from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.io import load_any, save_graph
from graphgraph.retrieval.relations import query_relations, query_saved_relations
from graphgraph.storage.backends import _save_graph_binary_v3
from graphgraph.storage.delta import GraphDelta, append_delta
from graphgraph.storage.sectioned import (
    GGB4_MAGIC,
    load_sectioned_relation_view,
    read_sectioned_directory,
)


def _graph() -> Graph:
    return Graph(
        nodes={
            "TARGET": Node("TARGET", "work", "function", "src/core.py", "L10", facts=("typed",)),
            "CALLER": Node("CALLER", "run", "function", "src/app.py", "L20"),
            "TEST": Node("TEST", "test_work", "function", "tests/test_core.py", "L30"),
            "CALLEE": Node("CALLEE", "helper", "function", "src/helper.py", "L40"),
            "EXTERNAL": Node("EXTERNAL", "append", "external"),
            "INACTIVE": Node("INACTIVE", "old", "function", "src/old.py", active=False),
        },
        edges=[
            Edge("CALLER", "TARGET", "calls", confidence=0.95, provenance="tree_sitter", evidence="a"),
            Edge("CALLER", "TARGET", "calls", confidence=0.80, provenance="regex", source_location="fallback"),
            Edge("TEST", "TARGET", "calls", confidence=0.90, provenance="tree_sitter"),
            Edge("TARGET", "CALLEE", "calls", confidence=0.85, provenance="tree_sitter"),
            Edge("TARGET", "EXTERNAL", "calls", confidence=0.50, provenance="external"),
            Edge("INACTIVE", "TARGET", "calls", active=False),
        ],
        metadata={
            "member_calls_global_resolved": "12",
            "member_calls_global_unknown_receiver": "0",
            "member_calls_global_ambiguous": "0",
            "member_calls_global_scope": "full_scan",
            "custom": "full fidelity",
        },
    )


class SectionedStorageTest(unittest.TestCase):
    def test_ggb4_is_the_only_writer_and_round_trips_full_fidelity(self) -> None:
        graph = _graph()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(graph, path)
            self.assertEqual(path.read_bytes()[:4], GGB4_MAGIC)
            loaded = load_any(path)

        self.assertEqual(loaded.nodes, graph.nodes)
        self.assertEqual(loaded.edges, graph.edges)
        self.assertEqual(loaded.metadata, graph.metadata)

    def test_save_survives_a_transient_reader_holding_the_destination(self) -> None:
        """A reader must not be able to destroy a completed scan.

        Readers of a .gg take no lock. On Windows os.replace raises
        PermissionError while any handle is open on the destination, and the
        writer's cleanup handler deletes the staged temp file -- so a bare
        replace turned a momentary read into permanent loss of the graph.
        """
        import dataclasses
        from unittest import mock

        from graphgraph.storage import sectioned

        graph = _graph()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(graph, path)
            original = path.read_bytes()

            calls: list[int] = []
            real_replace = Path.replace

            def flaky_replace(self: Path, target):  # type: ignore[no-untyped-def]
                calls.append(1)
                if len(calls) == 1:
                    raise PermissionError(32, "The process cannot access the file")
                return real_replace(self, target)

            updated = _graph()
            updated.nodes["TARGET"] = dataclasses.replace(
                updated.nodes["TARGET"], summary="rewritten after contention"
            )

            with mock.patch.object(Path, "replace", flaky_replace):
                sectioned.save_sectioned_graph(updated, path)

            self.assertGreater(len(calls), 1, "expected the writer to retry the rename")
            self.assertNotEqual(path.read_bytes(), original)
            self.assertEqual(load_any(path).nodes["TARGET"].summary, "rewritten after contention")
            leftovers = [p.name for p in Path(tmp).iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [], "staged temp file was left behind")

    def test_partial_relation_view_matches_resident_graph(self) -> None:
        graph = _graph()
        cases = [
            ("work", {"direction": "callers"}),
            ("src/core.py::work", {"direction": "callers", "include_tests": False}),
            ("work", {"direction": "callers", "limit": 1}),
            ("work", {"direction": "callers", "details": True}),
            ("work", {"direction": "callees"}),
            ("work", {"direction": "callees", "include_external": True, "freshness": "fresh"}),
            ("missing", {"direction": "callers"}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(graph, path)
            view = load_sectioned_relation_view(path)
            self.assertNotIn("INACTIVE", {node.id for node in view.nodes})
            for target, options in cases:
                with self.subTest(target=target, options=options):
                    self.assertEqual(
                        query_saved_relations(path, target, **options),
                        query_relations(graph, target, **options),
                    )

    def test_exact_relation_uses_packed_indexes_without_materializing_view(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(_graph(), path)
            with mock.patch(
                "graphgraph.retrieval.relations.load_sectioned_relation_view",
                side_effect=AssertionError("packed GGB4 lookup must not materialize the legacy relation view"),
            ):
                result = query_saved_relations(
                    path,
                    "src/core.py::work",
                    direction="callers",
                    include_tests=False,
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual([row["label"] for row in result["neighbors"]], ["run"])

    def test_full_load_checks_cold_sections_while_partial_read_is_selective(self) -> None:
        graph = _graph()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(graph, path)
            edge = read_sectioned_directory(path).sections[b"EDGE"]
            with path.open("r+b") as handle:
                handle.seek(edge.offset)
                original = handle.read(1)
                handle.seek(edge.offset)
                handle.write(bytes([original[0] ^ 0xFF]))

            # Exact relations do not read the full EDGE section.
            self.assertEqual(query_saved_relations(path, "work", direction="callers")["status"], "ok")
            with self.assertRaisesRegex(ValueError, "EDGE"):
                load_any(path)

    def test_relation_section_corruption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(_graph(), path)
            calls = read_sectioned_directory(path).sections[b"CALL"]
            with path.open("r+b") as handle:
                handle.seek(calls.offset)
                original = handle.read(1)
                handle.seek(calls.offset)
                handle.write(bytes([original[0] ^ 0xFF]))
            with self.assertRaisesRegex(ValueError, "CALL"):
                query_saved_relations(path, "work", direction="callers")

    def test_legacy_ggb3_loads_and_rewrites_as_ggb4(self) -> None:
        graph = _graph()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            _save_graph_binary_v3(graph, path)
            self.assertEqual(path.read_bytes()[:4], b"GGB3")
            migrated = load_any(path)
            save_graph(migrated, path)
            self.assertEqual(path.read_bytes()[:4], GGB4_MAGIC)
            self.assertEqual(load_any(path).nodes, graph.nodes)

    def test_current_delta_forces_full_fidelity_relation_fallback(self) -> None:
        graph = _graph()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(graph, path)
            append_delta(
                path,
                GraphDelta(
                    upsert_nodes=[Node("NEW", "new_caller", "function", "src/new.py")],
                    upsert_edges=[Edge("NEW", "TARGET", "calls", confidence=0.99)],
                ),
            )
            result = query_saved_relations(path, "work", direction="callers")

        self.assertIn("new_caller", {neighbor["label"] for neighbor in result["neighbors"]})


if __name__ == "__main__":
    unittest.main()
