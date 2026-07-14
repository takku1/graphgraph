from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def test_reverse_lookup_preserves_multi_identifier_contract_intent(self) -> None:
        graph = Graph(
            nodes={
                "TRAIT": Node("TRAIT", "DiscoveryPipeline", "trait", "core/pipeline.rs"),
                "TYPE": Node("TYPE", "LocusEngine", "struct", "pipeline/lib.rs"),
                "DECL_SEARCH": Node("DECL_SEARCH", "search_candidates", "method", "core/pipeline.rs"),
                "DECL_VALIDATE": Node("DECL_VALIDATE", "validate_candidates", "method", "core/pipeline.rs"),
                "IMPL_SEARCH": Node("IMPL_SEARCH", "search_candidates", "function", "pipeline/lib.rs"),
                "IMPL_VALIDATE": Node("IMPL_VALIDATE", "validate_candidates", "function", "pipeline/lib.rs"),
                "TEST": Node("TEST", "pipeline_behavior", "function", "pipeline/tests/pipeline.rs"),
            },
            edges=[
                Edge("TYPE", "TRAIT", "implements", confidence=0.95, provenance="tree_sitter"),
                Edge("TRAIT", "DECL_SEARCH", "contains", confidence=0.95, provenance="tree_sitter"),
                Edge("TRAIT", "DECL_VALIDATE", "contains", confidence=0.95, provenance="tree_sitter"),
                Edge("TEST", "TYPE", "imports_from", confidence=0.95, provenance="tree_sitter"),
                Edge("TEST", "IMPL_SEARCH", "calls", confidence=0.95, provenance="tree_sitter"),
                Edge("TEST", "IMPL_VALIDATE", "calls", confidence=0.95, provenance="tree_sitter"),
            ],
        )
        result = retrieve_context(
            graph,
            "Which type implements DiscoveryPipeline, and where are search_candidates and validate_candidates tested?",
            "reverse_lookup",
            hops=1,
        )

        self.assertIn("TRAIT", result.starts)
        self.assertIn("DECL_SEARCH", result.starts)
        self.assertIn("IMPL_SEARCH", result.starts)
        self.assertIn("TYPE", result.starts)
        self.assertIn("TYPE", result.nodes)
        self.assertIn("TEST", result.nodes)
        self.assertTrue(any(edge.type == "implements" for edge in result.edges))
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

    def test_recent_changes_query_class_surfaces_fixes_edges_deprioritized_elsewhere(self) -> None:
        # Concrete, scoped instance of the "time-scoped query" idea in
        # docs/planned-work.md: extract_commit_history already puts commit
        # nodes + fixes edges into the graph when history=True, but before
        # this test/feature, no traversal policy in graph/traversal.py
        # listed "history" in preferred_families or "fixes" in
        # preferred_relations -- confirmed by reading every POLICIES entry.
        # Those edges only ever survived as unprioritized weak-edge-limit
        # leftovers under every existing query class.
        import subprocess

        from graphgraph.graph.traversal import traversal_policy
        from graphgraph.scanner import scan_directory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")
            (root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "feat: initial commit")
            (root / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "fix: correct add() returning subtraction result")

            graph = scan_directory(root, depth="files", history=True)

            result = retrieve_context(graph, "app", "recent_changes", hops=1)
            commit_nodes_in_result = [n for n in result.nodes if graph.nodes[n].kind == "commit"]
            self.assertTrue(commit_nodes_in_result, "recent_changes should surface the fix commit touching app.py")
            fixes_edges_in_result = [e for e in result.edges if e.type == "fixes"]
            self.assertTrue(fixes_edges_in_result, "recent_changes should surface the fixes edge itself")

            # Contrast: confirm blast_radius genuinely does not prioritize
            # this relation/family -- the gap this query class closes.
            blast_policy = traversal_policy("blast_radius")
            self.assertNotIn("fixes", blast_policy.preferred_relations)
            self.assertNotIn("history", blast_policy.preferred_families)

    def test_recent_changes_ignores_ephemeral_session_layer_git_dirty_injection(self) -> None:
        # Found live-testing recent_changes against this project's own repo
        # (which had 15 uncommitted files at the time): retrieve_context
        # unconditionally appends every currently-dirty file as an extra
        # start for every query class ("Ephemeral Session Layer"), which is
        # reasonable for exploratory queries but actively defeats
        # recent_changes -- a query class specifically about one deliberate
        # anchor's committed history. On a repo under active development
        # (exactly when "what recently changed here" is most useful), a
        # dozen unrelated dirty files drowned out the one real anchor and
        # its fixes/commit evidence before the node budget was ever reached.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
            graph = Graph(nodes={"TARGET": Node("TARGET", "widget", "function", "widget.py")})
            with patch(
                "graphgraph.retrieval.git_utils.get_git_modified_files",
                return_value={"unrelated.py": 3},
            ):
                result = retrieve_context(graph, "widget", "recent_changes", hops=1)
                self.assertNotIn("unrelated_py", result.starts)

                # Exact structural queries must not gain unrelated traversal
                # starts merely because the worktree is dirty.
                graph2 = Graph(
                    nodes={
                        "TARGET": Node("TARGET", "widget", "function", "widget.py"),
                        "unrelated_py": Node("unrelated_py", "unrelated.py", "python", "unrelated.py"),
                    }
                )
                result2 = retrieve_context(graph2, "widget", "blast_radius", hops=1)
                self.assertNotIn("unrelated_py", result2.starts)

                # The session layer remains available for exploratory status
                # queries where current edits are useful ambient context.
                result3 = retrieve_context(graph2, "widget", "subsystem_summary", hops=1)
                self.assertIn("unrelated_py", result3.starts)

    def test_search_prefers_source_over_tests_unless_query_mentions_tests(self) -> None:
        graph = Graph(
            nodes={
                "SRC": Node("SRC", "scan_directory", "function", "src/graphgraph/scanner/core.py"),
                "TEST": Node("TEST", "test_scan_directory", "function", "tests/test_graphgraph_core.py"),
            }
        )
        self.assertEqual(search_nodes(graph, "scan directory", limit=2)[0].node.id, "SRC")
        self.assertEqual(search_nodes(graph, "test scan directory", limit=2)[0].node.id, "TEST")

    def test_broad_implementation_query_keeps_tests_as_support_not_primary_intent(self) -> None:
        graph = Graph(
            nodes={
                "SRC": Node("SRC", "scanner_implementation", "function", "src/graphgraph/scanner/core.py"),
                "TEST": Node(
                    "TEST",
                    "test_scanner_implementation_blast_radius",
                    "function",
                    "tests/test_scanner.py",
                ),
            }
        )
        matches = search_nodes(graph, "scanner implementation callers tests blast radius", limit=2)
        self.assertEqual(matches[0].node.id, "SRC")

    def test_search_prefers_handwritten_source_over_generated_stub(self) -> None:
        # Adversarial: identical text, and the generated protobuf stub is more
        # connected (higher degree/PPR). Only a generated-source signal can
        # keep the hand-written source of truth on top -- and a query that
        # explicitly asks for the generated artifact must lift the penalty.
        nodes = {
            "SRC": Node("SRC", "User", "class", "src/models/user.py", summary="user record"),
            "GEN": Node("GEN", "User", "class", "build/generated/user_pb2.py", summary="user record"),
        }
        edges = []
        for i in range(6):
            nodes[f"C{i}"] = Node(f"C{i}", f"caller_{i}", "function", f"src/c{i}.py")
            edges.append(Edge(f"C{i}", "GEN", "imports_from"))
        graph = Graph(nodes=nodes, edges=edges)
        self.assertEqual(search_nodes(graph, "User", limit=3, personalize=True)[0].node.id, "SRC")
        self.assertEqual(
            search_nodes(graph, "User protobuf", limit=3, personalize=True)[0].node.id, "GEN"
        )

    def test_search_prefers_source_over_benchmark_unless_query_mentions_benchmark(self) -> None:
        graph = Graph(
            nodes={
                "SRC": Node("SRC", "rank_packet", "function", "src/graphgraph/retrieval/search.py"),
                "BENCH": Node("BENCH", "rank_packet", "function", "benchmarks/context_graph/ranking.py"),
            }
        )
        self.assertEqual(search_nodes(graph, "rank packet", limit=2)[0].node.id, "SRC")
        self.assertEqual(search_nodes(graph, "benchmark rank packet", limit=2)[0].node.id, "BENCH")

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

    def test_identifier_quality_bonus_rewards_descriptive_multi_segment_names(self) -> None:
        # From prior-art-research.md: Aider's repo-map personalization gives
        # a well-formed identifier a 10x weight over a generic one when
        # ranking. Direct unit coverage of the scoring function itself.
        from graphgraph.retrieval.search import identifier_quality_bonus

        self.assertEqual(identifier_quality_bonus("x"), 0.0)
        self.assertEqual(identifier_quality_bonus("tmp"), 0.0)
        self.assertEqual(identifier_quality_bonus("data"), 0.0)
        self.assertEqual(identifier_quality_bonus(""), 0.0)
        self.assertEqual(identifier_quality_bonus("helper"), 0.0)  # single segment, not generic-listed but still 1 segment
        self.assertGreater(identifier_quality_bonus("resolve_modified_node_ids"), 0.0)
        self.assertGreater(identifier_quality_bonus("resolveModifiedNodeIds"), 0.0)
        # More segments should score at least as high, and the bonus must
        # stay capped well below an exact-match-tier bonus (36.0).
        four_seg = identifier_quality_bonus("resolve_modified_node")
        eight_seg = identifier_quality_bonus("resolve_modified_node_ids_from_git_diff_output")
        self.assertGreaterEqual(eight_seg, four_seg)
        self.assertLessEqual(eight_seg, 3.0)

    def test_search_nodes_prefers_well_named_identifier_when_otherwise_tied(self) -> None:
        # Integration-level: two functions match a generic query term
        # equally (both are "function" kind with the same lexical match
        # strength), but one has a descriptive multi-segment name and the
        # other is a bare placeholder-style name. The well-named one should
        # rank first.
        graph = Graph(
            nodes={
                "GOOD": Node("GOOD", "resolve_modified_node_ids", "function", "a.py"),
                "BAD": Node("BAD", "x", "function", "b.py"),
            }
        )
        matches = search_nodes(graph, "resolve modified node ids", limit=2)
        self.assertEqual(matches[0].node.id, "GOOD")

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

    def test_blast_radius_prioritizes_incoming_impact_over_outgoing_context(self) -> None:
        from graphgraph.planning.types import ContextPlan
        from graphgraph.retrieval.context import expand_context

        nodes = {"T": Node("T", "Target")}
        nodes.update({f"I{i}": Node(f"I{i}", f"Incoming {i}") for i in range(30)})
        nodes.update({f"O{i}": Node(f"O{i}", f"Outgoing {i}") for i in range(30)})
        nodes["CFG"] = Node("CFG", "Config")
        edges = [Edge(f"I{i}", "T", "calls") for i in range(30)]
        edges += [Edge("T", f"O{i}", "calls") for i in range(30)]
        edges.append(Edge("CFG", "T", "configures"))
        graph = Graph(nodes=nodes, edges=edges)
        plan = ContextPlan(
            query_class="blast_radius",
            hops=2,
            direction="both",
            packet="gg_max",
            node_budget=20,
            anchor_limit=1,
            weak_edge_limit=20,
            min_confidence=0.0,
            reason="test",
        )

        selected, _edges = expand_context(graph, ("T",), plan)
        incoming = sum(node_id.startswith("I") for node_id in selected)
        outgoing = sum(node_id.startswith("O") for node_id in selected)
        self.assertGreater(incoming, outgoing)
        self.assertIn("CFG", selected)
        self.assertLessEqual(len(selected), 20)

    def test_subsystem_summary_expands_high_degree_anchor(self) -> None:
        from graphgraph.planning import plan_context
        from graphgraph.retrieval.context import expand_context

        leaves = {f"N{i}": Node(f"N{i}", f"Node {i}") for i in range(200)}
        graph = Graph(
            nodes={"HUB": Node("HUB", "Subsystem", "class"), **leaves},
            edges=[Edge("HUB", node_id, "contains") for node_id in leaves],
        )
        plan = plan_context("subsystem_summary", max_nodes=40)

        nodes, edges = expand_context(graph, ("HUB",), plan)

        self.assertEqual(len(nodes), plan.node_budget)
        self.assertTrue(edges)

    def test_multi_hop_path_reserves_connection_across_high_fanout(self) -> None:
        from graphgraph.planning import plan_context
        from graphgraph.retrieval.context import expand_context

        leaves = {f"N{i}": Node(f"N{i}", f"Node {i}") for i in range(100)}
        graph = Graph(
            nodes={
                "START": Node("START", "Start"),
                "MID": Node("MID", "Middle"),
                "TARGET": Node("TARGET", "Target"),
                **leaves,
            },
            edges=[
                *(Edge("START", node_id, "contains") for node_id in leaves),
                Edge("START", "MID", "calls"),
                Edge("MID", "TARGET", "calls"),
            ],
        )
        plan = plan_context("multi_hop_path", max_nodes=20)

        nodes, edges = expand_context(graph, ("START", "TARGET"), plan)
        edge_keys = {(edge.source, edge.target, edge.type) for edge in edges}

        self.assertIn("MID", nodes)
        self.assertIn(("START", "MID", "calls"), edge_keys)
        self.assertIn(("MID", "TARGET", "calls"), edge_keys)
        self.assertLessEqual(len(nodes), 20)

    def test_multi_hop_path_beam_reserves_strongest_equal_length_path(self) -> None:
        # Two equally short START->TARGET routes: a weak one (low-confidence
        # references) and a strong one (high-confidence calls). Beam search must
        # reserve the strong route, not whichever the adjacency yields first.
        from graphgraph.planning import plan_context
        from graphgraph.retrieval.context import expand_context

        graph = Graph(
            nodes={k: Node(k, k, "function", f"{k}.py") for k in ("START", "W", "S", "TARGET")},
            edges=[
                Edge("START", "W", "references", confidence=0.3),
                Edge("W", "TARGET", "references", confidence=0.3),
                Edge("START", "S", "calls", confidence=1.0),
                Edge("S", "TARGET", "calls", confidence=1.0),
            ],
        )
        plan = plan_context("multi_hop_path", max_nodes=20)
        nodes, edges = expand_context(graph, ("START", "TARGET"), plan)
        edge_keys = {(edge.source, edge.target, edge.type) for edge in edges}
        self.assertIn("S", nodes)
        self.assertIn(("START", "S", "calls"), edge_keys)
        self.assertIn(("S", "TARGET", "calls"), edge_keys)

    def test_subsystem_summary_reserves_relation_family_evidence(self) -> None:
        from graphgraph.planning import plan_context
        from graphgraph.retrieval.context import expand_context

        leaves = {f"N{i}": Node(f"N{i}", f"Node {i}") for i in range(100)}
        graph = Graph(
            nodes={"HUB": Node("HUB", "Subsystem"), "DOC": Node("DOC", "Docs"), **leaves},
            edges=[
                *(Edge("HUB", node_id, "contains") for node_id in leaves),
                Edge("DOC", "HUB", "explains"),
            ],
        )
        plan = plan_context("subsystem_summary", max_nodes=20)

        _nodes, edges = expand_context(graph, ("HUB",), plan)

        self.assertIn("contains", {edge.type for edge in edges})
        self.assertIn("explains", {edge.type for edge in edges})

    def test_doc_summary_file_anchor_retrieves_section_contents(self) -> None:
        from graphgraph.planning import plan_context
        from graphgraph.retrieval.context import expand_context

        graph = Graph(
            nodes={
                "DOC": Node("DOC", "Coverage Matrix", "markdown", "docs/coverage-matrix.md"),
                "ROADMAP": Node(
                    "ROADMAP",
                    "Roadmap",
                    "section",
                    "docs/coverage-matrix.md",
                    summary="Prioritized parser and retrieval work.",
                ),
                "STATUS": Node(
                    "STATUS",
                    "Current Coverage",
                    "section",
                    "docs/coverage-matrix.md",
                    summary="Current language coverage by frontend.",
                ),
            },
            edges=[
                Edge("ROADMAP", "DOC", "section_of"),
                Edge("STATUS", "DOC", "section_of"),
            ],
        )
        plan = plan_context("doc_summary", "coverage matrix roadmap")

        nodes, edges = expand_context(graph, ("DOC",), plan)

        self.assertEqual(nodes, {"DOC", "ROADMAP", "STATUS"})
        self.assertEqual({edge.type for edge in edges}, {"section_of"})

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

    def test_render_query_context_cache_hit_skips_retrieval(self) -> None:
        from graphgraph.runtime.cache import TopologicalKVCache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            save_graph(sample_graph(), graph_path)
            cache = TopologicalKVCache(root / "cache.json")
            with patch("graphgraph.services.context.TopologicalKVCache", return_value=cache):
                first = render_query_context(
                    query="auth service",
                    query_class="direct_lookup",
                    graph_path=graph_path,
                    cache_namespace="early_query_cache",
                )
                with patch(
                    "graphgraph.services.context.retrieve_context",
                    side_effect=AssertionError("retrieval ran on a cache hit"),
                ), patch(
                    "graphgraph.services.context._load_graph_cached",
                    side_effect=AssertionError("graph loaded on a cache hit"),
                ):
                    second = render_query_context(
                        query="auth service",
                        query_class="direct_lookup",
                        graph_path=graph_path,
                        cache_namespace="early_query_cache",
                    )
            self.assertEqual(first, second)

    def test_render_final_packet_cache_hit_skips_expansion(self) -> None:
        from graphgraph.runtime.cache import TopologicalKVCache

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            save_graph(sample_graph(), graph_path)
            cache = TopologicalKVCache(root / "cache.json")
            with patch("graphgraph.services.context.TopologicalKVCache", return_value=cache):
                first = render_final_packet(
                    starts=["N1"],
                    query_class="direct_lookup",
                    graph_path=graph_path,
                    cache_namespace="early_final_cache",
                )
                with patch(
                    "graphgraph.services.context.expand_context",
                    side_effect=AssertionError("expansion ran on a cache hit"),
                ), patch(
                    "graphgraph.services.context._load_graph_cached",
                    side_effect=AssertionError("graph loaded on a cache hit"),
                ):
                    second = render_final_packet(
                        starts=["N1"],
                        query_class="direct_lookup",
                        graph_path=graph_path,
                        cache_namespace="early_final_cache",
                    )
            self.assertEqual(first, second)

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

    def test_explicit_identifier_blast_radius_uses_one_anchor(self) -> None:
        graph = Graph(
            nodes={
                "SRC": Node("SRC", "render_packet", "function", "src/packets.py"),
                "BENCH": Node("BENCH", "render_packet", "function", "benchmarks/protocol.py"),
                "CALLER": Node("CALLER", "build_packet", "function", "src/context.py"),
            },
            edges=[Edge("CALLER", "SRC", "calls")],
        )

        result = retrieve_context(
            graph,
            "blast radius changing render_packet",
            "blast_radius",
            hops=2,
        )

        self.assertEqual(result.starts, ("SRC",))
        self.assertIn("CALLER", result.nodes)

    def test_broad_blast_radius_caps_ambiguous_two_hop_expansion(self) -> None:
        nodes = {"SRC": Node("SRC", "scanner.py", "python", "src/graphgraph/scanner/core.py")}
        edges = []
        for i in range(100):
            node_id = f"N{i}"
            nodes[node_id] = Node(node_id, f"scanner_helper_{i}", "function", f"src/helpers/h{i}.py")
            edges.append(Edge(node_id, "SRC", "calls"))
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(
            graph,
            "continue implementation scanner callers tests blast radius",
            "blast_radius",
            hops=2,
        )

        self.assertLessEqual(len(result.nodes), 48)

    def test_broad_subsystem_summary_caps_ambiguous_expansion(self) -> None:
        nodes = {"SRC": Node("SRC", "scanner.py", "python", "src/graphgraph/scanner/core.py")}
        edges = []
        for i in range(100):
            node_id = f"N{i}"
            nodes[node_id] = Node(node_id, f"scanner_helper_{i}", "function", f"src/helpers/h{i}.py")
            edges.append(Edge("SRC", node_id, "contains"))
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(graph, "continue implementation scanner architecture", "subsystem_summary", hops=1)

        self.assertLessEqual(len(result.nodes), 48)

    def test_exact_symbol_blast_radius_retains_recall_budget(self) -> None:
        nodes = {"SRC": Node("SRC", "render_packet", "function", "src/packets.py")}
        edges = []
        for i in range(70):
            node_id = f"C{i}"
            nodes[node_id] = Node(node_id, f"caller_{i}", "function", f"src/c{i}.py")
            edges.append(Edge(node_id, "SRC", "calls"))
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(graph, "blast radius changing render_packet", "blast_radius", hops=2)

        self.assertGreater(len(result.nodes), 48)

    def test_exact_symbol_subsystem_summary_retains_recall_budget(self) -> None:
        nodes = {"SRC": Node("SRC", "render_packet", "function", "src/packets.py")}
        edges = []
        for i in range(70):
            node_id = f"C{i}"
            nodes[node_id] = Node(node_id, f"helper_{i}", "function", f"src/c{i}.py")
            edges.append(Edge("SRC", node_id, "calls"))
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(graph, "render_packet", "subsystem_summary", hops=1)

        self.assertGreater(len(result.nodes), 48)

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
        # Budget tracks the path-aware gg_max token surface. Source provenance
        # raises per-node cost, so the same token target admits fewer nodes.
        self.assertEqual(len(node_rows), 58)

    def test_render_full_graph_includes_every_active_node_and_edge(self) -> None:
        # The explicit "give me everything, no query scoping" escape hatch
        # added after testing full-graph loading surfaced a real validator
        # bug (see test_gg_max_validation_survives_node_content_containing_
        # marker_substrings in test_packets.py). render_full_graph must
        # include every active node/edge with no budget/retrieval filtering
        # at all, and must exclude inactive (soft-deleted) ones.
        from graphgraph.packets.validation import validate_packet
        from graphgraph.services import render_full_graph

        graph = Graph(
            nodes={
                "A": Node("A", "Alpha", "function", active=True),
                "B": Node("B", "Beta", "function", active=True),
                "GONE": Node("GONE", "Gone", "function", active=False),
            },
            edges=[Edge("A", "B", "calls")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(graph, graph_path)
            packet = render_full_graph(graph_path, max_tokens=None)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.node_count, 2)
        self.assertNotIn("Gone", packet)

    def test_render_full_graph_refuses_over_token_guard(self) -> None:
        from graphgraph.services import FullGraphTooLargeError, render_full_graph

        graph = Graph(
            nodes={f"N{i}": Node(f"N{i}", f"node_number_{i}_with_a_longer_label", "function") for i in range(50)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(graph, graph_path)
            with self.assertRaises(FullGraphTooLargeError) as ctx:
                render_full_graph(graph_path, max_tokens=10)
            self.assertIn("10", str(ctx.exception))
            # max_tokens=None (or 0, via the CLI/MCP "disable" convention)
            # must render regardless of size.
            packet = render_full_graph(graph_path, max_tokens=None)
            self.assertIn("node_number_0_with_a_longer_label", packet)


class QueryConditionedSectionRelevanceTest(unittest.TestCase):
    """P0 #2: document section retrieval must rank sections by query relevance,
    not by graph shape, when a document has more sections than the budget."""

    def _doc_graph(self) -> Graph:
        # One markdown document with six distinctly-themed sections, each
        # attached to the doc by a section_of edge (section -> doc), mirroring
        # the real scanner layout. Bodies carry topic terms so BM25 has signal.
        nodes = {
            "doc": Node("doc", "guide.md", "markdown", "docs/guide.md"),
        }
        sections = {
            "sec_install": ("Installation", "install the package with pip and configure the virtualenv"),
            "sec_auth": ("Authentication", "configure oauth tokens and api keys for login credentials"),
            "sec_deploy": ("Deployment", "deploy to kubernetes with docker containers and helm charts"),
            "sec_metrics": ("Metrics", "prometheus scrapes latency and throughput gauges and counters"),
            "sec_backup": ("Backups", "snapshot the database to s3 and restore from archived dumps"),
            "sec_upgrade": ("Upgrades", "migrate the schema and roll forward version pins during upgrade"),
        }
        edges = []
        for sid, (label, body) in sections.items():
            nodes[sid] = Node(sid, label, "section", "docs/guide.md", facts=(body,))
            edges.append(Edge(sid, "doc", "section_of"))
        return Graph(nodes=nodes, edges=edges)

    def _retained_sections(self, graph: Graph, query: str, budget: int) -> set[str]:
        from dataclasses import replace

        from graphgraph.planning import plan_context
        from graphgraph.planning.budgets import plan_terms
        from graphgraph.retrieval.context import expand_context

        plan = replace(plan_context("doc_summary", query, max_nodes=budget), node_budget=budget)
        nodes, _ = expand_context(graph, ("doc",), plan, query_terms=plan_terms(query))
        return {n for n in nodes if n.startswith("sec_")}

    def test_query_selects_its_own_section_within_a_tight_budget(self) -> None:
        graph = self._doc_graph()
        # Budget holds the doc + 3 of 6 sections. Each query must surface the
        # section that answers it -- proving selection tracks the query, not
        # graph shape (all sections are one hop with identical edge weight).
        deploy = self._retained_sections(graph, "deploy kubernetes docker containers", budget=4)
        self.assertIn("sec_deploy", deploy)

        backup = self._retained_sections(graph, "restore database backup from s3 snapshot", budget=4)
        self.assertIn("sec_backup", backup)

        # Different queries yield different survivors: the feature is doing work.
        self.assertNotEqual(deploy, backup)

    def test_bm25_ranks_heading_and_body_matches_above_unrelated(self) -> None:
        from graphgraph.retrieval.relevance import bm25_scores

        graph = self._doc_graph()
        sections = [graph.nodes[n] for n in graph.nodes if n.startswith("sec_")]
        scores = bm25_scores(sections, ("deploy", "kubernetes", "docker"))
        top = max(scores, key=scores.__getitem__)
        self.assertEqual(top, "sec_deploy")
        # An unrelated section scores zero against these terms.
        self.assertEqual(scores["sec_install"], 0.0)

    def test_empty_query_is_a_no_op_multiplier(self) -> None:
        from graphgraph.retrieval.relevance import relevance_multipliers, section_priority_bias

        graph = self._doc_graph()
        sections = [graph.nodes[n] for n in graph.nodes if n.startswith("sec_")]
        self.assertEqual(relevance_multipliers(sections, ()), {})
        self.assertEqual(section_priority_bias(graph, ("doc",), ()), {})
