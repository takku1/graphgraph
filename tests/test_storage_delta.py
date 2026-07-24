from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.io.core import load_any, save_graph
from graphgraph.storage.delta import (
    GraphDelta,
    append_delta,
    compact,
    delta_sidecar_path,
    load_with_deltas,
    save_incremental_validated_graph,
)


def _base_graph(n: int) -> Graph:
    nodes = {f"n{i}": Node(f"n{i}", f"sym{i}", "function", f"pkg/m{i}.py") for i in range(n)}
    edges = [Edge(f"n{i}", f"n{i+1}", "calls") for i in range(n - 1)]
    return Graph(nodes=nodes, edges=edges)


class AppendDeltaStoreTest(unittest.TestCase):
    def _saved_base(self, tmp: str, n: int = 6) -> Path:
        base = _base_graph(n)
        path = Path(tmp) / "graph.gg"
        save_graph(base, path)
        return path

    def test_replay_equals_direct_application(self) -> None:
        # A sequence of appended deltas must reconstruct exactly the graph a
        # full rewrite of the same edits would produce.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp)
            append_delta(path, GraphDelta(
                upsert_nodes=[Node("nX", "added", "function", "pkg/x.py")],
                upsert_edges=[Edge("n0", "nX", "calls")],
            ))
            append_delta(path, GraphDelta(
                delete_node_ids=["n5"],
                delete_edge_keys=[("n4", "n5", "calls")],
            ))
            replayed = load_with_deltas(path)

            expected = _base_graph(6)
            expected_nodes = dict(expected.nodes)
            expected_nodes["nX"] = Node("nX", "added", "function", "pkg/x.py")
            expected_nodes.pop("n5")
            expected_edges = [e for e in expected.edges if not (e.source == "n4" and e.target == "n5")]
            expected_edges.append(Edge("n0", "nX", "calls"))

            self.assertEqual(set(replayed.nodes), set(expected_nodes))
            self.assertEqual(
                {(e.source, e.target, e.type) for e in replayed.edges},
                {(e.source, e.target, e.type) for e in expected_edges},
            )

    def test_torn_delta_tail_is_ignored_and_base_survives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp)
            base_bytes = path.read_bytes()
            append_delta(path, GraphDelta(upsert_nodes=[Node("nX", "kept", "function", "x.py")]))
            sidecar = delta_sidecar_path(path)
            # Simulate an interrupted second append: a truncated trailing record.
            with sidecar.open("ab") as fh:
                fh.write(b"GGD1\xff\xff")  # header magic + partial length, then EOF
            merged = load_with_deltas(path)
            self.assertIn("nX", merged.nodes)          # the intact delta applied
            self.assertEqual(path.read_bytes(), base_bytes)  # base .gg untouched

    def test_corrupted_record_payload_stops_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp)
            append_delta(path, GraphDelta(upsert_nodes=[Node("nA", "a", "function", "a.py")]))
            append_delta(path, GraphDelta(upsert_nodes=[Node("nB", "b", "function", "b.py")]))
            sidecar = delta_sidecar_path(path)
            raw = bytearray(sidecar.read_bytes())
            raw[-1] ^= 0xFF  # corrupt the last record's payload -> crc mismatch
            sidecar.write_bytes(raw)
            merged = load_with_deltas(path)
            self.assertIn("nA", merged.nodes)      # first record intact
            self.assertNotIn("nB", merged.nodes)   # corrupted record dropped

    def test_compaction_folds_deltas_and_clears_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp)
            append_delta(path, GraphDelta(upsert_nodes=[Node("nX", "added", "function", "x.py")]))
            compacted = compact(path)
            self.assertIn("nX", compacted.nodes)
            self.assertFalse(delta_sidecar_path(path).exists())
            # The folded state is now the base itself.
            self.assertIn("nX", load_any(path).nodes)

    def test_append_cost_is_independent_of_graph_size(self) -> None:
        # The O(Δ) claim: the same one-node delta costs the same append bytes
        # against a tiny base and a 100x larger base -- the write does not scale
        # with N, unlike the full-rewrite store.
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "small.gg"
            large = Path(tmp) / "large.gg"
            save_graph(_base_graph(10), small)
            save_graph(_base_graph(1000), large)
            self.assertGreater(large.stat().st_size, small.stat().st_size * 10)

            d = GraphDelta(upsert_nodes=[Node("nX", "added", "function", "x.py")])
            small_sidecar = append_delta(small, d)
            large_sidecar = append_delta(large, d)
            self.assertEqual(small_sidecar.stat().st_size, large_sidecar.stat().st_size)
            # And the delta record is a small constant, not a fraction of N.
            self.assertLess(small_sidecar.stat().st_size, 1024)

    def test_append_is_faster_than_full_rewrite_on_a_larger_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.gg"
            big = _base_graph(4000)
            save_graph(big, path)

            def best(fn, n=5):
                return min(_timed(fn) for _ in range(n))

            d = GraphDelta(upsert_nodes=[Node("nX", "added", "function", "x.py")])
            append_ms = best(lambda: append_delta(path, d))
            save_ms = best(lambda: save_graph(big, path))
            self.assertLess(append_ms, save_ms)

    def test_exact_diff_preserves_metadata_and_location_scoped_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.gg"
            nodes = {
                "a": Node("a", "a", "function", "a.py"),
                "b": Node("b", "b", "function", "b.py"),
            }
            previous = Graph(
                nodes=nodes,
                edges=[
                    Edge("a", "b", "calls", source_location="a.py:1"),
                    Edge("a", "b", "calls", source_location="a.py:2"),
                ],
                metadata={"version": "old"},
            )
            current = Graph(
                nodes={**nodes, "c": Node("c", "c", "function", "c.py")},
                edges=[
                    Edge("a", "b", "calls", weight=2.0, source_location="a.py:2"),
                    Edge("b", "c", "calls", source_location="b.py:1"),
                ],
                metadata={"version": "new", "fresh": "true"},
            )
            save_graph(previous, path)
            append_delta(path, GraphDelta.between(previous, current))

            replayed = load_with_deltas(path)

            self.assertEqual(replayed.nodes, current.nodes)
            self.assertEqual(set(replayed.edges), set(current.edges))
            self.assertEqual(replayed.metadata, current.metadata)

    def test_promoted_incremental_save_is_visible_to_normal_cached_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.gg"
            previous = _base_graph(500)
            save_graph(previous, path)
            # Seed both normal cache paths before the sidecar exists.
            self.assertNotIn("nX", load_any(path).nodes)
            current = Graph(
                nodes={**previous.nodes, "nX": Node("nX", "added", "function", "x.py")},
                edges=[*previous.edges, Edge("n0", "nX", "calls", source_location="m0.py")],
                metadata={"updated": "true"},
            )

            save_incremental_validated_graph(previous, current, path)

            self.assertTrue(delta_sidecar_path(path).exists())
            loaded = load_any(path)
            self.assertIn("nX", loaded.nodes)
            self.assertEqual(loaded.metadata, {"updated": "true"})

    def test_full_rewrite_clears_stale_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp)
            append_delta(path, GraphDelta(upsert_nodes=[Node("nX", "stale", "function", "x.py")]))
            self.assertTrue(delta_sidecar_path(path).exists())

            replacement = _base_graph(3)
            save_graph(replacement, path)

            self.assertFalse(delta_sidecar_path(path).exists())
            self.assertEqual(set(load_any(path).nodes), set(replacement.nodes))

    def test_large_delta_uses_atomic_full_rewrite_cost_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp, n=20)
            previous = _base_graph(20)
            current = _base_graph(400)

            save_incremental_validated_graph(previous, current, path)

            self.assertFalse(delta_sidecar_path(path).exists())
            self.assertEqual(set(load_any(path).nodes), set(current.nodes))

    def test_concurrent_appends_are_serialized_as_complete_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._saved_base(tmp)
            deltas = [
                GraphDelta(upsert_nodes=[Node(f"x{i}", f"x{i}", "function", f"x{i}.py")])
                for i in range(8)
            ]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda delta: append_delta(path, delta), deltas))

            replayed = load_with_deltas(path)
            self.assertTrue(all(f"x{i}" in replayed.nodes for i in range(8)))


def _timed(fn) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


if __name__ == "__main__":
    unittest.main()
