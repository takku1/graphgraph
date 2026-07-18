from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
    choose_packet,
    plan_context,
)
from graphgraph.planning import (
    path_matches,
    profile_graph_shape,
    recommend_context_window,
    recommend_node_budget,
    recommend_observed_context_window,
    route_query,
)
from graphgraph.retrieval import (
    default_anchor_limit,
    retrieval_node_budget,
    retrieve_context,
    search_nodes,
)
from graphgraph.retrieval.context import apply_shape_budget, prune_doc_concept_noise, shape_edge_budget
from graphgraph.retrieval.models import Match


class PlanningTest(unittest.TestCase):
    def test_query_router_maps_agent_intents_without_graph_io(self) -> None:
        cases = {
            "where is render_packet defined": "direct_lookup",
            "where are facet coverage and answerability reconciled": "direct_lookup",
            "what calls validate_packet and where is it tested": "reverse_lookup",
            "which tests cover run_formula_yield_benchmark and should run": "affected_tests",
            "Which exact direct and transitive tests are affected after adding planner deduplication?": "affected_tests",
            "Return minimal runnable Cargo test commands for the direct behavioral tests": "affected_tests",
            "trace request parsing through planning to packet rendering": "multi_hop_path",
            "how does run_formula_yield_benchmark depend on validate_candidates_detailed": "multi_hop_path",
            "what is the blast radius if Edge changes": "blast_radius",
            "how does retrieval work": "subsystem_summary",
            "how is the low-level graph IR designed and structured": "subsystem_summary",
            "README installation and usage guide": "doc_summary",
            "What is the ordered execution backlog and what happens next before new capability development?": "doc_summary",
            "is legacy_cache unused and does it have no callers": "negative_query",
            "what changed recently in scanner": "recent_changes",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                route = route_query(query)
                self.assertEqual(route.query_class, expected)
                self.assertTrue(route.reasons)

    def test_query_router_keeps_explicit_policy_and_ambiguous_queries_broad(self) -> None:
        explicit = route_query("what calls validate_packet", "direct_lookup")
        self.assertEqual(explicit.query_class, "direct_lookup")
        self.assertEqual(explicit.reasons, ("explicit query class",))

        ambiguous = route_query("auth service")
        self.assertEqual(ambiguous.query_class, "subsystem_summary")

    def test_query_router_prefers_reverse_intent_over_broad_work_language(self) -> None:
        route = route_query("how does packet validation work and what calls it")
        self.assertEqual(route.query_class, "reverse_lookup")
        self.assertGreater(route.margin, 0.0)

    def test_query_router_consumer_wording_stays_source_orientation(self) -> None:
        route = route_query(
            "Where is SourceCaseBaseline, what metrics does it enforce, and which test consumes it?"
        )

        self.assertNotEqual(route.query_class, "affected_tests")
        self.assertIn(route.query_class, {"direct_lookup", "reverse_lookup", "subsystem_summary"})

    def test_path_matches_leading_wildcard_requires_literal_segment(self) -> None:
        # Regression: path_matches computed the prefix as
        # pattern.split("**", 1)[0] and did path.startswith(prefix). That's
        # correct for a trailing wildcard ("src/**"), but for a
        # leading/middle wildcard ("**/tests/**") the prefix is "" and
        # every path starts with "", so a policy scoped to "**/tests/**"
        # silently matched every path in the repo instead of just paths
        # containing "tests/".
        self.assertFalse(path_matches("**/tests/**", "src/graphgraph/core.py"))
        self.assertTrue(path_matches("**/tests/**", "sub/tests/test_thing.py"))
        # Trailing-wildcard behavior must stay unchanged.
        self.assertTrue(path_matches("src/**", "src/graphgraph/core.py"))
        self.assertFalse(path_matches("src/**", "other/file.py"))
        self.assertTrue(path_matches("**", "anything/at/all.py"))

    def test_adaptive_anchor_limit_handles_symbol_plateaus(self) -> None:
        from graphgraph.retrieval.context import _adaptive_anchor_limit

        plan = plan_context("blast_radius", "parse")
        plateau = (
            Match(Node("A", "parse", "function", "a/parse.rs"), 23.74, ()),
            Match(Node("B", "parse", "function", "b/parse.rs"), 23.70, ()),
            Match(Node("C", "parse", "function", "c/parse.rs"), 23.69, ()),
            Match(Node("D", "parse", "function", "d/fowler.rs"), 19.24, ()),
            Match(Node("E", "parse", "function", "e/mod.rs"), 19.21, ()),
        )
        self.assertEqual(_adaptive_anchor_limit(plateau, plan, "parse"), 3)

        wide_plateau = (
            Match(Node("A", "search", "method", "a/mcts.py"), 24.09, ()),
            Match(Node("B", "search", "method", "b/alphabeta.py"), 23.998, ()),
            Match(Node("C", "search", "method", "c/engine.py"), 19.551, ()),
            Match(Node("D", "search", "function", "d/tbprobe.cpp"), 19.477, ()),
            Match(Node("E", "search", "header", "e/search.h"), 18.5, ()),
        )
        self.assertEqual(_adaptive_anchor_limit(wide_plateau, plan, "search"), 5)

        same_stem = (
            Match(Node("A", "translate", "function", "src/hir/translate.rs"), 30.50, ()),
            Match(Node("B", "t_err", "function", "src/hir/translate.rs"), 12.50, ()),
            Match(Node("C", "ascii_class", "function", "src/hir/translate.rs"), 12.44, ()),
            Match(Node("D", "translate.rs", "rust", "src/hir/translate.rs"), 11.73, ()),
            Match(Node("E", "hir_capture", "function", "src/hir/translate.rs"), 11.19, ()),
        )
        self.assertEqual(_adaptive_anchor_limit(same_stem, plan, "translate"), 4)

    def test_choose_packet_empirical_alignment(self) -> None:
        # Empirical data: structural packets with edges → gg is the token floor.
        self.assertEqual(choose_packet("direct_lookup").packet, "gg")
        self.assertEqual(choose_packet("direct_lookup").hops, 1)
        self.assertEqual(choose_packet("reverse_lookup").packet, "gg")
        self.assertEqual(choose_packet("reverse_lookup").hops, 1)
        # blast_radius / multi_hop → gg 2-hop
        self.assertEqual(choose_packet("blast_radius").hops, 2)
        self.assertEqual(choose_packet("blast_radius").packet, "gg")
        self.assertEqual(choose_packet("multi_hop_path").hops, 2)
        self.assertEqual(choose_packet("multi_hop_path").packet, "gg")
        # summary → gg unless it is explicitly documentation-oriented.
        self.assertEqual(choose_packet("subsystem_summary").packet, "gg")
        self.assertEqual(choose_packet("subsystem_summary", "README installation usage").packet, "doc_summary")
        self.assertEqual(choose_packet("doc_summary").packet, "doc_summary")
        # negative/absence probes use 1 hop -- enough to prove real
        # connectivity exists (see test_negative_query_surfaces_real_edges),
        # while staying far short of a full expansion.
        self.assertEqual(choose_packet("negative_query").hops, 1)
        self.assertEqual(choose_packet("negative_query").packet, "semantic_arrow")
        # unknown → conservative 2-hop gg_hybrid
        self.assertEqual(choose_packet("unknown_xyz").hops, 2)
        self.assertEqual(choose_packet("unknown_xyz").packet, "gg_hybrid")

    def test_context_plan_unifies_runtime_policy(self) -> None:
        direct = plan_context("direct_lookup", "what does AuthService call")
        self.assertEqual(direct.hops, 1)
        self.assertEqual(direct.direction, "out")
        self.assertEqual(direct.packet, "gg")
        self.assertEqual(direct.node_budget, 80)
        self.assertGreaterEqual(direct.anchor_limit, 1)
        self.assertIn("context_plan_v4", direct.planner_version)

        docs = plan_context("subsystem_summary", "README installation usage")
        self.assertEqual(docs.packet, "doc_summary")
        self.assertEqual(docs.node_budget, 12)

        override = plan_context("blast_radius", "auth service", max_nodes=40, hops=1, packet="sql")
        self.assertEqual(override.hops, 1)
        self.assertEqual(override.packet, "sql")
        self.assertEqual(override.node_budget, 40)

    def test_refine_packet_for_zero_edge_subgraph(self) -> None:
        from graphgraph.planning import (
            PacketChoice,
            compute_subgraph_stats,
            refine_packet_for_subgraph,
            refine_plan_for_subgraph,
        )

        refined = refine_packet_for_subgraph(PacketChoice(1, "gg", "test"), 0)
        self.assertEqual(refined.packet, "semantic_arrow")
        self.assertEqual(refined.hops, 1)
        unchanged = refine_packet_for_subgraph(PacketChoice(1, "gg", "test"), 1)
        self.assertEqual(unchanged.packet, "gg")

        graph = sample_graph()
        stats = compute_subgraph_stats(graph, {"N1"}, [])
        self.assertEqual(stats.nodes, 1)
        self.assertEqual(stats.edges, 0)
        self.assertLessEqual(
            stats.estimated_tokens_by_packet["semantic_arrow"], stats.estimated_tokens_by_packet["gg"]
        )

        summary_graph = Graph(
            nodes={
                "A": Node("A", "Alpha", facts=("handles auth",)),
                "B": Node("B", "Beta", summary="stores tokens"),
            },
            edges=[Edge("A", "B", "calls")],
        )
        summary_stats = compute_subgraph_stats(summary_graph, {"A", "B"}, summary_graph.edges)
        summary_plan = refine_plan_for_subgraph(plan_context("subsystem_summary", "auth subsystem"), summary_stats)
        self.assertEqual(summary_plan.packet, "gg")

    def test_calibrated_token_surface_preserves_density_crossover(self) -> None:
        from graphgraph.planning import estimate_packet_tokens

        zero_edge = estimate_packet_tokens(2, 0)
        self.assertLessEqual(zero_edge["semantic_arrow"], zero_edge["gg"])

        sparse = estimate_packet_tokens(20, 10)
        self.assertLess(sparse["semantic_arrow"], sparse["gg"])

        dense = estimate_packet_tokens(20, 50)
        self.assertLess(dense["gg"], dense["semantic_arrow"])
        self.assertLess(dense["gg"], dense["sql"])

    def test_subgraph_relation_entropy_is_normalized_shannon_entropy(self) -> None:
        from graphgraph.planning import compute_subgraph_stats

        graph = Graph(
            nodes={"A": Node("A", "A"), "B": Node("B", "B"), "C": Node("C", "C")},
            edges=[Edge("A", "B", "calls"), Edge("A", "C", "imports")],
        )
        balanced = compute_subgraph_stats(graph, set(graph.nodes), graph.edges)
        single = compute_subgraph_stats(graph, {"A", "B"}, [graph.edges[0]])
        self.assertAlmostEqual(balanced.relation_entropy, 1.0)
        self.assertEqual(single.relation_entropy, 0.0)

    def test_graph_shape_budget_recommendations_are_candidate_only(self) -> None:
        graph = Graph(
            nodes={
                **{f"S{i}": Node(f"S{i}", f"source_{i}", "python") for i in range(30)},
                **{f"D{i}": Node(f"D{i}", f"doc_{i}", "section") for i in range(100)},
                **{f"F{i}": Node(f"F{i}", f"func_{i}", "function") for i in range(20)},
            },
            edges=[
                *[Edge(f"D{i}", f"F{i % 20}", "mentions") for i in range(100)],
                *[Edge(f"F{i}", f"F{(i + 1) % 20}", "calls") for i in range(20)],
            ],
        )
        shape = profile_graph_shape(graph)
        self.assertGreater(shape.doc_node_ratio, 0.6)
        path_recommendation = recommend_node_budget("multi_hop_path", "runtime graph", shape)
        self.assertEqual(path_recommendation.base_budget, 80)
        self.assertLess(path_recommendation.recommended_budget, path_recommendation.base_budget)
        self.assertEqual(path_recommendation.mode, "candidate")

        blast_recommendation = recommend_node_budget("blast_radius", "runtime graph", shape)
        self.assertEqual(blast_recommendation.base_budget, 120)
        self.assertEqual(blast_recommendation.recommended_budget, blast_recommendation.base_budget)
        self.assertEqual(blast_recommendation.mode, "measured_default")

    def test_recommend_facts_per_node_scales_with_selection_size(self) -> None:
        from graphgraph.planning import recommend_facts_per_node

        # Small selections can afford close to the max per-node allowance.
        self.assertEqual(recommend_facts_per_node(1), 5)
        self.assertEqual(recommend_facts_per_node(0), 5)
        # Monotonically non-increasing as selection size grows.
        prev = recommend_facts_per_node(1)
        for n in (5, 25, 100, 500, 5000):
            current = recommend_facts_per_node(n)
            self.assertLessEqual(current, prev)
            prev = current
        # Always within [1, max_facts] regardless of scale.
        self.assertGreaterEqual(recommend_facts_per_node(1_000_000), 1)
        self.assertEqual(recommend_facts_per_node(1, max_facts=8), 8)

    def test_recommend_node_budget_multi_hop_path_matches_closed_form(self) -> None:
        graph = Graph(
            nodes={
                **{f"S{i}": Node(f"S{i}", f"source_{i}", "python") for i in range(30)},
                **{f"D{i}": Node(f"D{i}", f"doc_{i}", "section") for i in range(100)},
                **{f"F{i}": Node(f"F{i}", f"func_{i}", "function") for i in range(20)},
            },
            edges=[
                *[Edge(f"D{i}", f"F{i % 20}", "mentions") for i in range(100)],
                *[Edge(f"F{i}", f"F{(i + 1) % 20}", "calls") for i in range(20)],
            ],
        )
        shape = profile_graph_shape(graph)
        recommendation = recommend_node_budget("multi_hop_path", "runtime graph", shape)

        self.assertEqual(recommendation.base_budget, 80)
        # lambda_ = 0.05 * 1.2 (doc_node_ratio>=0.65) * 1.25 (nodes<=500) = 0.075
        # density = 0.8 * (1.0 + 0.30*0.8333 + 0.20*0.6667) = 1.106664 -> clipped to 1.106664 (<1.5)
        # tau = 11.9975 + 5.1632*1.106664 = 17.7116 (path-aware gg LOPO refit)
        # n* = (1/0.075) * ln(max(1.1, 0.075/(1e-4*17.7116))) = 50
        self.assertEqual(recommendation.recommended_budget, 50)
        self.assertEqual(recommendation.mode, "candidate")
        self.assertEqual(
            recommendation.reason,
            "Regularized budget: n*=50 (lambda=0.075, tau=17.711); "
            "doc-heavy graph trims structural noise; "
            "warning: import topology looks under-extracted",
        )

    def test_context_window_budget_expands_small_sparse_and_pages_huge_dense(self) -> None:
        small = Graph(
            nodes={f"N{i}": Node(f"N{i}", f"node_{i}", "function") for i in range(300)},
            edges=[Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(40)],
        )
        small_window = recommend_context_window("subsystem_summary", "", profile_graph_shape(small))
        self.assertGreater(small_window.recommended_budget, 120)
        self.assertEqual(small_window.mode, "single_window")

        huge = Graph(
            nodes={f"N{i}": Node(f"N{i}", f"node_{i}", "function") for i in range(6000)},
            edges=[Edge(f"N{i % 6000}", f"N{(i + 1) % 6000}", "references") for i in range(18000)],
        )
        huge_window = recommend_context_window("direct_lookup", "", profile_graph_shape(huge))
        self.assertLess(huge_window.recommended_budget, 80)
        self.assertIn(huge_window.mode, {"paged", "sparse_window"})

    def test_observed_context_window_uses_rendered_first_page(self) -> None:
        graph = Graph(
            nodes={f"N{i}": Node(f"N{i}", f"node_{i}", "function") for i in range(600)},
            edges=[Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(80)],
        )
        shape = profile_graph_shape(graph)
        underfilled = recommend_observed_context_window(
            "multi_hop_path",
            "",
            shape,
            observed_budget=80,
            observed_nodes=80,
            observed_tokens=360,
        )
        self.assertGreater(underfilled.recommended_budget, 80)
        self.assertIn(underfilled.mode, {"single_window", "sparse_window"})

        oversized = recommend_observed_context_window(
            "multi_hop_path",
            "",
            shape,
            observed_budget=80,
            observed_nodes=80,
            observed_tokens=1400,
        )
        self.assertLess(oversized.recommended_budget, 80)
        self.assertEqual(oversized.mode, "paged")

    def test_shape_budget_applies_only_safe_runtime_trims(self) -> None:
        graph = Graph(
            nodes={
                **{f"S{i}": Node(f"S{i}", f"source_{i}", "python") for i in range(30)},
                **{f"D{i}": Node(f"D{i}", f"doc_{i}", "section") for i in range(100)},
                **{f"F{i}": Node(f"F{i}", f"func_{i}", "function") for i in range(20)},
            },
            edges=[
                *[Edge(f"D{i}", f"F{i % 20}", "mentions") for i in range(100)],
                *[Edge(f"F{i}", f"F{(i + 1) % 20}", "calls") for i in range(20)],
            ],
        )
        path_plan = apply_shape_budget(graph, plan_context("multi_hop_path"), "")
        self.assertLess(path_plan.node_budget, 80)
        self.assertIn("shape_budget", path_plan.planner_version)

        blast_plan = apply_shape_budget(graph, plan_context("blast_radius"), "")
        self.assertEqual(blast_plan.node_budget, 120)
        self.assertNotIn("shape_budget", blast_plan.planner_version)

    def test_subsystem_pruning_preserves_doc_like_start_anchors(self) -> None:
        graph = Graph(
            nodes={
                "C": Node("C", "Alpha Tensor", "concept"),
                "S": Node("S", "Service", "function", "src/service.py"),
                "D": Node("D", "Doc", "section", "README.md"),
                **{f"N{i}": Node(f"N{i}", f"N{i}", "function", f"src/n{i}.py") for i in range(8)},
            },
            edges=[Edge("S", f"N{i}", "calls") for i in range(8)],
        )
        plan = plan_context("subsystem_summary", "alpha tensor")
        nodes, edges = prune_doc_concept_noise(
            graph,
            {"C", "S", "D"},
            [],
            ("C", "S"),
            plan,
            max_nodes=3,
        )
        self.assertIn("C", nodes)

    def test_single_token_file_queries_prefer_exact_basename_stem(self) -> None:
        graph = Graph(
            nodes={
                "setup_py": Node("setup_py", "setup.py", "python", "setup.py"),
                "setup_func": Node("setup_func", "setup", "function", "doc/conf.py"),
            },
            edges=[],
        )
        matches = search_nodes(graph, "setup", limit=2)
        self.assertEqual(matches[0].node.id, "setup_py")
        self.assertIn("basename_stem_exact", matches[0].reasons)

    def test_direct_lookup_widens_ambiguous_single_token_plateau(self) -> None:
        graph = Graph(
            nodes={f"F{i}": Node(f"F{i}", "cache", "function", f"src/m{i}.py") for i in range(10)},
            edges=[],
        )
        result = retrieve_context(graph, "cache", "direct_lookup", hops=1)
        self.assertGreaterEqual(len(result.starts), 10)

    def test_negative_query_surfaces_real_edges_instead_of_always_isolated(self) -> None:
        # Regression: negative_query used hops=0 with a 1-node budget, so it
        # could never show connectivity evidence for *any* node regardless
        # of the graph -- a query like "is X isolated/unused" always read as
        # isolated even when X has real callers. Confirmed on a real repo:
        # an actively-called Rust struct (QuadPoly, used via its own
        # associated function QuadPoly::from_uni(...)) read as fully
        # isolated under negative_query. Using plan_context's own default
        # resolution (not an explicit hops override) to exercise exactly
        # what a real query hits.
        graph = Graph(
            nodes={
                "QuadPoly": Node("QuadPoly", "QuadPoly", "struct", "src/integrate.rs"),
                "from_uni": Node("from_uni", "from_uni", "function", "src/integrate.rs"),
                "caller": Node("caller", "integrate_rational_rothstein_trager", "function", "src/integrate.rs"),
            },
            edges=[
                Edge("caller", "from_uni", "calls"),
                Edge("from_uni", "QuadPoly", "returns"),
            ],
        )
        plan = plan_context("negative_query", "QuadPoly")
        result = retrieve_context(graph, "QuadPoly", "negative_query", hops=plan.hops, max_nodes=plan.node_budget)
        self.assertIn("QuadPoly", result.nodes)
        self.assertTrue(result.edges, "negative_query should surface real connectivity evidence, not read as isolated")

    def test_blast_radius_reserves_immediate_anchor_callee_under_budget_pressure(self) -> None:
        graph = Graph(
            nodes={
                "route": Node("route", "route", "function", "src/app.py"),
                "pop": Node("pop", "pop", "function", "src/ctx.py"),
                **{f"T{i}": Node(f"T{i}", f"test_{i}", "function", f"tests/test_{i}.py") for i in range(150)},
            },
            edges=[
                Edge("route", "pop", "calls", confidence=0.9),
                *[Edge(f"T{i}", "route", "calls", confidence=1.0) for i in range(150)],
            ],
        )
        result = retrieve_context(graph, "route", "blast_radius", hops=2, max_nodes=40)
        self.assertIn("pop", result.nodes)

    def test_blast_radius_reserves_test_support_files_for_test_hubs(self) -> None:
        graph = Graph(
            nodes={
                "TestRequests": Node("TestRequests", "TestRequests", "class", "tests/test_requests.py"),
                "test_requests_py": Node("test_requests_py", "test_requests.py", "python", "tests/test_requests.py"),
                "tests_init": Node("tests_init", "__init__.py", "python", "tests/__init__.py"),
                "tests_compat": Node("tests_compat", "compat.py", "python", "tests/compat.py"),
                **{f"T{i}": Node(f"T{i}", f"test_{i}", "function", "tests/test_requests.py") for i in range(80)},
            },
            edges=[
                Edge("test_requests_py", "TestRequests", "contains"),
                *[Edge("TestRequests", f"T{i}", "contains") for i in range(80)],
            ],
        )
        result = retrieve_context(graph, "test requests", "blast_radius", hops=2, max_nodes=30)
        self.assertIn("test_requests_py", result.nodes)
        self.assertIn("tests_init", result.nodes)
        self.assertIn("tests_compat", result.nodes)

    def test_shape_edge_budget_reduces_dense_fanout_but_keeps_start_edges(self) -> None:
        edges = [
            Edge("A", "B", "calls"),
            *[Edge(f"N{i}", f"M{i}", "imports") for i in range(120)],
            *[Edge(f"D{i}", f"C{i}", "explains") for i in range(80)],
        ]
        plan = plan_context("blast_radius", "dense")
        shaped = shape_edge_budget(edges, ("A",), plan, node_count=40)
        self.assertLess(len(shaped), len(edges))
        self.assertIn(("A", "B", "calls"), {(edge.source, edge.target, edge.type) for edge in shaped})
        self.assertTrue(any(edge.type == "imports" for edge in shaped))
        self.assertTrue(any(edge.type == "explains" for edge in shaped))

    def test_default_path_resolution(self) -> None:
        from graphgraph.io import find_external_graph_path, find_graph_path, find_policies_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(FileNotFoundError):
                find_graph_path(workspace_root=root)

            self.assertIsNone(find_policies_path(workspace_root=root))

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir()
            mock_graph = gg_dir / "graph.json"
            mock_graph.write_text("{}", encoding="utf-8")

            self.assertEqual(find_graph_path(workspace_root=root), mock_graph)

            graphify_dir = root / "graphify-out"
            graphify_dir.mkdir()
            graphify_graph = graphify_dir / "graph.json"
            graphify_graph.write_text("{}", encoding="utf-8")
            self.assertEqual(find_graph_path(workspace_root=root), mock_graph)
            self.assertEqual(find_external_graph_path(workspace_root=root), graphify_graph)
            mock_graph.unlink()
            with self.assertRaises(FileNotFoundError):
                find_graph_path(workspace_root=root)
            self.assertEqual(find_graph_path(workspace_root=root, include_external=True), graphify_graph)

            mock_policies = root / "policies.json"
            mock_policies.write_text("[]", encoding="utf-8")
            self.assertEqual(find_policies_path(workspace_root=root), mock_policies)

    def test_subsystem_summary_prunes_doc_concept_spillover(self) -> None:
        nodes = {
            "SRC": Node("SRC", "operator planning status", "function", "src/operator/planning.py"),
            "HELPER": Node("HELPER", "operator executor", "function", "src/operator/executor.py"),
        }
        edges = [Edge("SRC", "HELPER", "calls")]
        for i in range(30):
            doc_id = f"D{i}"
            concept_id = f"C{i}"
            nodes[doc_id] = Node(doc_id, f"operator planning note {i}", "section", f"docs/note_{i}.md")
            nodes[concept_id] = Node(concept_id, f"operator planning concept {i}", "concept")
            edges.append(Edge("SRC", doc_id, "explains", confidence=0.9, provenance="doc"))
            edges.append(Edge(doc_id, concept_id, "discusses", confidence=0.9, provenance="doc"))
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(graph, "operator planning status", "subsystem_summary", hops=2, max_nodes=80)
        doc_nodes = [
            nid for nid in result.nodes if graph.nodes[nid].kind in {"section", "markdown", "text", "rst", "html"}
        ]
        concept_nodes = [nid for nid in result.nodes if graph.nodes[nid].kind == "concept"]

        self.assertIn("SRC", result.nodes)
        self.assertIn("HELPER", result.nodes)
        self.assertTrue(
            any(edge.source == "SRC" and edge.target == "HELPER" and edge.type == "calls" for edge in result.edges)
        )
        self.assertLessEqual(len(doc_nodes), 16)
        self.assertLessEqual(len(concept_nodes), 2)
        self.assertTrue(all(edge.source in result.nodes and edge.target in result.nodes for edge in result.edges))

    def test_doc_summary_packet_does_not_use_status_pruning(self) -> None:
        nodes = {
            "DOC": Node("DOC", "README installation usage", "section", "README.md"),
        }
        for i in range(4):
            nodes[f"C{i}"] = Node(f"C{i}", f"installation concept {i}", "concept")
        edges = [Edge("DOC", f"C{i}", "discusses", confidence=0.9, provenance="doc") for i in range(4)]
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(graph, "README installation usage", "subsystem_summary", hops=1, max_nodes=40)
        self.assertEqual(result.starts[0], "DOC")
        self.assertGreaterEqual(len([nid for nid in result.nodes if graph.nodes[nid].kind == "concept"]), 3)

    def test_subsystem_summary_uses_compact_node_budget(self) -> None:
        self.assertEqual(default_anchor_limit("README installation usage", "subsystem_summary"), 6)
        self.assertEqual(default_anchor_limit("search", "blast_radius"), 6)
        self.assertEqual(default_anchor_limit("auth service", "blast_radius"), 6)
        self.assertEqual(default_anchor_limit("compiler expression rules", "blast_radius"), 5)
        self.assertEqual(retrieval_node_budget("auth service", "direct_lookup", None), 80)
        self.assertEqual(retrieval_node_budget("compile rules", "reverse_lookup", None), 80)
        self.assertEqual(retrieval_node_budget("compile to runtime path", "multi_hop_path", None), 80)
        self.assertEqual(retrieval_node_budget("auth service", "blast_radius", None), 120)
        self.assertEqual(retrieval_node_budget("matrix subsystem", "subsystem_summary", None), 120)
        self.assertEqual(retrieval_node_budget("missing auth service", "negative_query", None), 8)
        self.assertEqual(
            retrieval_node_budget("matrix transpose orthogonal symmetric square vector rules", "subsystem_summary", 40),
            32,
        )
        self.assertEqual(retrieval_node_budget("README installation usage", "subsystem_summary", 40), 12)
        self.assertEqual(retrieval_node_budget("README installation usage", "doc_summary", 40), 12)
        self.assertEqual(retrieval_node_budget("auth service", "blast_radius", 40), 40)
