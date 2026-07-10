from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
    expire_node,
)
from graphgraph.doccode import summarize_doc_code_components, summarize_doc_code_coverage
from graphgraph.io import (
    save_graph,
)
from graphgraph.retrieval import (
    retrieve_context,
    search_nodes,
    tokenize,
)
from graphgraph.services import render_final_packet, render_query_context, render_source_snippets
from graphgraph.services.context import resolve_start_nodes


class RetrievalTest(unittest.TestCase):
    def test_spreading_activation_retrieval(self) -> None:
        graph = sample_graph()
        from graphgraph.retrieval.activation import ActivationStateCache
        from graphgraph.retrieval.context import retrieve_context

        cache = ActivationStateCache()
        if cache.cache_path.exists():
            try:
                cache.cache_path.unlink()
            except Exception:
                pass

        result = retrieve_context(graph, "auth service", "spreading_activation", hops=2, max_nodes=5)
        self.assertIn("N1", result.nodes)
        self.assertIn("N2", result.nodes)
        self.assertIn("N3", result.nodes)

        state = cache.load()
        self.assertIn("N1", state)

        result2 = retrieve_context(graph, "audit log", "spreading_activation", hops=2, max_nodes=5)
        self.assertIn("N3", result2.nodes)
        self.assertIn("N1", result2.nodes)

    def test_spreading_activation_filters_stale_cached_nodes(self) -> None:
        graph = sample_graph()
        from graphgraph.retrieval.activation import spreading_activation

        nodes, edges = spreading_activation(
            graph,
            ["N1"],
            max_nodes=5,
            previous_activation={"ghost_node_from_old_scan": 100.0, "N2": 0.25},
        )
        self.assertNotIn("ghost_node_from_old_scan", nodes)
        self.assertTrue(nodes <= set(graph.nodes))
        self.assertTrue(all(edge.source in nodes and edge.target in nodes for edge in edges))

    def test_spreading_activation_excludes_soft_deleted_cached_nodes(self) -> None:
        # Regression: unlike search_nodes/expand/pagerank/degree elsewhere in
        # the system, spreading_activation never checked node.active anywhere
        # -- not on injected starts, not on previous_activation, not on the
        # final selected_nodes filter. previous_activation is loaded from a
        # cache file that persists across turns (.graphgraph/activation_state
        # .json); if the graph mutates between turns (e.g. N2 gets soft-
        # deleted via expire_node because its file was removed/merged), the
        # stale cached energy for N2 got reinjected and N2 could resurface in
        # selected_nodes even though it's no longer live -- the same
        # soft-delete leak search_nodes had before it started filtering on
        # .active. This differs from the "ghost_node_from_old_scan" case
        # above: that node is entirely absent from graph.nodes, whereas N2
        # here still exists in graph.nodes with active=False.
        from graphgraph.retrieval.activation import spreading_activation

        graph = sample_graph()
        graph, _ = expire_node(graph, "N2", "2026-07-08T00:00:00Z", reason="removed")

        nodes, edges = spreading_activation(
            graph,
            [],
            max_nodes=5,
            previous_activation={"N2": 1.0},
        )
        self.assertNotIn("N2", nodes)
        self.assertTrue(all(edge.source in nodes and edge.target in nodes for edge in edges))

    def test_spreading_activation_numeric_alpha_and_steps(self) -> None:
        graph = sample_graph()
        from graphgraph.retrieval.activation import ActivationStateCache, spreading_activation

        cache = ActivationStateCache()
        if cache.cache_path.exists():
            try:
                cache.cache_path.unlink()
            except Exception:
                pass

        spreading_activation(graph, ["N1"], max_nodes=10)
        state = cache.load()

        # alpha=0.6, decay=0.6, steps=2 defaults:
        #   step0: N1=1.0 (injection) spreads 0.6*1.0/1 to N2 => N2=0.6
        #   step1: N1 receives 0.6*0.6/2 back from N2 (N1,N3 neighbors of N2) => N1=1.18
        #          N2 receives another 0.6*1.0/1 from N1 => N2=1.2
        #          N3 receives 0.6*0.6/2 from N2 => N3=0.18
        self.assertAlmostEqual(state["N1"], 1.18, places=6)
        self.assertAlmostEqual(state["N2"], 1.2, places=6)
        self.assertAlmostEqual(state["N3"], 0.18, places=6)

    def test_spreading_activation_numeric_decay_isolated(self) -> None:
        from graphgraph.retrieval.activation import ActivationStateCache, spreading_activation

        graph = Graph(nodes={"A": Node("A", "A", "service", "a.py")}, edges=[])
        cache = ActivationStateCache()
        if cache.cache_path.exists():
            try:
                cache.cache_path.unlink()
            except Exception:
                pass

        # No new injection (empty starts); only decay of prior-turn activation.
        spreading_activation(graph, [], max_nodes=10, previous_activation={"A": 1.0})
        state = cache.load()
        self.assertAlmostEqual(state["A"], 0.6, places=6)  # 1.0 * decay(0.6)

    def test_retrieval_finds_anchor_from_query_text(self) -> None:
        graph = sample_graph()
        matches = search_nodes(graph, "auth service", limit=2)
        self.assertEqual(matches[0].node.id, "N1")
        result = retrieve_context(graph, "auth service", "blast_radius", hops=2)
        self.assertEqual(result.starts[0], "N1")
        self.assertEqual(result.nodes, {"N1", "N2", "N3"})

    def test_search_prefers_source_over_tests_unless_query_mentions_tests(self) -> None:
        graph = Graph(
            nodes={
                "SRC": Node("SRC", "scan_directory", "function", "src/graphgraph/scanner/core.py"),
                "TEST": Node("TEST", "test_scan_directory", "function", "tests/test_graphgraph_core.py"),
            }
        )
        self.assertEqual(search_nodes(graph, "scan directory", limit=2)[0].node.id, "SRC")
        self.assertEqual(search_nodes(graph, "test scan directory", limit=2)[0].node.id, "TEST")

    def test_search_nodes_penalizes_external_nodes_unless_intent_gate_matches(self) -> None:
        graph = Graph(
            nodes={
                "LOCAL": Node("LOCAL", "urllib3_client", "function", "src/client.py"),
                "EXT": Node("EXT", "urllib3", "external"),
            }
        )
        # Broad query: local code should win over external node because of the external_unresolved_penalty/external_dependency_penalty
        matches = search_nodes(graph, "urllib3 client", limit=2)
        self.assertEqual(matches[0].node.id, "LOCAL")

        # Query targeting the dependency with a single term: both are exact, but external has a smaller penalty and is direct match
        matches_single = search_nodes(graph, "urllib3", limit=2)
        self.assertEqual(matches_single[0].node.id, "EXT")

        # Query with explicit dependency/import keywords: intent gate opens for external node
        matches_dep = search_nodes(graph, "urllib3 dependency", limit=2)
        self.assertEqual(matches_dep[0].node.id, "EXT")

    def test_search_nodes_exact_phrase_bonus_fires_through_stopwords(self) -> None:
        # Regression: the query side tokenizes with stopwords removed
        # (tokenize(query)), but label_term_sequence/label_exact_sequence
        # (built in _search_index) keep them, since a label like
        # "how to deploy" needs "how"/"to" to reconstruct its real sequence.
        # A query that's an exact phrase match for such a label could never
        # equal that stopword-preserving sequence, so the +36
        # label_exact_terms bonus could never fire for any label containing
        # a stopword.
        graph = Graph(
            nodes={
                "A": Node("A", "how to deploy", "section", "docs/deploy.md"),
            }
        )
        matches = search_nodes(graph, "how to deploy", limit=5)
        self.assertEqual(len(matches), 1)
        self.assertIn("label_exact_terms", matches[0].reasons)

    def test_search_nodes_excludes_expired_nodes(self) -> None:
        # Regression: _search_index iterated graph.nodes.values() with no
        # active filter, unlike pagerank/expand/degree elsewhere in the
        # system. A node soft-deleted via expire_node could still be
        # returned as a top search hit, and expand() would then silently
        # drop it as an anchor, producing an empty/degraded context packet.
        graph = Graph(
            nodes={
                "A": Node("A", "quadpoly_solver", "function", "src/solver.py"),
            }
        )
        matches = search_nodes(graph, "quadpoly_solver", limit=5)
        self.assertEqual([m.node.id for m in matches], ["A"])

        graph, _ = expire_node(graph, "A", "2026-07-08T00:00:00Z", reason="removed")
        matches_after = search_nodes(graph, "quadpoly_solver", limit=5)
        self.assertEqual(matches_after, ())

    def test_search_nodes_respects_scope(self) -> None:
        graph = Graph(
            nodes={
                "BACKEND": Node("BACKEND", "Alpha", "function", "backend/a.py"),
                "FRONTEND": Node("FRONTEND", "Alpha", "function", "frontend/a.ts"),
            }
        )
        matches = search_nodes(graph, "alpha", limit=5, scopes=("backend",))
        self.assertEqual([match.node.id for match in matches], ["BACKEND"])

    def test_structural_queries_prefer_code_anchors_over_docs(self) -> None:
        graph = Graph(
            nodes={
                "D": Node("D", "Alpha Beta Search", "section", "docs/search.md"),
                "C": Node("C", "Alpha Beta Search", "python", "src/search.py"),
                "M": Node("M", "MCTS", "python", "src/mcts.py"),
            },
            edges=[Edge("C", "M", "calls")],
        )
        result = retrieve_context(graph, "alpha beta search mcts", "blast_radius", hops=1, max_nodes=4)
        self.assertEqual(result.starts[0], "C")
        self.assertIn("M", result.nodes)

    def test_status_queries_penalize_floating_concepts_as_anchors(self) -> None:
        graph = Graph(
            nodes={
                "CONCEPT": Node("CONCEPT", "operator planning status", "concept"),
                "CODE": Node("CODE", "operator planning status", "function", "src/operator/planning.py"),
                "FW": Node("FW", "firmware status", "function", "src/firmware/com.cpp"),
            },
            edges=[Edge("CODE", "FW", "mentions", confidence=0.2, provenance="doc_link")],
        )
        matches = search_nodes(graph, "operator planning status", limit=2)
        self.assertEqual(matches[0].node.id, "CODE")
        result = retrieve_context(graph, "operator planning status", "subsystem_summary", hops=1, max_nodes=8)
        self.assertEqual(result.starts[0], "CODE")

    def test_doc_queries_can_still_use_concept_anchors(self) -> None:
        graph = Graph(
            nodes={
                "CONCEPT": Node("CONCEPT", "installation guide", "concept"),
                "DOC": Node("DOC", "installation guide", "section", "README.md"),
                "CODE": Node("CODE", "installation guide", "function", "src/install.py"),
            },
            edges=[Edge("DOC", "CONCEPT", "discusses")],
        )
        matches = search_nodes(graph, "README installation guide", limit=3, doc_intensity=1.0)
        self.assertIn(matches[0].node.id, {"DOC", "CONCEPT"})

    def test_doc_code_pairing_matrix_separates_coverage_gaps(self) -> None:
        graph = Graph(
            nodes={
                "D": Node("D", "Doc Concept", "section", "docs/doc.md"),
                "C": Node("C", "Doc Concept", "function", "src/doc_concept.py"),
                "DO": Node("DO", "Doc Only", "section", "docs/notes.md"),
                "CO": Node("CO", "Code Only", "function", "src/code_only.py"),
                "N": Node("N", "Loose Note", "policy", "policies.json"),
            },
        )
        coverage = summarize_doc_code_coverage(graph)
        self.assertEqual(coverage.paired_keys, 1)
        self.assertEqual(coverage.doc_only_keys, 1)
        self.assertEqual(coverage.code_only_keys, 1)
        self.assertGreaterEqual(coverage.unlabeled_keys, 1)

    def test_doc_code_component_pairing_detects_real_graph_links(self) -> None:
        graph = Graph(
            nodes={
                "D": Node("D", "API Overview", "section", "docs/api.md"),
                "M": Node("M", "Routing", "concept", "docs/api.md"),
                "C": Node("C", "render_packet", "function", "src/render.py"),
                "DO": Node("DO", "Setup Notes", "section", "docs/setup.md"),
                "CO": Node("CO", "parse_query", "function", "src/query.py"),
            },
            edges=[
                Edge("D", "M", "discusses"),
                Edge("M", "C", "explains"),
            ],
        )
        coverage = summarize_doc_code_components(graph)
        self.assertEqual(coverage.paired_components, 1)
        self.assertEqual(coverage.doc_only_components, 1)
        self.assertEqual(coverage.code_only_components, 1)
        self.assertTrue(any("D" in example.doc_nodes for example in coverage.paired_examples))

    def test_doc_code_alignment_fixture_cases(self) -> None:
        fixture = Path(__file__).with_name("fixtures") / "doc_code_alignment_cases.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        for case in data["cases"]:
            nodes = {nid: Node(nid, label, kind, path) for nid, label, kind, path in case["nodes"]}
            edges = [Edge(source, target, etype) for source, target, etype in case["edges"]]
            graph = Graph(nodes=nodes, edges=edges)

            semantic = summarize_doc_code_coverage(graph)
            components = summarize_doc_code_components(graph)
            expect = case["expect"]

            self.assertEqual(semantic.paired_keys, expect["semantic"]["paired_keys"], case["name"])
            self.assertEqual(semantic.doc_only_keys, expect["semantic"]["doc_only_keys"], case["name"])
            self.assertEqual(semantic.code_only_keys, expect["semantic"]["code_only_keys"], case["name"])
            self.assertEqual(components.paired_components, expect["components"]["paired_components"], case["name"])
            self.assertEqual(components.doc_only_components, expect["components"]["doc_only_components"], case["name"])
            self.assertEqual(
                components.code_only_components, expect["components"]["code_only_components"], case["name"]
            )

    def test_load_eval_tasks_accepts_repo_manifest_shapes(self) -> None:
        from graphgraph.eval import load_eval_tasks

        with tempfile.TemporaryDirectory() as tmp:
            flat = Path(tmp) / "flat.json"
            flat.write_text(
                json.dumps(
                    [
                        {
                            "question": "What reaches auth?",
                            "expected_nodes": ["AuthService"],
                            "expected_edges": [["A", "B"], ["B", "C", "calls"]],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            nested = Path(tmp) / "nested.json"
            nested.write_text(
                json.dumps(
                    {
                        "projects": {
                            "demo": [
                                {
                                    "query": "auth blast radius",
                                    "query_class": "blast_radius",
                                    "expected_nodes": ["AuthService"],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            flat_tasks = load_eval_tasks(flat)
            nested_tasks = load_eval_tasks(nested)
            self.assertEqual(flat_tasks[0].query, "What reaches auth?")
            self.assertEqual(flat_tasks[0].expected_edges, (("A", "B"), ("B", "C", "calls")))
            self.assertEqual(nested_tasks[0].query, "auth blast radius")

    def test_search_short_terms_do_not_match_inside_unrelated_words(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "ContextService", "function", "src/context.py"),
                "B": Node("B", "Text", "file", "src/text.py"),
            }
        )
        matches = search_nodes(graph, "text", limit=2)
        self.assertEqual(matches[0].node.id, "B")

    def test_search_index_cache_reuses_and_invalidates_on_node_shape(self) -> None:
        graph = Graph(nodes={"A": Node("A", "AlphaSearch", "function", "src/a.py")})
        self.assertEqual(search_nodes(graph, "alpha search", limit=1)[0].node.id, "A")
        cache = graph._search_index_cache
        self.assertIsNotNone(cache)
        token_cache = graph._search_token_cache
        self.assertIsNotNone(token_cache)
        self.assertEqual(search_nodes(graph, "alpha search", limit=1)[0].node.id, "A")
        self.assertIs(graph._search_index_cache, cache)
        self.assertIs(graph._search_token_cache, token_cache)

        graph.nodes["B"] = Node("B", "BetaSearch", "function", "src/b.py")
        self.assertEqual(search_nodes(graph, "beta search", limit=1)[0].node.id, "B")
        self.assertIsNot(graph._search_index_cache, cache)
        self.assertIsNot(graph._search_token_cache, token_cache)

    def test_retrieval_anchors_code_identifier_queries(self) -> None:
        graph = Graph(
            nodes={
                "S": Node("S", "What it is", "section", "docs/what.md"),
                "F": Node("F", "compile_rules_slice", "function", "crates/locus-engine/src/rules/compiler.rs"),
                "C": Node("C", "compile_all", "function", "crates/locus-engine/src/rules/compiler.rs"),
            },
            edges=[Edge("C", "F", "calls", provenance="tree_sitter")],
        )
        self.assertEqual(
            tokenize("what calls compile_rules_slice"), ("calls", "compile_rules_slice", "compile", "rules", "slice")
        )
        self.assertEqual(
            tokenize("GameSession FastAceEngine cleanup_API"),
            (
                "gamesession",
                "game",
                "session",
                "fastaceengine",
                "fast",
                "ace",
                "engine",
                "cleanup_api",
                "cleanup",
                "api",
            ),
        )
        matches = search_nodes(graph, "what calls compile_rules_slice", limit=3)
        self.assertEqual(matches[0].node.id, "F")
        result = retrieve_context(graph, "what calls compile_rules_slice", "reverse_lookup", hops=1, max_nodes=5)
        self.assertIn("C", result.nodes)

    def test_render_query_context_show_anchors_includes_line_number(self) -> None:
        # The text-mode ANCHORS listing (used by `graphgraph query
        # --show-anchors`) previously showed only the file path, never the
        # line -- an agent had no way to jump straight to the match without
        # a follow-up snippets call. Same gap as MCP search_nodes/
        # query_context's JSON anchors; fixed via the shared Node.line
        # property.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def unrelated():\n    pass\n\n\ndef find_this_function():\n    return 1\n",
                encoding="utf-8",
            )
            from graphgraph.scanner import scan_directory

            graph_path = root / "graph.gg"
            save_graph(scan_directory(root, depth="symbols", frontend="regex"), graph_path)

            packet = render_query_context(
                query="find_this_function",
                query_class="direct_lookup",
                graph_path=graph_path,
                show_anchors=True,
            )
            self.assertIn("app.py:5", packet)

    def test_render_query_context_honors_hops_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            packet = render_query_context(
                query="auth service",
                query_class="blast_radius",
                graph_path=graph_path,
                hops=0,
            )
            self.assertIn("AuthService", packet)
            self.assertNotIn("TokenStore", packet)
            self.assertNotIn("reads", packet)

    def test_render_source_snippets_uses_node_line_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def helper():\n    return 1\n\ndef login():\n    token = helper()\n    return token\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = Graph(
                nodes={
                    "F": Node("F", "login", "function", "src/auth.py", summary="L4"),
                }
            )
            save_graph(graph, graph_path)

            out = render_source_snippets(starts=["F"], graph_path=graph_path, context_lines=1, max_lines=5)
            self.assertIn("## login (F)", out)
            self.assertIn("src/auth.py:3", out)
            self.assertIn("4 | def login():", out)
            self.assertIn("5 |     token = helper()", out)
            self.assertNotIn("1 | def helper", out)

    def test_render_source_snippets_prefers_real_code_over_doc_concept_with_same_label(self) -> None:
        # Found via live dogfooding: a label commonly matches both a real
        # code symbol AND a doc-derived "concept" node with the identical
        # label (e.g. the function name also gets mentioned in commit
        # messages/docs, producing a concept node). resolve_start_nodes
        # correctly resolves both (ambiguous labels resolve to every
        # matching active node, by design), but the old rendering printed a
        # confusing "No readable source path for node." block for the
        # concept match right alongside the real, useful source excerpt --
        # noise with no explanation. Now the real source wins outright when
        # it exists.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir(parents=True)
            source.write_text("def login():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = Graph(
                nodes={
                    "F": Node("F", "login", "function", "src/auth.py", summary="L1"),
                    "C": Node("C", "login", "concept", ""),
                }
            )
            save_graph(graph, graph_path)

            out = render_source_snippets(starts=["login"], graph_path=graph_path, context_lines=1, max_lines=5)
            self.assertIn("## login (F)", out)
            self.assertIn("src/auth.py:1", out)
            self.assertNotIn("No readable source path", out)
            self.assertNotIn("## login (C)", out)

    def test_render_source_snippets_resolves_package_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "examples" / "multi-router"
            pkg.mkdir(parents=True)
            child = pkg / "index.js"
            child.write_text("function bootstrap() {\n  return true;\n}\n", encoding="utf-8")

            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = Graph(
                nodes={
                    "P": Node("P", "multi-router", "package", "examples/multi-router"),
                    "F": Node("F", "bootstrap", "function", "examples/multi-router/index.js", summary="L1"),
                }
            )
            save_graph(graph, graph_path)

            out = render_source_snippets(starts=["P"], graph_path=graph_path, context_lines=0, max_lines=4)
            self.assertIn("## multi-router (P)", out)
            self.assertIn("examples/multi-router/index.js:1", out)
            self.assertIn("1 | function bootstrap()", out)

    def test_retrieve_context_filters_low_confidence_for_path_queries(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "Alpha"),
                "B": Node("B", "Beta"),
                "C": Node("C", "Gamma"),
            },
            edges=[
                Edge("A", "B", "calls", 1.0, confidence=1.0, provenance="regex_ast"),
                Edge("A", "C", "references", 1.0, confidence=0.1, provenance="ambiguous"),
            ],
        )
        result = retrieve_context(graph, "alpha", "multi_hop_path", hops=1)
        self.assertIn("B", result.nodes)
        self.assertTrue(all(edge.target != "C" for edge in result.edges))

    def test_retrieve_context_tightens_weak_edge_budget_for_noisy_subgraphs(self) -> None:
        graph = Graph(
            nodes={"A": Node("A", "Alpha")} | {f"N{i}": Node(f"N{i}", f"Loose {i}") for i in range(20)},
            edges=[Edge("A", f"N{i}", "references") for i in range(20)],
        )
        result = retrieve_context(graph, "alpha", "direct_lookup", hops=1, max_nodes=80)
        self.assertLessEqual(len([edge for edge in result.edges if edge.type == "references"]), 4)

    def test_retrieve_context_respects_scope(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "Alpha Worker", path="backend/a.py"),
                "B": Node("B", "Beta", path="backend/b.py"),
                "C": Node("C", "Alpha", path="frontend/c.ts"),
            },
            edges=[Edge("A", "B", "calls"), Edge("C", "A", "calls")],
        )
        result = retrieve_context(graph, "alpha", "blast_radius", hops=1, scopes=("backend",))
        self.assertEqual(result.starts, ("A",))
        self.assertIn("A", result.nodes)
        self.assertIn("B", result.nodes)
        self.assertNotIn("C", result.nodes)

    def test_retrieve_context_surfaces_policy_nodes(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "AuthService", path="server/auth.py"),
                "P": Node("P", "SecurityPolicy", kind="policy", scope="server/**"),
            },
            edges=[],
        )
        result = retrieve_context(graph, "auth", "direct_lookup", hops=1, max_nodes=5)
        self.assertIn("P", result.nodes)
        self.assertTrue(any(edge.type == "constrained_by" for edge in result.edges))

    def test_retrieve_context_surfaces_decision_traces(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "AuthService", path="server/auth.py"),
                "D": Node("D", "Decision", kind="decision_trace", summary="Used auth context"),
            },
            edges=[Edge("D", "A", "used_input", provenance="decision_trace")],
        )
        result = retrieve_context(graph, "auth", "direct_lookup", hops=1, max_nodes=5)
        self.assertIn("D", result.nodes)
        self.assertTrue(any(edge.type == "used_input" for edge in result.edges))

    def test_retrieve_context_sanitizes_query_noise(self) -> None:
        from graphgraph.retrieval.context import sanitize_query

        raw_query = """
[Fri 2026-07-06 14:00 UTC] Sender (untrusted metadata): ```python
def dummy(): pass
```
Find the AuthService implementation.
"""
        clean = sanitize_query(raw_query)
        self.assertEqual(clean, "Find the AuthService implementation.")

    def test_final_packet_applies_retrieval_policy(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "AuthService", path="server/auth.py"),
                "B": Node("B", "TokenStore", path="server/tokens.py"),
                "C": Node("C", "LooseMention", path="notes.md"),
                "P": Node("P", "SecurityPolicy", kind="policy", scope="server/**"),
            },
            edges=[
                Edge("A", "B", "calls", confidence=1.0, provenance="regex_ast"),
                Edge("A", "C", "references", confidence=0.1, provenance="ambiguous"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(graph, graph_path)
            packet = render_final_packet(
                starts=["A"],
                query_class="multi_hop_path",
                query_text="auth",
                graph_path=graph_path,
                cache_namespace="test_final_policy",
            )
        self.assertIn("calls", packet)
        self.assertIn("constrained_by", packet)
        self.assertNotIn("references", packet)

    def test_resolve_start_nodes_accepts_id_path_basename_and_label(self) -> None:
        graph = sample_graph()
        self.assertEqual(resolve_start_nodes(graph, ["N1"]), ["N1"])
        self.assertEqual(resolve_start_nodes(graph, ["server/auth.py"]), ["N1"])
        self.assertEqual(resolve_start_nodes(graph, ["auth.py"]), ["N1"])
        self.assertEqual(resolve_start_nodes(graph, ["AuthService"]), ["N1"])
        callable_graph = Graph(nodes={"F": Node("F", "validate_packet()", "function")})
        self.assertEqual(resolve_start_nodes(callable_graph, ["validate_packet"]), ["F"])

    def test_render_final_packet_resolves_human_facing_starts(self) -> None:
        graph = sample_graph()
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(graph, graph_path)
            packet = render_final_packet(
                starts=["AuthService"],
                query_class="direct_lookup",
                graph_path=graph_path,
                cache_namespace="test_label_start",
            )
        self.assertIn("AuthService", packet)
        self.assertIn("TokenStore", packet)
        self.assertIn("[e]", packet)

    def test_render_final_packet_uses_shape_budget_without_explicit_cap(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "A", "function"),
                **{f"B{i}": Node(f"B{i}", f"B{i}", "function") for i in range(100)},
            },
            edges=[Edge("A", f"B{i}", "calls") for i in range(100)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(graph, graph_path)
            packet = render_final_packet(
                starts=["A"],
                query_class="multi_hop_path",
                graph_path=graph_path,
                cache_namespace="test_shape_final",
            )
        lines = packet.splitlines()
        node_start = lines.index("[n]") + 1
        edge_start = lines.index("[e]")
        node_rows = [line for line in lines[node_start:edge_start] if not line.startswith("# ")]
        self.assertEqual(len(node_rows), 70)
