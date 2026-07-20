from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
)
from graphgraph.analysis.eval import EvalTask, estimate_tokens, evaluate_graph
from graphgraph.io import (
    graph_to_json,
    load_any,
    load_csv_edges,
    load_gg,
    load_gg_text,
    load_graph,
    load_policies,
    save_gg,
    save_graph,
    save_validated_graph,
)
from graphgraph.packets.validation import validate_any, validate_graph_json

if TYPE_CHECKING:
    from graphgraph.runtime.cache import TopologicalKVCache


class IOTest(unittest.TestCase):
    def test_save_graph_persists_valid_pagerank_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            graph = sample_graph()
            save_graph(graph, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("centrality", raw)
            self.assertIn("pagerank", raw["centrality"])
            self.assertIsInstance(raw["centrality"]["pagerank"]["scores"], list)

            loaded = load_graph(path)
            self.assertIsNotNone(loaded._pagerank_cache)
            self.assertEqual(loaded.pagerank(), graph.pagerank())

    def test_graph_json_centrality_is_safe_for_case_insensitive_object_consumers(self) -> None:
        graph = Graph(
            nodes={
                "pkg__Lane": Node("pkg__Lane", "Lane"),
                "pkg__lane": Node("pkg__lane", "lane"),
            },
            edges=[Edge("pkg__Lane", "pkg__lane", "references")],
        )
        raw = json.loads(graph_to_json(graph))
        rows = raw["centrality"]["pagerank"]["scores"]
        self.assertEqual({row["id"] for row in rows}, {"pkg__Lane", "pkg__lane"})
        self.assertNotIsInstance(raw["centrality"]["pagerank"]["scores"], dict)

    def test_load_graph_rejects_stale_pagerank_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            graph = sample_graph()
            save_graph(graph, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["edges"].append({"source": "N3", "target": "N1", "type": "calls"})
            path.write_text(json.dumps(raw), encoding="utf-8")

            loaded = load_graph(path)
            self.assertIsNone(loaded._pagerank_cache)
            scores = loaded.pagerank()
            self.assertIsNotNone(loaded._pagerank_cache)
            self.assertIn("N1", scores)

    def test_load_graph_gives_clear_error_on_binary_gg_input(self) -> None:
        # Regression: load_graph() is JSON-only despite the generic-sounding
        # name; calling it on a .gg binary file used to fail deep inside
        # json.loads() with a raw UnicodeDecodeError. It should fail fast
        # with a message pointing at load_any() instead.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_gg(sample_graph(), path)
            with self.assertRaises(ValueError) as ctx:
                load_graph(path)
            self.assertIn("load_any", str(ctx.exception))
            # load_any() on the same file must actually work.
            loaded = load_any(path)
            self.assertEqual(set(loaded.nodes), set(sample_graph().nodes))

    def test_load_graph_gives_clear_error_on_non_json_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            path.write_text("not json at all", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_graph(path)
            self.assertIn("load_any", str(ctx.exception))

    def test_load_gg_text_preserves_distinct_nodes_with_duplicate_labels(self) -> None:
        # Regression: two distinct nodes sharing the exact same label (e.g.
        # two different "helper" functions in different files -- this
        # legacy text format has no other per-node qualifier) collided on
        # the same sanitized id. The rename-on-collision guard only fired
        # when labels *differed*, so a same-labeled node silently overwrote
        # the earlier one in `nodes`, discarding it entirely.
        text = "gg/1\nhelper [function] a.py\n  calls other 1.0\nhelper [function] c.py\nother [function] b.py\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.gg.txt"
            path.write_text(text, encoding="utf-8")
            graph = load_gg_text(path)
            self.assertEqual(len(graph.nodes), 3)
            paths = sorted(n.path for n in graph.nodes.values())
            self.assertEqual(paths, ["a.py", "b.py", "c.py"])

    def test_eval_graph_reports_recall_and_token_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), path)
            results = evaluate_graph(
                path, [EvalTask("auth service", "blast_radius", expected_nodes=("server/auth.py", "AuthService()"))]
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].node_recall, 1.0)
            self.assertGreater(results[0].token_estimate, 0)
            self.assertGreater(estimate_tokens("A -calls-> B"), 0)

    def test_load_graph_and_policies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            policies_path = root / "policies.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": [{"id": "N1", "label": "A"}, {"id": "N2", "label": "B"}],
                        "edges": [{"source": "N1", "target": "N2", "type": "calls", "weight": 0.7}],
                        "metadata": {"frontend": "regex"},
                    }
                ),
                encoding="utf-8",
            )
            policies_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "P1",
                            "kind": "frontend",
                            "priority": "must",
                            "applies_to": ["src/**"],
                            "task_tags": ["frontend"],
                            "compact": "UI compact",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            loaded = load_graph(graph_path)
            self.assertEqual(len(loaded.edges), 1)
            self.assertEqual(loaded.metadata["frontend"], "regex")
            self.assertEqual(load_policies(policies_path)[0].id, "P1")

    def test_load_graph_fallback_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "N1",
                                "name": "AuthService",
                                "file_type": "service",
                                "source_file": "server/auth.py",
                                "properties": {"description": "Handles authentication"},
                                "community": "auth",
                                "source_uri": "repo://server/auth.py",
                                "confidence": 0.95,
                                "active": True,
                                "created_at": "2026-06-01T00:00:00Z",
                            },
                            {"id": "N2", "type": "data", "facts": None},
                        ],
                        "edges": [
                            {
                                "source": "N1",
                                "target": "N2",
                                "relation": "reads",
                                "confidence": 0.75,
                                "provenance": "inferred",
                                "source_location": "server/auth.py:10",
                                "valid_from": "2026-06-01T00:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            graph = load_graph(graph_path)
            n1 = graph.nodes["N1"]
            self.assertEqual(n1.label, "AuthService")
            self.assertEqual(n1.kind, "service")
            self.assertEqual(n1.path, "server/auth.py")
            self.assertEqual(n1.summary, "Handles authentication")
            self.assertEqual(n1.facts, ())
            self.assertEqual(n1.scope, "auth")
            self.assertEqual(n1.source, "repo://server/auth.py")
            self.assertEqual(n1.confidence, 0.95)
            self.assertTrue(n1.active)
            self.assertEqual(n1.created_at, "2026-06-01T00:00:00Z")

            n2 = graph.nodes["N2"]
            self.assertEqual(n2.label, "N2")
            self.assertEqual(n2.kind, "data")
            self.assertEqual(n2.path, "")
            self.assertEqual(n2.summary, "")
            self.assertEqual(n2.facts, ())

            edge = graph.edges[0]
            self.assertEqual(edge.confidence, 0.75)
            self.assertEqual(edge.provenance, "inferred")
            self.assertEqual(edge.source_location, "server/auth.py:10")
            self.assertEqual(edge.valid_from, "2026-06-01T00:00:00Z")

    def test_save_graph_and_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input_graph.json"
            output_path = root / "output_graph.json"
            input_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "N1",
                                "name": "A",
                                "file_type": "code",
                                "properties": {"description": "summary text"},
                            }
                        ],
                        "links": [{"source": "N1", "target": "N1", "relation": "calls"}],
                    }
                ),
                encoding="utf-8",
            )
            graph = load_graph(input_path)
            save_graph(graph, output_path)

            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("nodes", data)
            self.assertIn("edges", data)
            self.assertEqual(data["nodes"][0]["label"], "A")
            self.assertEqual(data["nodes"][0]["kind"], "code")
            self.assertEqual(data["nodes"][0]["summary"], "summary text")
            self.assertEqual(data["edges"][0]["type"], "calls")

    def test_load_graph_can_materialize_external_reference_nodes_for_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graphify.json"
            path.write_text(
                json.dumps(
                    {
                        "nodes": [{"id": "requests_init", "label": "__init__.py", "file_type": "code"}],
                        "edges": [
                            {
                                "source": "requests_init",
                                "target": "urllib3",
                                "relation": "imports",
                                "confidence": "EXTRACTED",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            raw = load_any(path)
            raw_result = validate_graph_json(graph_to_json(raw))
            self.assertFalse(raw_result.ok)

            normalized = load_any(path, normalize_external_refs=True)
            self.assertIn("urllib3", normalized.nodes)
            self.assertEqual(normalized.nodes["urllib3"].kind, "external")
            self.assertIn("external:unresolved", normalized.nodes["urllib3"].facts)
            self.assertEqual(normalized.metadata["external_reference_nodes"], "1")
            normalized_result = validate_graph_json(graph_to_json(normalized))
            self.assertTrue(normalized_result.ok, normalized_result.errors)

    def test_validate_graph_json_accepts_saved_graphs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            result = validate_graph_json(graph_path.read_text(encoding="utf-8"))
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.format, "graph_json")
            self.assertEqual(result.node_count, 3)
            self.assertEqual(result.edge_count, 2)
            self.assertEqual(validate_any(graph_path.read_text(encoding="utf-8")).format, "graph_json")

    def test_validate_graph_json_rejects_edges_to_missing_nodes(self) -> None:
        payload = json.dumps(
            {
                "nodes": [{"id": "A", "label": "A"}],
                "edges": [{"source": "A", "target": "B", "type": "calls"}],
            }
        )
        result = validate_graph_json(payload)
        self.assertFalse(result.ok)
        self.assertIn("edge target missing from nodes: B", result.errors)

    def test_save_validated_graph_refuses_invalid_graph_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            before = graph_path.read_text(encoding="utf-8")
            bad_graph = Graph(nodes={"A": Node("A", "A")}, edges=[Edge("A", "B", "calls")])

            with self.assertRaisesRegex(ValueError, "Refusing to write invalid graph JSON"):
                save_validated_graph(bad_graph, graph_path)

            self.assertEqual(graph_path.read_text(encoding="utf-8"), before)

    def test_save_load_gg_roundtrip_preserves_graph_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            graph = Graph(
                nodes={
                    "N1": Node(
                        "N1",
                        "AuthService",
                        "service",
                        "server/auth.py",
                        summary="L10 authenticates users",
                        facts=("uses constant-time compare",),
                        scope="server",
                        parent="P1",
                        source="scanner",
                        confidence=0.95,
                        created_at="2026-07-05T00:00:00Z",
                        updated_at="2026-07-05T01:00:00Z",
                    ),
                    "N2": Node("N2", "TokenStore", "data", "server/tokens.py", active=False),
                },
                edges=[
                    Edge(
                        "N1",
                        "N2",
                        "reads",
                        weight=0.75,
                        confidence=0.8,
                        provenance="ast",
                        evidence="AuthService.reads(TokenStore)",
                        source_location="server/auth.py:12",
                        valid_from="2026-07-05T00:00:00Z",
                    )
                ],
                metadata={"project": "sample"},
            )

            save_graph(graph, path)
            loaded = load_any(path)

            self.assertEqual(loaded.nodes["N1"], graph.nodes["N1"])
            self.assertEqual(loaded.nodes["N2"], graph.nodes["N2"])
            self.assertEqual(loaded.edges, graph.edges)
            self.assertEqual(loaded.metadata["project"], "sample")

    def test_save_graph_binary_preserves_prior_file_on_write_failure(self) -> None:
        # Regression: save_graph_binary() used to open the destination with
        # path.open("wb"), which truncates the file immediately. A failure
        # partway through writing -- e.g. a label/summary/fact containing an
        # unpaired UTF-16 surrogate, which can occur naturally from
        # mis-decoded source text and can't be UTF-8 encoded -- left the
        # previously-good persisted .gg file destroyed instead of just
        # failing the save.
        from graphgraph.storage.backends import save_graph_binary

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            good = Graph(nodes={"N1": Node("N1", "Good", "file")}, edges=[])
            save_graph_binary(good, path)
            before = path.read_bytes()

            poisoned = Graph(nodes={"N1": Node("N1", "bad\udcffvalue", "file")}, edges=[])
            with self.assertRaises(UnicodeEncodeError):
                save_graph_binary(poisoned, path)

            self.assertEqual(path.read_bytes(), before)
            # No leftover temp files from the aborted write.
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_load_gg_preserves_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.gg"
            path.write_text("gg/1\nMyService [service] server/svc.py\n", encoding="utf-8")
            g = load_gg(path)
            self.assertEqual(len(g.nodes), 1)
            node = list(g.nodes.values())[0]
            self.assertEqual(node.kind, "service")
            self.assertEqual(node.path, "server/svc.py")

    def test_load_any_routes_gg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g = sample_graph()
            path = Path(tmp) / "graph.gg"
            save_gg(g, path)
            g2 = load_any(path)
            self.assertEqual(len(g.nodes), len(g2.nodes))

    def test_reciprocal_rank_and_ndcg(self) -> None:
        from graphgraph.analysis.eval import ndcg_at_k, reciprocal_rank

        ranked = ["A", "B", "C", "D", "E"]
        expected = {"C", "E"}

        # First expected node is at rank 3 -> RR = 1/3
        self.assertAlmostEqual(reciprocal_rank(ranked, expected), 0.3333333333333333)
        self.assertEqual(reciprocal_rank(ranked, {"X"}), 0.0)

        # NDCG@5: DCG@5 = 1/log2(3+1) + 1/log2(5+1) = 0.5 + 0.38685 = 0.88685
        # IDCG@5: expected size is 2, so ideal is ranks 1, 2: 1/log2(1+1) + 1/log2(2+1) = 1.0 + 0.6309 = 1.6309
        # NDCG = 0.88685 / 1.6309 = 0.54378
        self.assertAlmostEqual(ndcg_at_k(ranked, expected, 5), 0.5437798, places=4)
        self.assertEqual(ndcg_at_k(ranked, expected, 0), 0.0)
        self.assertEqual(ndcg_at_k(ranked, set(), 5), 0.0)

    def test_rank_nodes_by_subgraph_pagerank(self) -> None:
        from graphgraph.analysis.eval import rank_nodes_by_subgraph_pagerank

        g = sample_graph()
        # g has N1 -> N2 -> N3
        retrieved_nodes = {"N1", "N2", "N3"}
        retrieved_edges = g.edges
        ranked = rank_nodes_by_subgraph_pagerank(g, retrieved_nodes, retrieved_edges)
        self.assertEqual(set(ranked), retrieved_nodes)
        self.assertEqual(len(ranked), 3)

    def test_save_validated_graph_routes_backend_suffixes(self) -> None:
        from graphgraph.io import save_validated_graph

        with tempfile.TemporaryDirectory() as tmp:
            g = sample_graph()
            path = Path(tmp) / "g.gg"
            result = save_validated_graph(g, path)
            self.assertTrue(result.ok)
            self.assertEqual(result.format, "graph.gg")
            self.assertTrue(path.exists())
            g2 = load_any(path)
            self.assertEqual(set(g.nodes), set(g2.nodes))

    def test_native_save_validates_graph_without_materializing_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            with patch(
                "graphgraph.io.core.graph_to_json",
                side_effect=AssertionError("native saves must not serialize JSON"),
            ):
                result = save_validated_graph(sample_graph(), path)

            self.assertTrue(result.ok)
            self.assertEqual(result.format, "graph.gg")
            self.assertEqual(set(load_any(path).nodes), set(sample_graph().nodes))

    def test_ggb_is_read_only_and_migrates_to_gg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "graph.gg"
            legacy = root / "graph.ggb"
            save_gg(sample_graph(), canonical)
            canonical.replace(legacy)

            loaded = load_any(legacy)
            self.assertEqual(set(loaded.nodes), set(sample_graph().nodes))
            with self.assertRaisesRegex(ValueError, "read-only migration format"):
                save_graph(sample_graph(), legacy)
            with self.assertRaisesRegex(ValueError, "read-only migration format"):
                save_validated_graph(sample_graph(), legacy)
            with self.assertRaisesRegex(ValueError, "must use the .gg suffix"):
                save_gg(sample_graph(), legacy)

    def test_explicit_test_root_remains_attributed_direct_evidence(self) -> None:
        from graphgraph.retrieval.context import affected_test_recommendations

        graph = Graph(
            nodes={
                "SAVE": Node(
                    "SAVE",
                    "save_validated_graph",
                    "function",
                    "src/graphgraph/io/core.py",
                ),
                "TEST": Node(
                    "TEST",
                    "test_native_save_avoids_json",
                    "function",
                    "tests/test_io.py",
                ),
            },
            edges=[Edge("TEST", "SAVE", "calls")],
        )

        affected = affected_test_recommendations(
            graph,
            ("SAVE", "TEST"),
            {"SAVE", "TEST"},
        )

        self.assertEqual([item["id"] for item in affected["direct"]], ["TEST"])
        self.assertEqual(affected["direct"][0]["distance"], 1)
        self.assertEqual(
            affected["commands"],
            ["python -m pytest tests/test_io.py"],
        )

    def test_test_path_detection_requires_structural_evidence_under_src(self) -> None:
        from graphgraph.retrieval.scoping import _is_test_node, _is_test_path

        production_path = "src/graphgraph/retrieval/test_recommendations.py"
        self.assertFalse(_is_test_path(production_path))
        self.assertFalse(_is_test_node(Node(
            "PRODUCTION",
            "affected_test_recommendations",
            "function",
            production_path,
        )))

        self.assertTrue(_is_test_path("tests/test_recommendations.py"))
        self.assertTrue(_is_test_path("src/ui/recommendations.test.ts"))
        self.assertTrue(_is_test_node(Node(
            "TEST",
            "test_recommendations",
            "function",
            "tests/test_recommendations.py",
        )))

    def test_load_csv_edges_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.csv"
            path.write_text("source,target,type,weight\nA,B,calls,0.9\nB,C,imports,1.0\n", encoding="utf-8")
            g = load_csv_edges(path)
            self.assertEqual(len(g.nodes), 3)
            self.assertEqual(len(g.edges), 2)
            self.assertEqual(g.edges[0].weight, 0.9)

    def test_load_csv_edges_no_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.csv"
            path.write_text("Foo,Bar\nBaz,Qux\n", encoding="utf-8")
            g = load_csv_edges(path)
            self.assertEqual(len(g.nodes), 4)
            self.assertEqual(len(g.edges), 2)
            self.assertEqual(g.edges[0].type, "relates")

    def test_load_tsv_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.tsv"
            path.write_text("X\tY\tcalls\nY\tZ\treads\n", encoding="utf-8")
            g = load_csv_edges(path)
            self.assertEqual(len(g.nodes), 3)
            self.assertEqual(len(g.edges), 2)

    def test_load_any_routes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.csv"
            path.write_text("A,B\nC,D\n", encoding="utf-8")
            g = load_any(path)
            self.assertEqual(len(g.nodes), 4)

    def test_merge_graphify_enriches_base_adds_overlay_and_dedupes_edges(self) -> None:
        # Coverage gap: merge_graphify is a real, exported io primitive (merge
        # an overlay graph -- e.g. from graphify -- into an existing scanned
        # base graph, enriching matching nodes and adding overlay-only ones)
        # but had zero test coverage. Not currently wired into `cmd_ingest`
        # (which replaces wholesale rather than merging) -- that's a CLI
        # behavior decision left alone -- but the function itself should be
        # verified to actually do what its docstring says.
        from graphgraph.io import merge_graphify

        base = Graph(
            nodes={
                "A": Node("A", "AuthService", "service", "server/auth.py", summary="", facts=()),
                "B": Node("B", "TokenStore", "data", "server/tokens.py"),
            },
            edges=[Edge("A", "B", "reads", 0.9)],
        )
        overlay = Graph(
            nodes={
                # Same path as base "A" -- should enrich, not duplicate.
                "ext-A": Node(
                    "ext-A",
                    "AuthService",
                    "service",
                    "server/auth.py",
                    summary="Handles login",
                    facts=("owns sessions",),
                ),
                # Overlay-only node -- should be added verbatim.
                "ext-C": Node("ext-C", "AuditLog", "data", "server/audit.py"),
            },
            edges=[
                # Resolves through the path-matched id remap (ext-A -> A) and B is untouched -- new edge.
                Edge("ext-A", "B", "writes", 0.5),
                # Duplicate of an edge already in base -- must not be added twice.
                Edge("ext-A", "B", "reads", 0.9),
                # Dangling endpoint (no such overlay/base node) -- must be dropped silently, not crash.
                Edge("ext-A", "missing-node", "calls", 1.0),
            ],
        )

        merged = merge_graphify(base, overlay)

        self.assertEqual(set(merged.nodes), {"A", "B", "ext-C"})
        self.assertEqual(merged.nodes["A"].summary, "Handles login")
        self.assertEqual(merged.nodes["A"].facts, ("owns sessions",))
        self.assertEqual(merged.nodes["ext-C"].label, "AuditLog")

        edge_keys = {(e.source, e.target, e.type) for e in merged.edges}
        self.assertEqual(edge_keys, {("A", "B", "reads"), ("A", "B", "writes")})

    def test_kv_cache(self) -> None:
        import time

        from graphgraph.runtime.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            cache_path = tmp / "kv_cache.json"

            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(cache_path)
            key = compute_cache_key(["N1", "N2"], "blast_radius", 2, "gg")

            self.assertIsNone(cache.get(graph_path, key))
            cache.set(graph_path, key, "rendered_packet_data")
            self.assertEqual(cache.get(graph_path, key), "rendered_packet_data")
            self.assertEqual(cache.cache_data[key]["node_ids"], [])
            self.assertEqual(cache.cache_data[key]["paths"], [])

            time.sleep(0.01)
            graph_path.write_text('{"nodes": {}}', encoding="utf-8")
            self.assertIsNone(cache.get(graph_path, key))

    def test_kv_cache_records_packet_dependencies(self) -> None:
        from graphgraph.runtime.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(tmp / "kv_cache.json")
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg")
            cache.set(graph_path, key, "packet", node_ids={"B", "A"}, paths={"src/a.py", ""})

            loaded = TopologicalKVCache(tmp / "kv_cache.json")
            self.assertEqual(loaded.get(graph_path, key), "packet")
            self.assertEqual(loaded.cache_data[key]["node_ids"], ["A", "B"])
            self.assertEqual(loaded.cache_data[key]["paths"], ["src/a.py"])

    def _dependency_cache_fixture(self, tmp: Path) -> tuple[Path, "TopologicalKVCache"]:
        from graphgraph.runtime.cache import TopologicalKVCache

        (tmp / "src").mkdir()
        (tmp / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
        (tmp / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
        graph_path = tmp / ".graphgraph" / "graph.json"
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        graph_path.write_text("{}", encoding="utf-8")
        cache = TopologicalKVCache(tmp / ".graphgraph" / "kv_cache.json")
        return graph_path, cache

    def test_kv_cache_invalidates_when_graph_changes_even_if_known_dependency_is_unchanged(self) -> None:
        import time

        from graphgraph.runtime.cache import compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path, cache = self._dependency_cache_fixture(tmp)
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg")
            cache.set(graph_path, key, "packet-for-a", node_ids={"A"}, paths={"src/a.py"})

            # Rescan bumps the graph file's mtime (e.g. an incremental scan that
            # introduced a new caller from b.py). The old packet only recorded
            # a.py, so positive dependency hashes alone cannot prove that its
            # topology is still complete.
            time.sleep(0.01)
            graph_path.write_text('{"edges": [["B", "A", "calls"]]}', encoding="utf-8")

            self.assertIsNone(cache.get(graph_path, key))

    def test_kv_cache_survives_timestamp_only_graph_rewrite(self) -> None:
        import time

        from graphgraph.runtime.cache import compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path, cache = self._dependency_cache_fixture(tmp)
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg")
            cache.set(graph_path, key, "packet-for-a", node_ids={"A"}, paths={"src/a.py"})

            original = graph_path.read_bytes()
            time.sleep(0.01)
            graph_path.write_bytes(original)

            self.assertEqual(cache.get(graph_path, key), "packet-for-a")

    def test_kv_cache_evicts_when_dependency_changes(self) -> None:
        import time

        from graphgraph.runtime.cache import compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path, cache = self._dependency_cache_fixture(tmp)
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg")
            cache.set(graph_path, key, "packet-for-a", node_ids={"A"}, paths={"src/a.py"})

            time.sleep(0.01)
            (tmp / "src" / "a.py").write_text("A = 2  # changed\n", encoding="utf-8")
            graph_path.write_text('{"nodes": {"rescanned": true}}', encoding="utf-8")

            self.assertIsNone(cache.get(graph_path, key))

    def test_kv_cache_stats(self) -> None:
        from graphgraph.runtime.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(tmp / "kv_cache.json")
            key = compute_cache_key(["A"], "direct_lookup", 1, "sql")

            cache.get(graph_path, key)  # miss
            cache.set(graph_path, key, "data")
            cache.get(graph_path, key)  # hit

            s = cache.stats()
            self.assertEqual(s["hits"], 1)
            self.assertEqual(s["misses"], 1)
            self.assertEqual(s["entries"], 1)
            self.assertEqual(s["hit_rate_pct"], 50)

    def test_kv_cache_lru_eviction(self) -> None:
        from graphgraph.runtime.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(tmp / "kv_cache.json", max_entries=3)

            for i in range(4):
                k = compute_cache_key([f"N{i}"], "direct_lookup", 1, "sql")
                cache.set(graph_path, k, f"packet_{i}")

            self.assertLessEqual(len(cache.cache_data), 3)

    def test_kv_cache_clear(self) -> None:
        from graphgraph.runtime.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(tmp / "kv_cache.json")
            k = compute_cache_key(["X"], "direct_lookup", 1, "sql")
            cache.set(graph_path, k, "payload")
            self.assertEqual(len(cache.cache_data), 1)

            removed = cache.clear()
            self.assertEqual(removed, 1)
            self.assertEqual(len(cache.cache_data), 0)

    def test_public_graph_cache_clear_resets_every_load_layer(self) -> None:
        from graphgraph.io import clear_graph_cache, load_any_cached

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), path)
            first = load_any_cached(path)
            self.assertIs(load_any_cached(path), first)

            self.assertGreaterEqual(clear_graph_cache(), 1)
            self.assertIsNot(load_any_cached(path), first)
