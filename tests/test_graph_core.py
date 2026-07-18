from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
    add_decision_trace,
    add_edge,
    add_node,
    append_operation,
    expire_edge,
    expire_node,
    merge_node,
    operation_to_json,
    read_operations,
)
from graphgraph.metrics import compare_graphs, summarize_graph


class GraphCoreTest(unittest.TestCase):
    def test_expand_two_hops(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        self.assertEqual(nodes, {"N1", "N2", "N3"})
        self.assertEqual(
            [(edge.source, edge.target, edge.type) for edge in edges], [("N1", "N2", "reads"), ("N2", "N3", "writes")]
        )

    def test_expand_with_max_nodes_budget(self) -> None:
        graph = sample_graph()
        # N1 expands to N2 (hop 1) and N3 (hop 2). With max_nodes=2, it should truncate N3 and its edge.
        nodes, edges = graph.expand(["N1"], hops=2, max_nodes=2)
        self.assertEqual(nodes, {"N1", "N2"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in edges], [("N1", "N2", "reads")])

    def test_expand_keeps_same_round_edges_when_budget_exhausted_mid_round(self) -> None:
        # Regression: when the node budget was hit while `scores` was still
        # non-empty (new candidates were found, just no room left for them),
        # expand() broke out of the loop *before* appending new_edges whose
        # both endpoints were already included (e.g. a direct edge between
        # two explicit start nodes) -- silently dropping a real
        # intra-subgraph edge from the packet. Two starts already connected
        # by an edge, with max_nodes equal to the start count (no room to
        # expand further), reproduces this directly.
        graph = Graph(
            nodes={
                "A": Node("A", "A", "function"),
                "B": Node("B", "B", "function"),
                "C": Node("C", "C", "function"),
            },
            edges=[Edge("A", "B", "calls"), Edge("A", "C", "calls")],
        )
        included, edges = graph.expand(starts=("A", "B"), hops=2, max_nodes=2)
        self.assertEqual(included, {"A", "B"})
        self.assertIn(("A", "B", "calls"), [(e.source, e.target, e.type) for e in edges])

    def test_expand_zero_hops_keeps_edges_between_start_nodes(self) -> None:
        # Regression: with hops=0 the expansion loop body never runs at all,
        # so the only place that ever emits edges between already-included
        # nodes (the `not scores` catch-up branch, or the `all_included`
        # filter after a round) never gets a chance to run either. Two start
        # nodes that are directly connected reproduce this: expand() returned
        # both nodes correctly but silently dropped the edge between them,
        # even though both endpoints were already selected.
        graph = Graph(
            nodes={
                "A": Node("A", "A", "function"),
                "B": Node("B", "B", "function"),
            },
            edges=[Edge("A", "B", "calls")],
        )
        included, edges = graph.expand(starts=("A", "B"), hops=0)
        self.assertEqual(included, {"A", "B"})
        self.assertEqual([(e.source, e.target, e.type) for e in edges], [("A", "B", "calls")])

    def test_expand_direction(self) -> None:
        graph = sample_graph()
        out_nodes, out_edges = graph.expand(["N2"], hops=1, direction="out")
        self.assertEqual(out_nodes, {"N2", "N3"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in out_edges], [("N2", "N3", "writes")])

        in_nodes, in_edges = graph.expand(["N2"], hops=1, direction="in")
        self.assertEqual(in_nodes, {"N1", "N2"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in in_edges], [("N1", "N2", "reads")])

    def test_pagerank(self) -> None:
        # N1 -> N2 -> N3. All flows go to N3, so N3 should have the highest PageRank.
        graph = Graph(
            nodes={
                "N1": Node("N1", "Source", "file", active=True),
                "N2": Node("N2", "Middle", "file", active=True),
                "N3": Node("N3", "Sink", "file", active=True),
            },
            edges=[
                Edge("N1", "N2", "calls", 1.0),
                Edge("N2", "N3", "calls", 1.0),
            ],
        )
        scores = graph.pagerank(damping=0.85)
        self.assertEqual(len(scores), 3)
        self.assertAlmostEqual(sum(scores.values()), 1.0, places=4)
        # N3 (Sink) should have higher score than N2, which should be higher than N1 (Source)
        self.assertTrue(scores["N3"] > scores["N2"])
        self.assertTrue(scores["N2"] > scores["N1"])

    def test_graph_operations_add_expire_merge_and_trace(self) -> None:
        graph = Graph()
        graph, op = add_node(graph, Node("A", "Alpha"))
        self.assertEqual(op.op, "AddNode")
        graph, _ = add_node(graph, Node("B", "Beta", facts=("fact",)))
        graph, op = add_edge(graph, Edge("A", "B", "calls", source_location="a.py:1"))
        self.assertEqual(op.op, "AddEdge")
        self.assertEqual(len(graph.edges), 1)

        graph, op = expire_edge(graph, "A", "B", "calls", "2026-06-26T00:00:00Z", reason="deprecated")
        self.assertEqual(op.op, "ExpireEdge")
        self.assertFalse(graph.edges[0].active)
        self.assertEqual(graph.edges[0].valid_to, "2026-06-26T00:00:00Z")

        graph, op = merge_node(graph, "B", "A", reason="same entity")
        self.assertEqual(op.op, "MergeEntity")
        self.assertIn("A", graph.nodes)
        self.assertNotIn("B", graph.nodes)
        self.assertEqual(graph.nodes["A"].facts, ("fact",))

    def test_merge_node_redirects_dangling_parent_references(self) -> None:
        # Regression: merge_node rewrote edges pointing at source_id but not
        # Node.parent fields naming it, so a merged-away node's former
        # children were left with a parent reference to a node that no
        # longer exists in the graph.
        graph = Graph(
            nodes={
                "A": Node("A", "A"),
                "B": Node("B", "B"),
                "CHILD": Node("CHILD", "child", parent="A"),
            }
        )
        graph, _ = merge_node(graph, "A", "B", reason="dup")
        self.assertNotIn("A", graph.nodes)
        self.assertEqual(graph.nodes["CHILD"].parent, "B")

    def test_expire_node_soft_deletes_node_and_incident_edges(self) -> None:
        graph = Graph()
        graph, _ = add_node(graph, Node("A", "Alpha"))
        graph, _ = add_node(graph, Node("B", "Beta"))
        graph, _ = add_node(graph, Node("C", "Gamma"))
        graph, _ = add_edge(graph, Edge("A", "B", "calls"))
        graph, _ = add_edge(graph, Edge("C", "A", "calls"))
        graph, _ = add_edge(graph, Edge("B", "C", "calls"))  # unrelated to A

        graph, op = expire_node(graph, "A", "2026-07-08T00:00:00Z", reason="file removed")
        self.assertEqual(op.op, "ExpireNode")
        self.assertEqual(op.target, "A")

        # Node itself is soft-deleted, not removed -- still present, inactive.
        self.assertIn("A", graph.nodes)
        self.assertFalse(graph.nodes["A"].active)
        self.assertEqual(graph.nodes["A"].updated_at, "2026-07-08T00:00:00Z")

        by_key = {(e.source, e.target, e.type): e for e in graph.edges}
        self.assertFalse(by_key[("A", "B", "calls")].active)
        self.assertFalse(by_key[("C", "A", "calls")].active)
        # Edge not touching A is untouched.
        self.assertTrue(by_key[("B", "C", "calls")].active)

    def test_expire_node_can_leave_incident_edges_untouched(self) -> None:
        graph = Graph()
        graph, _ = add_node(graph, Node("A", "Alpha"))
        graph, _ = add_node(graph, Node("B", "Beta"))
        graph, _ = add_edge(graph, Edge("A", "B", "calls"))

        graph, _ = expire_node(graph, "A", "2026-07-08T00:00:00Z", expire_incident_edges=False)
        self.assertFalse(graph.nodes["A"].active)
        self.assertTrue(graph.edges[0].active)

    def test_operation_log_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops.jsonl"
            _graph, op = add_node(Graph(), Node("A", "Alpha"))
            append_operation(path, op)
            ops = read_operations(path)
            self.assertEqual(len(ops), 1)
            self.assertEqual(ops[0].op, "AddNode")
            self.assertEqual(operation_to_json(ops[0])["target"], "A")

    def test_decision_trace_records_inputs_and_policies(self) -> None:
        graph = Graph(nodes={"N1": Node("N1", "Input"), "policy_P1": Node("policy_P1", "P1", kind="policy")})
        graph, op = add_decision_trace(
            graph,
            "D1",
            "Chose auth packet",
            inputs=("N1",),
            policies=("P1",),
            outcome="approved",
            timestamp="2026-06-26T00:00:00Z",
            actor="agent",
        )
        self.assertEqual(op.op, "AddDecisionTrace")
        self.assertEqual(graph.nodes["D1"].kind, "decision_trace")
        edge_types = {edge.type for edge in graph.edges}
        self.assertIn("used_input", edge_types)
        self.assertIn("applied_policy", edge_types)

    def test_graph_metrics_summary_and_comparison(self) -> None:
        left = sample_graph()
        right = Graph(
            nodes={
                "X1": Node("X1", "AuthService", "service", "server/auth.py"),
                "X2": Node("X2", "Other", "file", "other.py"),
            },
            edges=[Edge("X1", "X2", "references", 0.5)],
        )
        summary = summarize_graph(left)
        self.assertEqual(summary.nodes, 3)
        self.assertEqual(summary.edge_types["reads"], 1)
        comparison = compare_graphs(left, right)
        self.assertEqual(comparison.shared_node_paths, 1)
        self.assertEqual(comparison.shared_edge_keys, 0)
        equivalent = Graph(
            nodes={
                "X1": Node("X1", "AuthService", "service", "server/auth.py"),
                "X2": Node("X2", "TokenStore", "data", "server/tokens.py"),
            },
            edges=[Edge("X1", "X2", "reads", 0.9)],
        )
        normalized = compare_graphs(left, equivalent)
        self.assertEqual(normalized.shared_normalized_edges, 1)

    def test_pagerank_scores_active_graph_without_rebuilding_semantics(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "A"),
                "B": Node("B", "B"),
                "C": Node("C", "C"),
                "D": Node("D", "D", active=False),
            },
            edges=[
                Edge("A", "B", "calls"),
                Edge("C", "B", "calls"),
                Edge("B", "A", "references"),
                Edge("A", "D", "calls"),
            ],
        )
        scores = graph.pagerank(max_iter=10)
        self.assertEqual(set(scores), {"A", "B", "C"})
        self.assertGreater(scores["B"], scores["C"])
        self.assertAlmostEqual(sum(scores.values()), 1.0, places=6)

    def test_pagerank_cache_reuses_and_invalidates_on_graph_shape(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "A"),
                "B": Node("B", "B"),
                "C": Node("C", "C"),
            },
            edges=[Edge("A", "B", "calls")],
        )
        first = graph.pagerank()
        cache = graph._pagerank_cache
        self.assertIsNotNone(cache)
        second = graph.pagerank()
        self.assertEqual(first, second)
        self.assertIs(graph._pagerank_cache, cache)

        graph.edges.append(Edge("C", "B", "calls"))
        third = graph.pagerank()
        self.assertNotEqual(graph._pagerank_cache, cache)
        self.assertGreater(third["B"], first["B"])

    def test_pagerank_cache_invalidates_when_edge_weight_is_replaced(self) -> None:
        graph = Graph(
            nodes={node_id: Node(node_id, node_id) for node_id in ("A", "B", "C")},
            edges=[
                Edge("A", "B", "calls", weight=1.0),
                Edge("A", "C", "calls", weight=1.0),
            ],
        )
        before = graph.pagerank()

        graph.edges[0] = Edge("A", "B", "calls", weight=100.0)
        after = graph.pagerank()
        expected = Graph(nodes=dict(graph.nodes), edges=list(graph.edges)).pagerank()

        self.assertEqual(after, expected)
        self.assertNotEqual(after, before)
        self.assertGreater(after["B"], after["C"])

    def test_adjacency_cache_invalidates_when_edge_is_replaced(self) -> None:
        graph = Graph(
            nodes={node_id: Node(node_id, node_id) for node_id in ("A", "B", "C")},
            edges=[Edge("A", "B", "calls")],
        )
        self.assertEqual([edge.target for edge in graph.outgoing()["A"]], ["B"])

        graph.edges[0] = Edge("C", "B", "calls")

        self.assertNotIn("A", graph.outgoing())
        self.assertEqual([edge.target for edge in graph.outgoing()["C"]], ["B"])

    def test_graph_mutation_revision_tracks_store_instructions(self) -> None:
        graph = Graph(nodes={"A": Node("A", "A")}, edges=[Edge("A", "A", "references")])
        revisions = [graph.mutation_revision]

        graph.nodes["A"] = Node("A", "Alpha")
        revisions.append(graph.mutation_revision)
        graph.nodes.update({"B": Node("B", "Beta")})
        revisions.append(graph.mutation_revision)
        graph.edges[0] = Edge("B", "A", "calls")
        revisions.append(graph.mutation_revision)
        graph.edges.extend([Edge("A", "B", "calls")])
        revisions.append(graph.mutation_revision)

        self.assertEqual(len(set(revisions)), len(revisions))
        self.assertTrue(all(after > before for before, after in zip(revisions, revisions[1:])))

    def test_graph_expansion_ignores_inactive_context(self) -> None:
        graph = Graph(
            nodes={
                "N1": Node("N1", "A"),
                "N2": Node("N2", "B", active=False),
                "N3": Node("N3", "C"),
            },
            edges=[
                Edge("N1", "N2", "calls"),
                Edge("N1", "N3", "calls", active=False),
            ],
        )
        nodes, edges = graph.expand(["N1"], hops=1)
        self.assertEqual(nodes, {"N1"})
        self.assertEqual(edges, [])

    def test_graph_expansion_relation_gate_prefers_recognized_edges(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "A"),
                "B": Node("B", "B"),
                **{f"D{i}": Node(f"D{i}", f"Doc {i}") for i in range(20)},
            },
            edges=[Edge("A", "B", "calls")] + [Edge("A", f"D{i}", "explains") for i in range(20)],
        )
        nodes, edges = graph.expand(["A"], hops=1, max_nodes=5, allowed_relations={"calls"})
        self.assertEqual(nodes, {"A", "B"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in edges], [("A", "B", "calls")])

    def test_graph_expansion_relation_gate_falls_back_for_custom_only_frontier(self) -> None:
        graph = Graph(
            nodes={"A": Node("A", "A"), "B": Node("B", "B")},
            edges=[Edge("A", "B", "custom_relation")],
        )
        nodes, edges = graph.expand(["A"], hops=1, allowed_relations={"calls"})
        self.assertEqual(nodes, {"A", "B"})
        self.assertEqual([edge.type for edge in edges], ["custom_relation"])

    def test_graph_expansion_with_energy_decay(self) -> None:
        nodes = {
            "A": Node("A", "A"),
            "B": Node("B", "B"),
            "C": Node("C", "C"),
            "H": Node("H", "H"),
            "D": Node("D", "D"),
        }
        for i in range(50):
            nodes[f"Dummy{i}"] = Node(f"Dummy{i}", f"Dummy{i}")

        edges = [
            Edge("A", "B", "calls", weight=1.0),
            Edge("B", "C", "calls", weight=1.0),
            Edge("A", "H", "calls", weight=1.0),
            Edge("H", "D", "calls", weight=1.0),
        ]
        for i in range(50):
            edges.append(Edge("H", f"Dummy{i}", "calls", weight=1.0))

        graph = Graph(nodes=nodes, edges=edges)
        ret_nodes, ret_edges = graph.expand(["A"], hops=2, max_nodes=100, decay_hubs=True)

        self.assertIn("B", ret_nodes)
        self.assertIn("C", ret_nodes)
        self.assertIn("H", ret_nodes)
        self.assertNotIn("D", ret_nodes)

    def test_cohesion_guided_budget_trimming(self) -> None:
        from graphgraph.planning.types import ContextPlan
        from graphgraph.retrieval.context import expand_context

        nodes = {f"N{i}": Node(f"N{i}", f"N{i}") for i in range(12)}
        edges = []
        for i in range(12):
            for j in range(i + 1, 12):
                edges.append(Edge(f"N{i}", f"N{j}", "calls", weight=1.0))

        graph = Graph(nodes=nodes, edges=edges)
        plan = ContextPlan(
            query_class="blast_radius",
            hops=2,
            direction="both",
            packet="gg",
            node_budget=100,
            anchor_limit=6,
            weak_edge_limit=15,
            min_confidence=0.0,
            reason="test",
        )

        ret_nodes, ret_edges = expand_context(graph, ("N0",), plan)
        self.assertLessEqual(len(ret_nodes), 60)

    def test_expand_context_density_throttle_scales_effective_node_budget(self) -> None:
        from graphgraph.planning.types import ContextPlan
        from graphgraph.retrieval.context import expand_context

        # Chain N0..N29 for connectivity ("calls"), plus skip-two cross edges
        # ("references") to raise local edge density and engage the Edge Density
        # Throttle's `scale = max(0.4, min(1.0, 1.5/density))` (retrieval/context.py).
        N = 30
        nodes = {f"N{i}": Node(f"N{i}", f"N{i}") for i in range(N)}
        edges = [Edge(f"N{i}", f"N{i + 1}", "calls", weight=1.0) for i in range(N - 1)]
        edges += [Edge(f"N{i}", f"N{i + 2}", "references", weight=1.0) for i in range(N - 2)]
        graph = Graph(nodes=nodes, edges=edges)

        plan = ContextPlan(
            query_class="multi_hop_path",
            hops=40,
            direction="out",
            packet="gg",
            node_budget=34,
            anchor_limit=6,
            weak_edge_limit=100,
            min_confidence=0.0,
            reason="test",
        )
        ret_nodes, ret_edges = expand_context(graph, ("N0",), plan)

        kept = {rel: len([e for e in ret_edges if e.type == rel]) for rel in {"calls", "references"}}
        # Initial density is 57/30=1.9, so the effective node budget is
        # floor(34 * 1.5/1.9)=26. Packet-aware partitioning may trim further
        # when incident edge rows consume the token budget.
        self.assertLessEqual(len(ret_nodes), 26)
        self.assertLessEqual(kept["references"], kept["calls"])
        reachable = {"N0"}
        while True:
            expanded = reachable | {
                edge.target if edge.source in reachable else edge.source
                for edge in ret_edges
                if edge.source in reachable or edge.target in reachable
            }
            if expanded == reachable:
                break
            reachable = expanded
        self.assertTrue(ret_nodes <= reachable)

    def test_personalized_pagerank(self) -> None:
        from graphgraph.core import Edge, Graph, Node
        from graphgraph.retrieval import search_nodes

        g = Graph(
            nodes={
                "A": Node("A", "AuthService", "service", "auth.py", active=True),
                "B": Node("B", "TokenStore", "data", "tokens.py", active=True),
                "C": Node("C", "AuditLog", "data", "audit.py", active=True),
            },
            edges=[
                Edge("A", "B", "calls", 1.0),
                Edge("C", "B", "calls", 1.0),
            ],
        )

        # Standard PageRank: B has incoming edges from A and C, so it should rank highest globally.
        pr = g.pagerank()
        self.assertGreater(pr["B"], pr["A"])

        # Personalized PageRank starting at A: A should receive the highest probability, and B (directly connected to A) should receive more than C (not connected to A).
        ppr = g.personalized_pagerank(personalization={"A": 1.0})
        self.assertGreater(ppr["A"], ppr["B"])
        self.assertGreater(ppr["B"], ppr["C"])

        # Test personalized search
        matches = search_nodes(g, "AuthService", personalize=True)
        self.assertEqual(matches[0].node.id, "A")

    def test_localized_personalized_pagerank_is_bounded_and_seeded(self) -> None:
        nodes = {f"N{i}": Node(f"N{i}", f"Node {i}") for i in range(1000)}
        edges = [Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(999)]
        graph = Graph(nodes=nodes, edges=edges)

        scores = graph.localized_personalized_pagerank(
            {"N0": 1.0},
            max_nodes=40,
            max_pushes=200,
        )

        self.assertLessEqual(len(scores), 40)
        self.assertGreater(scores["N0"], scores.get("N39", 0.0))
        self.assertAlmostEqual(sum(scores.values()), 1.0, places=6)

    def test_adaptive_local_ppr_params_scale_with_size_and_seeds(self) -> None:
        from graphgraph.graph.core import adaptive_local_ppr_params

        small = adaptive_local_ppr_params(1_000, 1)
        large = adaptive_local_ppr_params(100_000, 1)
        # Tolerance sharpens (decreases) as the graph grows so ~1/N-scale PPR
        # values stay separable; the explored frontier and push budget grow.
        self.assertLess(large[0], small[0])
        self.assertGreater(large[1], small[1])
        self.assertGreaterEqual(large[2], small[2])
        # More seeds widen the frontier at a fixed graph size.
        self.assertGreater(
            adaptive_local_ppr_params(10_000, 5)[1],
            adaptive_local_ppr_params(10_000, 1)[1],
        )
        # All outputs stay within the documented clamps regardless of extremes.
        for n_nodes in (1, 10, 10_000_000):
            tol, max_nodes, max_pushes = adaptive_local_ppr_params(n_nodes, 1)
            self.assertTrue(1e-6 <= tol <= 3e-4)
            self.assertTrue(256 <= max_nodes <= 8192)
            self.assertTrue(1024 <= max_pushes <= 65536)

    def test_localized_ppr_auto_params_match_explicit_derivation(self) -> None:
        from graphgraph.graph.core import adaptive_local_ppr_params

        nodes = {f"N{i}": Node(f"N{i}", f"Node {i}") for i in range(1000)}
        edges = [Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(999)]
        graph = Graph(nodes=nodes, edges=edges)
        tol, max_nodes, max_pushes = adaptive_local_ppr_params(len(graph.nodes), 1)
        auto = graph.localized_personalized_pagerank({"N0": 1.0})
        explicit = graph.localized_personalized_pagerank(
            {"N0": 1.0}, tolerance=tol, max_nodes=max_nodes, max_pushes=max_pushes
        )
        self.assertEqual(auto, explicit)

    def test_large_graph_personalized_search_uses_local_ppr(self) -> None:
        from graphgraph.retrieval import search_nodes

        graph = Graph(
            nodes={f"N{i}": Node(f"N{i}", "Target" if i == 0 else f"Node {i}") for i in range(600)},
            edges=[Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(599)],
        )
        with patch.object(
            graph,
            "personalized_pagerank",
            side_effect=AssertionError("full personalized PageRank ran for a large graph"),
        ):
            matches = search_nodes(graph, "Target", personalize=True)
        self.assertEqual(matches[0].node.id, "N0")

    def test_large_graph_broad_query_does_not_use_local_ppr(self) -> None:
        from graphgraph.retrieval import search_nodes

        graph = Graph(
            nodes={
                f"N{i}": Node(f"N{i}", "Retrieval" if i == 0 else f"Node {i}")
                for i in range(600)
            },
            edges=[Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(599)],
        )
        with patch.object(
            graph,
            "localized_personalized_pagerank",
            side_effect=AssertionError("local PPR ran for a broad natural-language query"),
        ):
            matches = search_nodes(graph, "retrieval anchor scoring", personalize=True)
        self.assertEqual(matches[0].node.id, "N0")

    def test_personalization_lexical_score_constants(self) -> None:
        from graphgraph.core import Graph, Node
        from graphgraph.retrieval import search_nodes

        def capture_personalization(query: str, nodes: dict) -> dict:
            g = Graph(nodes=nodes, edges=[])
            captured: dict = {}
            original_ppr = g.personalized_pagerank

            def _capture(personalization, *args, **kwargs):
                captured["p"] = dict(personalization)
                return original_ppr(personalization, *args, **kwargs)

            g.personalized_pagerank = _capture
            with patch("graphgraph.retrieval.git_utils.get_git_modified_files", return_value={}):
                search_nodes(g, query, personalize=True)
            return captured.get("p", {})

        # Exact node-id match only -> +8.0, no other signal.
        p = capture_personalization("svc", {"svc": Node("svc", "AuthService", "service", "auth.py", active=True)})
        self.assertEqual(p.get("svc"), 8.0)

        # Exact whole-label match (single-word label) -> +4.0.
        p = capture_personalization("widget", {"n1": Node("n1", "Widget", "service", "widget.py", active=True)})
        self.assertEqual(p.get("n1"), 4.0)

        # Term present in tokenized label terms, but not equal to the whole label -> +2.0.
        p = capture_personalization("factory", {"n2": Node("n2", "Widget Factory", "service", "wf.py", active=True)})
        self.assertEqual(p.get("n2"), 2.0)

    def test_personalization_git_session_weight_formula(self) -> None:
        from graphgraph.core import Graph, Node
        from graphgraph.retrieval import search_nodes

        def capture_personalization(query: str, nodes: dict, git_files: dict) -> dict:
            g = Graph(nodes=nodes, edges=[])
            captured: dict = {}
            original_ppr = g.personalized_pagerank

            def _capture(personalization, *args, **kwargs):
                captured["p"] = dict(personalization)
                return original_ppr(personalization, *args, **kwargs)

            g.personalized_pagerank = _capture
            with patch("graphgraph.retrieval.git_utils.get_git_modified_files", return_value=git_files):
                search_nodes(g, query, personalize=True)
            return captured.get("p", {})

        node = Node("svc", "AuthService", "service", "auth.py", active=True)

        # Git weight only: query matches nothing lexically; path == modified path.
        # math.log2(6 + 2) * 2.0 == log2(8) * 2.0 == 3.0 * 2.0 == 6.0
        p = capture_personalization("zzzznomatch", {"svc": node}, {"auth.py": 6})
        self.assertEqual(p.get("svc"), 6.0)

        # Combined: id-match lexical (+8.0) plus same git weight (+6.0) == 14.0.
        p = capture_personalization("svc", {"svc": node}, {"auth.py": 6})
        self.assertEqual(p.get("svc"), 14.0)

    def test_personalization_git_session_weight_uses_one_representative_per_path(self) -> None:
        # A dirty file can own many symbol nodes. Session personalization must
        # cover the path once rather than multiplying the same change weight by
        # every symbol in that file and diluting the query-specific seeds.
        from graphgraph.core import Graph, Node
        from graphgraph.retrieval import search_nodes

        def capture_personalization(nodes: dict, git_files: dict) -> dict:
            g = Graph(nodes=nodes, edges=[])
            captured: dict = {}
            original_ppr = g.personalized_pagerank

            def _capture(personalization, *args, **kwargs):
                captured["p"] = dict(personalization)
                return original_ppr(personalization, *args, **kwargs)

            g.personalized_pagerank = _capture
            with patch("graphgraph.retrieval.git_utils.get_git_modified_files", return_value=git_files):
                search_nodes(g, "zzzznomatch", personalize=True)
            return captured.get("p", {})

        nodes = {
            "fn1": Node("fn1", "parse", "function", "auth.py", active=True),
            "fn2": Node("fn2", "validate", "function", "auth.py", active=True),
        }
        p = capture_personalization(nodes, {"auth.py": 6})
        weighted = {node_id: weight for node_id, weight in p.items() if weight == 6.0}
        self.assertEqual(weighted, {"fn2": 6.0})

