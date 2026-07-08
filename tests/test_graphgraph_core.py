from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from graphgraph import (
    Edge,
    Graph,
    Node,
    Policy,
    Query,
    add_decision_trace,
    add_edge,
    add_node,
    add_policy_node,
    append_operation,
    choose_packet,
    expire_edge,
    expire_node,
    merge_node,
    operation_to_json,
    plan_context,
    policy_to_node,
    read_operations,
    remove_paths,
    scan_directory,
    select_policies,
    update_paths,
    validate_packet,
)
from graphgraph.ast_scanner import extract_symbols
from graphgraph.doc_scanner import DocumentInput, extract_document_context
from graphgraph.doccode import summarize_doc_code_components, summarize_doc_code_coverage
from graphgraph.eval import EvalTask, estimate_tokens, evaluate_graph
from graphgraph.frontends import (
    RegexExtractor,
    SourceFile,
    _imported_symbol_names,
    available_frontends,
    select_extractor,
    tree_sitter_available,
)
from graphgraph.io import (
    graph_to_json,
    load_any,
    load_csv_edges,
    load_gg,
    load_graph,
    load_policies,
    save_gg,
    save_graph,
    save_validated_graph,
)
from graphgraph.mcp_server import dispatch
from graphgraph.metrics import compare_graphs, summarize_graph
from graphgraph.ontology import provenance_confidence, relation_spec, traversal_strength
from graphgraph.packets import (
    render_doc_summary,
    render_gg_max,
    render_lowlevel,
    render_packet,
    render_semantic_arrow,
    render_sql,
    render_svo,
)
from graphgraph.planning import (
    profile_graph_shape,
    recommend_context_window,
    recommend_node_budget,
    recommend_observed_context_window,
)
from graphgraph.policies import render_policy_packet
from graphgraph.retrieval import (
    budget_edges,
    default_anchor_limit,
    retrieval_node_budget,
    retrieve_context,
    search_nodes,
    tokenize,
)
from graphgraph.retrieval.context import apply_shape_budget, prune_doc_concept_noise, shape_edge_budget
from graphgraph.retrieval.models import Match
from graphgraph.services import render_final_packet, render_query_context, render_source_snippets
from graphgraph.services.context import resolve_start_nodes
from graphgraph.services.native import graph_shape, render_native_context
from graphgraph.terms import canonical_concept_label, concept_id, term_key
from graphgraph.traversal import relation_rank, traversal_policy
from graphgraph.validate import validate_any, validate_graph_json

if TYPE_CHECKING:
    from graphgraph.cache import TopologicalKVCache


def sample_graph() -> Graph:
    return Graph(
        nodes={
            "N1": Node("N1", "AuthService", "service", "server/auth.py"),
            "N2": Node("N2", "TokenStore", "data", "server/tokens.py"),
            "N3": Node("N3", "AuditLog", "data", "server/audit.py"),
        },
        edges=[
            Edge("N1", "N2", "reads", 0.9),
            Edge("N2", "N3", "writes", 0.8),
        ],
    )


class GraphGraphCoreTest(unittest.TestCase):
    def test_expand_two_hops(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        self.assertEqual(nodes, {"N1", "N2", "N3"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in edges], [("N1", "N2", "reads"), ("N2", "N3", "writes")])

    def test_expand_with_max_nodes_budget(self) -> None:
        graph = sample_graph()
        # N1 expands to N2 (hop 1) and N3 (hop 2). With max_nodes=2, it should truncate N3 and its edge.
        nodes, edges = graph.expand(["N1"], hops=2, max_nodes=2)
        self.assertEqual(nodes, {"N1", "N2"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in edges], [("N1", "N2", "reads")])

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

    def test_render_and_validate_lowlevel(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=1)
        packet = render_lowlevel(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "lowlevel")
        self.assertEqual(result.node_count, 2)
        self.assertEqual(result.edge_count, 1)

    def test_render_and_validate_sql(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=1)
        packet = render_sql(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "sql")

    def test_sql_uses_short_integer_handles_not_qualified_ids(self) -> None:
        # Regression: sql edge rows must reference short integer handles, not the
        # full qualified node ids (which made the format scale badly on real repos).
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_sql(graph, nodes, edges)
        edge_line = next(line for line in packet.splitlines() if line.startswith("TABLE edges:"))
        rows = edge_line.split("|", 1)[1]
        # No qualified node id should appear in the edge rows.
        for node_id in nodes:
            self.assertNotIn(node_id, rows, f"qualified id {node_id} leaked into sql edge rows")
        # Edge endpoints should be the integer handles assigned in node order.
        for entry in [e.strip() for e in rows.split("|") if e.strip()]:
            source, target = entry.split(",")[:2]
            self.assertTrue(source.isdigit() and target.isdigit(), entry)

    def test_render_and_validate_semantic_arrow(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_semantic_arrow(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "semantic_arrow")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

    def test_render_and_validate_gg_max(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_gg_max(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_max")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

    def test_render_and_validate_gg_max_with_default_weights(self) -> None:
        graph = Graph(
            nodes={
                "N1": Node("N1", "AuthService", "service", "server/auth.py"),
                "N2": Node("N2", "TokenStore", "data", "server/tokens.py"),
            },
            edges=[
                Edge("N1", "N2", "reads", 1.0),
            ]
        )
        nodes, edges = graph.expand(["N1"], hops=1)
        packet = render_gg_max(graph, nodes, edges)
        self.assertNotIn("1.0", packet) # weight omitted
        self.assertIn("1:", packet.split("[e]")[1]) # relation opcode group
        self.assertIn("1 2", packet.split("[e]")[1]) # endpoint row under opcode
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_max")
        self.assertEqual(result.node_count, 2)
        self.assertEqual(result.edge_count, 1)

    def test_render_and_validate_gg_lex(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        from graphgraph.packets import render_packet
        packet = render_packet(graph, nodes, edges, "gg_lex")
        self.assertIn("authserv", packet)
        self.assertIn("tokensto", packet)
        self.assertIn("auditlog", packet)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_lex")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

        packet_hybrid = render_packet(graph, nodes, edges, "gg_lex_hybrid")
        result_hybrid = validate_packet(packet_hybrid)
        self.assertTrue(result_hybrid.ok, result_hybrid.errors)
        self.assertEqual(result_hybrid.format, "gg_lex_hybrid")

    def test_render_tensor_array(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        from graphgraph.packets import render_packet
        packet = render_packet(graph, nodes, edges, "tensor")
        self.assertIn("@types", packet)
        self.assertIn("@relations", packet)
        self.assertIn("@v", packet)
        self.assertIn("@a", packet)
        self.assertIn("AuthService", packet)
        self.assertIn("TokenStore", packet)

    def test_render_and_validate_gg_max_hybrid(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        from graphgraph.packets import render_packet
        packet = render_packet(graph, nodes, edges, "gg_max_hybrid")
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_max_hybrid")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

    def test_validation_rejects_missing_node(self) -> None:
        packet = """<g>
<r>
1:reads
</r>
<n>
N1:AuthService
</n>
<a>
N1,N2,1,0.9
</a>
</g>"""
        result = validate_packet(packet)
        self.assertFalse(result.ok)
        self.assertIn("edge target missing from nodes: N2", result.errors)

    def test_validation_rejects_empty_packets(self) -> None:
        packets = [
            "@nodes\n\n@edges\n",
            "[r]\n1:reads\n[n]\n\n[e]\n",
            "<g>\n<r>\n1:reads\n</r>\n<n>\n</n>\n<a>\n</a>\n</g>",
            "TABLE nodes: |\nTABLE edges: |\n",
        ]
        for packet in packets:
            with self.subTest(packet=packet.splitlines()[0]):
                result = validate_packet(packet)
                self.assertFalse(result.ok)
                self.assertIn("empty packet: no nodes", result.errors)

    def test_policy_selection(self) -> None:
        policies = [
            Policy("P1", "frontend", "must", ("src/ui/**",), ("frontend",), "UI compact"),
            Policy("P2", "security", "must", ("server/auth/**",), ("security",), "SEC compact"),
        ]
        query = Query("update button", "direct_lookup", paths=("src/ui/Button.tsx",), tags=("frontend",))
        selected = select_policies(policies, query)
        self.assertEqual([policy.id for policy in selected], ["P1"])
        self.assertEqual(render_policy_packet(selected), "P1:must:UI compact")

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

    def test_packet_renderers_skip_dangling_nodes_and_edges(self) -> None:
        graph = sample_graph()
        nodes = {"N1", "N2", "ghost_node_from_old_scan"}
        edges = [Edge("N1", "N2", "reads"), Edge("N2", "ghost_node_from_old_scan", "reads")]
        modes = [
            "lowlevel",
            "sql",
            "hybrid",
            "semantic_arrow",
            "gg_max",
            "gg_max_hybrid",
            "gg_lex",
            "gg_lex_hybrid",
            "svo",
            "doc_summary",
            "tensor",
        ]
        for mode in modes:
            with self.subTest(mode=mode):
                packet = render_packet(graph, nodes, edges, mode)
                self.assertNotIn("ghost_node_from_old_scan", packet)

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

    def test_policy_can_be_graph_node(self) -> None:
        policy = Policy("P1", "security", "must", ("server/auth/**",), ("security",), "Use constant-time token checks", "Full policy")
        node = policy_to_node(policy)
        self.assertEqual(node.id, "policy_P1")
        self.assertEqual(node.kind, "policy")
        self.assertEqual(node.scope, "server/auth/**")
        self.assertEqual(node.facts, ("Full policy",))

        graph, op = add_policy_node(Graph(), policy)
        self.assertEqual(op.op, "AddNode")
        self.assertIn("policy_P1", graph.nodes)

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

    def test_choose_packet_empirical_alignment(self) -> None:
        # Empirical data: structural packets with edges → gg_max is the token floor.
        self.assertEqual(choose_packet("direct_lookup").packet, "gg_max")
        self.assertEqual(choose_packet("direct_lookup").hops, 1)
        self.assertEqual(choose_packet("reverse_lookup").packet, "gg_max")
        self.assertEqual(choose_packet("reverse_lookup").hops, 1)
        # blast_radius / multi_hop → gg_max 2-hop
        self.assertEqual(choose_packet("blast_radius").hops, 2)
        self.assertEqual(choose_packet("blast_radius").packet, "gg_max")
        self.assertEqual(choose_packet("multi_hop_path").hops, 2)
        self.assertEqual(choose_packet("multi_hop_path").packet, "gg_max")
        # summary → gg_max unless it is explicitly documentation-oriented.
        self.assertEqual(choose_packet("subsystem_summary").packet, "gg_max")
        self.assertEqual(choose_packet("subsystem_summary", "README installation usage").packet, "doc_summary")
        self.assertEqual(choose_packet("doc_summary").packet, "doc_summary")
        # negative/absence probes avoid pulling unrelated edges.
        self.assertEqual(choose_packet("negative_query").hops, 0)
        self.assertEqual(choose_packet("negative_query").packet, "semantic_arrow")
        # unknown → conservative 2-hop gg_max_hybrid
        self.assertEqual(choose_packet("unknown_xyz").hops, 2)
        self.assertEqual(choose_packet("unknown_xyz").packet, "gg_max_hybrid")

    def test_context_plan_unifies_runtime_policy(self) -> None:
        direct = plan_context("direct_lookup", "what does AuthService call")
        self.assertEqual(direct.hops, 1)
        self.assertEqual(direct.direction, "out")
        self.assertEqual(direct.packet, "gg_max")
        self.assertEqual(direct.node_budget, 80)
        self.assertGreaterEqual(direct.anchor_limit, 1)
        self.assertIn("context_plan_v2", direct.planner_version)

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

        refined = refine_packet_for_subgraph(PacketChoice(1, "gg_max", "test"), 0)
        self.assertEqual(refined.packet, "semantic_arrow")
        self.assertEqual(refined.hops, 1)
        unchanged = refine_packet_for_subgraph(PacketChoice(1, "gg_max", "test"), 1)
        self.assertEqual(unchanged.packet, "gg_max")

        graph = sample_graph()
        stats = compute_subgraph_stats(graph, {"N1"}, [])
        self.assertEqual(stats.nodes, 1)
        self.assertEqual(stats.edges, 0)
        self.assertLessEqual(stats.estimated_tokens_by_packet["semantic_arrow"], stats.estimated_tokens_by_packet["gg_max"])

        summary_graph = Graph(
            nodes={
                "A": Node("A", "Alpha", facts=("handles auth",)),
                "B": Node("B", "Beta", summary="stores tokens"),
            },
            edges=[Edge("A", "B", "calls")],
        )
        summary_stats = compute_subgraph_stats(summary_graph, {"A", "B"}, summary_graph.edges)
        summary_plan = refine_plan_for_subgraph(plan_context("subsystem_summary", "auth subsystem"), summary_stats)
        self.assertEqual(summary_plan.packet, "gg_max")

    def test_calibrated_token_surface_preserves_packet_cliff(self) -> None:
        from graphgraph.planning import estimate_packet_tokens

        zero_edge = estimate_packet_tokens(2, 0)
        self.assertLessEqual(zero_edge["semantic_arrow"], zero_edge["gg_max"])

        structural = estimate_packet_tokens(20, 10)
        self.assertLess(structural["gg_max"], structural["semantic_arrow"])
        self.assertLess(structural["gg_max"], structural["sql"])

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
        # tau = 1.496 + 6.215*1.106664 = 8.37391676
        # n* = (1/0.075) * ln(max(1.1, 0.075/(1e-4*8.37391676))) = 60
        self.assertEqual(recommendation.recommended_budget, 60)
        self.assertEqual(recommendation.mode, "candidate")
        self.assertEqual(
            recommendation.reason,
            "Regularized budget: n*=60 (lambda=0.075, tau=8.374); "
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
            edges=[
                Edge(f"N{i % 6000}", f"N{(i + 1) % 6000}", "references")
                for i in range(18000)
            ],
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
            edges=[
                Edge("S", f"N{i}", "calls") for i in range(8)
            ],
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

    def test_save_graph_persists_valid_pagerank_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            graph = sample_graph()
            save_graph(graph, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("centrality", raw)
            self.assertIn("pagerank", raw["centrality"])

            loaded = load_graph(path)
            self.assertIsNotNone(loaded._pagerank_cache)
            self.assertEqual(loaded.pagerank(), graph.pagerank())

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


    def test_terms_normalize_concepts_consistently(self) -> None:
        self.assertEqual(term_key("Token Store"), "token store")
        self.assertEqual(term_key("token-store"), "token store")
        self.assertEqual(term_key("TokenStore"), "token store")
        self.assertEqual(concept_id("Token Store"), "concept_token_store")
        self.assertEqual(canonical_concept_label("token store"), "Token Store")


    def test_eval_graph_reports_recall_and_token_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), path)
            results = evaluate_graph(path, [EvalTask("auth service", "blast_radius", expected_nodes=("server/auth.py", "AuthService()"))])
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
                            {
                                "id": "N2",
                                "type": "data",
                                "facts": None
                            }
                        ],
                        "edges": [{
                            "source": "N1",
                            "target": "N2",
                            "relation": "reads",
                            "confidence": 0.75,
                            "provenance": "inferred",
                            "source_location": "server/auth.py:10",
                            "valid_from": "2026-06-01T00:00:00Z",
                        }],
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
                        "nodes": [{"id": "N1", "name": "A", "file_type": "code", "properties": {"description": "summary text"}}],
                        "links": [{"source": "N1", "target": "N1", "relation": "calls"}]
                    }
                ),
                encoding="utf-8"
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
                json.dumps({
                    "nodes": [{"id": "requests_init", "label": "__init__.py", "file_type": "code"}],
                    "edges": [
                        {
                            "source": "requests_init",
                            "target": "urllib3",
                            "relation": "imports",
                            "confidence": "EXTRACTED",
                        }
                    ],
                }),
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
            packet="gg_max",
            node_budget=100,
            anchor_limit=6,
            weak_edge_limit=15,
            min_confidence=0.0,
            reason="test"
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
            query_class="multi_hop_path", hops=40, direction="out", packet="gg_max",
            node_budget=34, anchor_limit=6, weak_edge_limit=100, min_confidence=0.0, reason="test",
        )
        ret_nodes, ret_edges = expand_context(graph, ("N0",), plan)

        kept = {rel: len([e for e in ret_edges if e.type == rel]) for rel in {"calls", "references"}}
        # "calls" is not a limited relation type -- unaffected by any edge budget.
        self.assertEqual(kept["calls"], 29)
        # Retained density = (29+13)/30 = 1.4, engaging the throttle (>1.0 scale-down
        # region relative to the untouched max_nodes//2==17 cap it would otherwise get).
        self.assertEqual(kept["references"], 13)

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

    def test_mcp_plan_context(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "plan_context", "arguments": {"query_class": "blast_radius"}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        self.assertIn('"hops": 2', text)
        self.assertIn('"packet": "gg_max"', text)

    def test_mcp_plan_context_direct_lookup(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "plan_context", "arguments": {"query_class": "direct_lookup"}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        self.assertEqual(data["packet"], "gg_max")
        self.assertEqual(data["hops"], 1)

    def test_mcp_describe_formats(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "describe_formats", "arguments": {}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        formats = [f["format"] for f in data]
        self.assertIn("gg_max", formats)
        self.assertIn("sql", formats)
        self.assertIn("semantic_arrow", formats)

    def test_mcp_describe_ontology(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 31, "method": "tools/call", "params": {"name": "describe_ontology", "arguments": {"family": "execution"}}})
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(data[0]["name"], "calls")
        self.assertEqual(data[0]["family"], "execution")

    def test_frontend_capabilities(self) -> None:
        caps = available_frontends()
        names = {cap.name for cap in caps}
        self.assertIn("regex", names)
        self.assertIn("tree_sitter", names)
        self.assertTrue(next(cap for cap in caps if cap.name == "regex").available)

    def test_regex_extractor_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("def helper(): pass\n", encoding="utf-8")
            result = RegexExtractor().extract_symbols(
                [SourceFile(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))],
                max_total_symbols=10,
            )
            self.assertEqual(result.frontend, "regex")
            self.assertTrue(any(node.label == "helper" for node in result.nodes.values()))

    def test_select_extractor_regex_forced(self) -> None:
        self.assertIsInstance(select_extractor("regex"), RegexExtractor)

    def test_select_extractor_tree_sitter_requires_dependency(self) -> None:
        if not tree_sitter_available():
            with self.assertRaises(RuntimeError):
                select_extractor("tree_sitter")

    def test_tree_sitter_extractor_captures_rust_trait_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = (
                "pub trait ExprVisitor {\n"
                "    fn visit_expr(&mut self, expr: &Expr);\n"
                "    fn visit_condition(&mut self, c: &Condition) -> bool;\n"
                "}\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "lib.rs", "lib_rs", text)],
                max_total_symbols=20,
            )
            labels = {node.label for node in result.nodes.values()}
            self.assertIn("ExprVisitor", labels)
            self.assertIn("visit_expr", labels)
            self.assertIn("visit_condition", labels)
            trait_id = next(nid for nid, node in result.nodes.items() if node.label == "ExprVisitor")
            method_ids = {nid for nid, node in result.nodes.items() if node.label in {"visit_expr", "visit_condition"}}
            nested = {(edge.source, edge.target, edge.type) for edge in result.edges}
            self.assertTrue(all((trait_id, method_id, "contains") in nested for method_id in method_ids))

    def test_tree_sitter_extractor_captures_rust_fields_and_returns(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = (
                "pub struct Point { pub x: f64, y: f64 }\n"
                "pub fn make() -> Point { Point { x: 0.0, y: 0.0 } }\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "lib.rs", "lib_rs", text)],
                max_total_symbols=20,
            )
            labels = {node.label for node in result.nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("x", labels)
            self.assertIn("y", labels)
            point_id = next(nid for nid, node in result.nodes.items() if node.label == "Point")
            make_id = next(nid for nid, node in result.nodes.items() if node.label == "make")
            self.assertTrue(any(edge.type == "field_of" and edge.target == point_id for edge in result.edges))
            self.assertTrue(any(edge.type == "returns" and edge.source == make_id and edge.target == point_id for edge in result.edges))

    def test_collect_files_include_overrides_default_skip(self) -> None:
        from graphgraph.scanner.files import collect_files, find_pruned_dirs
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "game" / "build").mkdir(parents=True)
            (root / "game" / "build" / "README.md").write_text("# guide", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

            # By default, a directory named 'build' is skipped.
            default = {p.relative_to(root).as_posix() for p in collect_files(root, 100)}
            self.assertNotIn("game/build/README.md", default)
            # find_pruned_dirs reports it (not silent).
            self.assertIn("build", find_pruned_dirs(root, frozenset({"build"})))
            # --include build keeps it.
            included = {p.relative_to(root).as_posix() for p in collect_files(root, 100, include=frozenset({"build"}))}
            self.assertIn("game/build/README.md", included)

    def test_collect_files_ignores_skip_listed_ancestor_directory_names(self) -> None:
        # Regression: the skip check used to compare against path.parts (the
        # *absolute* path), so a project checked out under e.g. ~/repos/foo
        # or /tmp/anything -- both "repos" and "tmp" are skip-listed dir
        # names -- silently yielded zero files with no warning, since every
        # file's absolute path contains the skip-listed ancestor component.
        from graphgraph.scanner.files import collect_files
        with tempfile.TemporaryDirectory() as tmp:
            # "repos" is in SKIP_DIRS; put it as an *ancestor* of root, not a
            # subdirectory being scanned.
            root = Path(tmp) / "repos" / "myproject"
            root.mkdir(parents=True)
            (root / "main.py").write_text("def foo(): pass\n", encoding="utf-8")
            files = {p.relative_to(root).as_posix() for p in collect_files(root, 100)}
            self.assertIn("main.py", files)

    def test_tree_sitter_extractor_captures_csharp_class_and_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "RecipeResolver.cs"
            text = (
                "namespace Game.Resolvers {\n"
                "  public class RecipeResolver : IRecipeCanon {\n"
                "    public RecipeResolver() {}\n"
                "    public Recipe Resolve(string id) { return null; }\n"
                "  }\n"
                "  public struct RecipeRecord { public int Id; }\n"
                "  public enum RecipeKind { Weapon, Armor }\n"
                "  public interface IRecipeCanon { }\n"
                "}\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "RecipeResolver.cs", "RecipeResolver_cs", text)],
                max_total_symbols=50,
            )
            by_label = {node.label: node for node in result.nodes.values()}
            self.assertIn("RecipeResolver", by_label)
            self.assertEqual(by_label["RecipeResolver"].kind, "class")
            self.assertEqual(by_label["Resolve"].kind, "method")
            self.assertEqual(by_label["RecipeRecord"].kind, "struct")
            self.assertEqual(by_label["RecipeKind"].kind, "enum")
            self.assertEqual(by_label["IRecipeCanon"].kind, "interface")
            # Method should be nested under the class via a contains edge.
            class_id = next(nid for nid, n in result.nodes.items() if n.label == "RecipeResolver" and n.kind == "class")
            resolve_id = next(nid for nid, n in result.nodes.items() if n.label == "Resolve")
            nested = {(edge.source, edge.target, edge.type) for edge in result.edges}
            self.assertIn((class_id, resolve_id, "contains"), nested)

    def test_tree_sitter_resolves_cross_file_calls_csharp_and_java(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "csharp": {
                "RecipeResolver.cs": "namespace G { public class RecipeResolver {\n  public int Resolve(string id) { return Compute(id); }\n} }\n",
                "CombatResolver.cs": "namespace G { public class CombatResolver {\n  public int Compute(string id) { return 7; }\n} }\n",
                "expect": ("Resolve", "Compute"),
            },
            "java": {
                "A.java": "class A { int run(){ return help(); } }\n",
                "B.java": "class B { int help(){ return 1; } }\n",
                "expect": ("run", "help"),
            },
        }
        for _lang, spec in cases.items():
            expect = spec.pop("expect")
            with tempfile.TemporaryDirectory() as tmp:
                srcs = []
                for name, text in spec.items():
                    f = Path(tmp) / name
                    f.write_text(text, encoding="utf-8")
                    srcs.append(SourceFile(f, name, name.replace(".", "_"), text))
                result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
                calls = {(result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"}
                self.assertIn(expect, calls, f"missing cross-file call edge {expect}; got {calls}")

    def test_tree_sitter_does_not_link_calls_across_languages(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via a real-world scan where a Rust function's call
        # to a std-library-style helper resolved to an unrelated C function of
        # the same name in vendored test fixtures purely because it was the
        # only "count" definition in the whole repo -- producing a nonsensical
        # Rust-calls-C edge (`_add_tree_sitter_calls` in frontends.py).
        rs_text = "pub fn examine() -> i32 { count() }\n"
        c_text = "int count(void) { return 1; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            rs = Path(tmp) / "shape.rs"
            rs.write_text(rs_text, encoding="utf-8")
            c = Path(tmp) / "vendor" / "common.h"
            c.parent.mkdir(parents=True, exist_ok=True)
            c.write_text(c_text, encoding="utf-8")
            srcs = [
                SourceFile(rs, "shape.rs", "shape_rs", rs_text),
                SourceFile(c, "vendor/common.h", "vendor_common_h", c_text),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {(result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"}
            self.assertNotIn(("examine", "count"), calls, f"found Rust->C cross-language call edge: {calls}")

    def test_tree_sitter_does_not_link_qualified_method_calls_to_free_functions(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via a real-world scan where `order.splice(...)`
        # (a receiver.method(...) call -- here Vec::splice, a stdlib method)
        # resolved to an unrelated private free function `fn splice(...)`
        # elsewhere in the same crate, purely because "splice" was the only
        # definition with that name in the repo. Resolving a qualified call
        # needs the receiver's type, which this heuristic extractor doesn't
        # have -- same bug class as the cross-language case above, but
        # same-language/same-crate, so the language-family guard alone
        # doesn't catch it (`_add_tree_sitter_calls` in frontends.py).
        rs_text_a = (
            "fn validate_schedule(order: &mut Vec<i32>) {\n"
            "    let pos = 0;\n"
            "    order.splice(pos..=pos, [1, 2, 3]);\n"
            "}\n"
        )
        rs_text_b = "fn splice(x: i32) -> i32 {\n    x + 1\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "schedule_legality.rs"
            a.write_text(rs_text_a, encoding="utf-8")
            b = Path(tmp) / "evolution.rs"
            b.write_text(rs_text_b, encoding="utf-8")
            srcs = [
                SourceFile(a, "schedule_legality.rs", "schedule_legality_rs", rs_text_a),
                SourceFile(b, "evolution.rs", "evolution_rs", rs_text_b),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {(result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"}
            self.assertNotIn(
                ("validate_schedule", "splice"), calls,
                f"found qualified-call-to-unrelated-free-function edge: {calls}",
            )

        # But a bare (unqualified) call to a globally-unique free function
        # must still resolve -- the fix must not break the common case.
        rs_text_c = "fn caller() -> i32 {\n    helper()\n}\n"
        rs_text_d = "fn helper() -> i32 {\n    1\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "c.rs"
            c.write_text(rs_text_c, encoding="utf-8")
            d = Path(tmp) / "d.rs"
            d.write_text(rs_text_d, encoding="utf-8")
            srcs = [
                SourceFile(c, "c.rs", "c_rs", rs_text_c),
                SourceFile(d, "d.rs", "d_rs", rs_text_d),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {(result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"}
            self.assertIn(("caller", "helper"), calls, f"bare unqualified call should still resolve: {calls}")

    def test_tree_sitter_extractor_captures_additional_languages(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "svc.rb": ("class RecipeResolver\n  def resolve(id)\n    1\n  end\nend\n", "RecipeResolver", "resolve"),
            "svc.php": ("<?php\nclass RecipeResolver { public function resolve($id){return 1;} }\n", "RecipeResolver", "resolve"),
            "Svc.kt": ("class RecipeResolver { fun resolve(id: String): Int { return 1 } }\n", "RecipeResolver", "resolve"),
            "Svc.scala": ("class RecipeResolver { def resolve(id: String): Int = 1 }\n", "RecipeResolver", "resolve"),
            "Svc.swift": ("class RecipeResolver { func resolve(_ id: String) -> Int { return 1 } }\n", "RecipeResolver", "resolve"),
        }
        for fname, (text, type_name, member) in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / fname
                f.write_text(text, encoding="utf-8")
                result = select_extractor("tree_sitter").extract_symbols(
                    [SourceFile(f, fname, fname.replace(".", "_"), text)],
                    max_total_symbols=50,
                )
                labels = {node.label for node in result.nodes.values()}
                self.assertIn(type_name, labels, f"{fname}: missing type node")
                self.assertIn(member, labels, f"{fname}: missing member node")

    def test_imported_symbol_name_extraction(self) -> None:
        rust = "use crate::rules::{compile_rules_slice, RuleRecord};\nuse crate::foo::Bar as Baz;\n"
        py = "from server.auth import AuthService, TokenStore as Store\n"
        ts = "import { createApp, Router as R } from './app';\n"
        self.assertEqual(_imported_symbol_names(".rs", rust), {"compile_rules_slice", "RuleRecord", "Bar"})
        self.assertEqual(_imported_symbol_names(".py", py), {"AuthService", "TokenStore"})
        self.assertEqual(_imported_symbol_names(".ts", ts), {"createApp", "Router"})

    def test_mcp_describe_frontends(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 32, "method": "tools/call", "params": {"name": "describe_frontends", "arguments": {}}})
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("regex", {item["name"] for item in data})

    def test_mcp_describe_traversal(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 33, "method": "tools/call", "params": {"name": "describe_traversal", "arguments": {"query_class": "blast_radius"}}})
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(data["query_class"], "blast_radius")
        self.assertIn("calls", data["preferred_relations"])

    def test_mcp_validate_packet(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_gg_max(graph, nodes, edges)
        response = dispatch({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "validate_packet", "arguments": {"packet": packet}}})
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["format"], "gg_max")

    def test_mcp_search_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph_path.write_text(
                json.dumps({
                    "nodes": [
                        {"id": "N1", "label": "AuthService", "kind": "service", "path": "server/auth.py"},
                        {"id": "N2", "label": "TokenStore", "kind": "data", "path": "server/tokens.py"},
                    ],
                    "edges": [],
                }),
                encoding="utf-8",
            )
            response = dispatch({
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "search_nodes", "arguments": {"query": "auth", "graph_path": str(graph_path)}},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            ids = [m["id"] for m in data["matches"]]
            self.assertIn("N1", ids)
            self.assertNotIn("N2", ids)

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
        doc_nodes = [nid for nid in result.nodes if graph.nodes[nid].kind in {"section", "markdown", "text", "rst", "html"}]
        concept_nodes = [nid for nid in result.nodes if graph.nodes[nid].kind == "concept"]

        self.assertIn("SRC", result.nodes)
        self.assertIn("HELPER", result.nodes)
        self.assertTrue(any(edge.source == "SRC" and edge.target == "HELPER" and edge.type == "calls" for edge in result.edges))
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
            nodes = {
                nid: Node(nid, label, kind, path)
                for nid, label, kind, path in case["nodes"]
            }
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
            self.assertEqual(components.code_only_components, expect["components"]["code_only_components"], case["name"])

    def test_load_eval_tasks_accepts_repo_manifest_shapes(self) -> None:
        from graphgraph.eval import load_eval_tasks

        with tempfile.TemporaryDirectory() as tmp:
            flat = Path(tmp) / "flat.json"
            flat.write_text(
                json.dumps([
                    {
                        "question": "What reaches auth?",
                        "expected_nodes": ["AuthService"],
                        "expected_edges": [["A", "B"], ["B", "C", "calls"]],
                    }
                ]),
                encoding="utf-8",
            )
            nested = Path(tmp) / "nested.json"
            nested.write_text(
                json.dumps({
                    "projects": {
                        "demo": [
                            {
                                "query": "auth blast radius",
                                "query_class": "blast_radius",
                                "expected_nodes": ["AuthService"],
                            }
                        ]
                    }
                }),
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

    def test_render_doc_summary_omits_topology_and_keeps_facts(self) -> None:
        graph = Graph(
            nodes={
                "S": Node("S", "Usage", "section", "README.md", summary="L10", facts=("Run graphgraph scan.",)),
                "C": Node("C", "Usage", "concept"),
            },
            edges=[Edge("S", "C", "discusses")],
        )
        packet = render_doc_summary(graph, {"S", "C"}, graph.edges)
        self.assertIn("[d]", packet)
        self.assertIn("Usage [section] README.md L10", packet)
        self.assertIn("Run graphgraph scan.", packet)
        self.assertNotIn("discusses", packet)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "doc_summary")
        self.assertEqual(result.node_count, 1)

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
        payload = json.dumps({
            "nodes": [{"id": "A", "label": "A"}],
            "edges": [{"source": "A", "target": "B", "type": "calls"}],
        })
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

    def test_cmd_scan_refuses_invalid_graph_without_overwrite(self) -> None:
        from graphgraph.cli.commands import cmd_scan

        class Args:
            directory = "."
            output = ""
            incremental = True
            skip_dirs = []
            exclude_dirs = []
            max_nodes = 2000
            generic_mentions = False
            depth = "symbols"
            frontend = "regex"
            docs = True
            history = False

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            save_graph(sample_graph(), graph_path)
            before = graph_path.read_text(encoding="utf-8")
            bad_graph = Graph(nodes={"A": Node("A", "A")}, edges=[Edge("A", "B", "calls")])
            args = Args()
            args.directory = str(root)
            args.output = str(graph_path)

            with patch("graphgraph.services.native.scan_directory", return_value=bad_graph):
                with self.assertRaisesRegex(ValueError, "Refusing to write invalid graph JSON"):
                    cmd_scan(args)

            self.assertEqual(graph_path.read_text(encoding="utf-8"), before)

    def test_scan_validated_graph_repairs_invalid_incremental_scan(self) -> None:
        from graphgraph.services.native import scan_validated_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            bad_graph = Graph(nodes={"A": Node("A", "A")}, edges=[Edge("A", "B", "calls")])
            clean_graph = sample_graph()

            with patch("graphgraph.services.native.scan_directory", side_effect=[bad_graph, clean_graph]):
                status = scan_validated_graph(directory=root, output_path=graph_path, incremental=True)

            self.assertTrue(status.repaired)
            self.assertTrue(graph_path.exists())
            result = validate_graph_json(graph_path.read_text(encoding="utf-8"))
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.node_count, 3)

    def test_full_scan_manifest_keeps_doc_concept_edge_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# GraphGraph Workspace Rules\n\nUse `graphgraph/query_context` for Project Status.\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(
                root,
                depth="symbols",
                docs=True,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            readme_nodes = manifest["files"]["README.md"]["nodes"]
            self.assertTrue(any(node_id.startswith("concept_") for node_id in readme_nodes))

            graph2 = scan_directory(
                root,
                depth="symbols",
                docs=True,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )
            result = validate_graph_json(graph_to_json(graph2))
            self.assertTrue(result.ok, result.errors)

    def test_update_paths_matches_full_rescan_including_cross_file_calls(self) -> None:
        def build_baseline(root: Path, graph_path: Path, manifest_path: Path) -> Graph:
            (root / "a.py").write_text("def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            (root / "b.py").write_text("def baz():\n    return 2\n", encoding="utf-8")
            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)
            return graph

        with tempfile.TemporaryDirectory() as tmp_full:
            root = Path(tmp_full)
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            build_baseline(root, graph_path, manifest_path)

            # a.py now calls into b.py instead of its own bar().
            (root / "a.py").write_text("def foo():\n    return baz()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            full = scan_directory(root, depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path)
            full_nodes = sorted((n.label, n.path) for n in full.nodes.values())
            full_edges = sorted((e.source, e.target, e.type) for e in full.edges)

        with tempfile.TemporaryDirectory() as tmp_targeted:
            root = Path(tmp_targeted)
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            build_baseline(root, graph_path, manifest_path)

            (root / "a.py").write_text("def foo():\n    return baz()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            targeted = update_paths(root, ["a.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path)
            targeted_nodes = sorted((n.label, n.path) for n in targeted.nodes.values())
            targeted_edges = sorted((e.source, e.target, e.type) for e in targeted.edges)

        self.assertEqual(full_nodes, targeted_nodes)
        self.assertEqual(full_edges, targeted_edges)
        # The cross-file call must actually be present, not just equal-and-empty.
        self.assertIn(("a_py__foo", "b_py__baz", "calls"), targeted_edges)

    def test_update_paths_preserves_concept_edges_for_untouched_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # b.py's function name matches a registered interpretation-layer
            # concept alias, producing an "implements_algorithm" edge.
            (root / "b.py").write_text("def dynamic_programming():\n    return 1\n", encoding="utf-8")
            (root / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)
            concept_edges_before = {
                (e.source, e.target, e.type) for e in graph.edges if e.type == "implements_algorithm"
            }
            self.assertTrue(concept_edges_before, "fixture should produce at least one concept edge")

            # Touch only a.py -- b.py is untouched and must keep its concept
            # edge via manifest restoration, not fresh linking.
            (root / "a.py").write_text("def foo():\n    return 2\n", encoding="utf-8")
            targeted = update_paths(root, ["a.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path)
            concept_edges_after = {
                (e.source, e.target, e.type) for e in targeted.edges if e.type == "implements_algorithm"
            }
            self.assertEqual(concept_edges_before, concept_edges_after)

    def test_update_paths_requires_prior_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                update_paths(
                    root,
                    ["a.py"],
                    previous_graph_path=root / ".graphgraph" / "graph.json",
                    manifest_path=root / ".graphgraph" / "manifest.json",
                )

    def test_update_paths_treats_missing_target_as_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)
            self.assertTrue(any(n.path == "a.py" for n in graph.nodes.values()))

            (root / "a.py").unlink()
            result = update_paths(root, ["a.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path)
            self.assertFalse(any(n.path == "a.py" for n in result.nodes.values()))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("a.py", manifest["files"])

    def test_remove_paths_drops_file_nodes_and_manifest_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            (root / "b.py").write_text("def baz():\n    return 2\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)

            result = remove_paths(root, ["b.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path)
            self.assertFalse(any(n.path == "b.py" for n in result.nodes.values()))
            self.assertTrue(any(n.path == "a.py" for n in result.nodes.values()))
            # a.py's own internal structure survives untouched.
            self.assertIn(("a_py__foo", "a_py__bar", "calls"), {(e.source, e.target, e.type) for e in result.edges})
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("b.py", manifest["files"])
            self.assertIn("a.py", manifest["files"])

    def test_retrieval_anchors_code_identifier_queries(self) -> None:
        graph = Graph(
            nodes={
                "S": Node("S", "What it is", "section", "docs/what.md"),
                "F": Node("F", "compile_rules_slice", "function", "crates/locus-engine/src/rules/compiler.rs"),
                "C": Node("C", "compile_all", "function", "crates/locus-engine/src/rules/compiler.rs"),
            },
            edges=[Edge("C", "F", "calls", provenance="tree_sitter")],
        )
        self.assertEqual(tokenize("what calls compile_rules_slice"), ("calls", "compile_rules_slice", "compile", "rules", "slice"))
        self.assertEqual(
            tokenize("GameSession FastAceEngine cleanup_API"),
            ("gamesession", "game", "session", "fastaceengine", "fast", "ace", "engine", "cleanup_api", "cleanup", "api"),
        )
        matches = search_nodes(graph, "what calls compile_rules_slice", limit=3)
        self.assertEqual(matches[0].node.id, "F")
        result = retrieve_context(graph, "what calls compile_rules_slice", "reverse_lookup", hops=1, max_nodes=5)
        self.assertIn("C", result.nodes)

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
        self.assertEqual(retrieval_node_budget("missing auth service", "negative_query", None), 1)
        self.assertEqual(retrieval_node_budget("matrix transpose orthogonal symmetric square vector rules", "subsystem_summary", 40), 32)
        self.assertEqual(retrieval_node_budget("README installation usage", "subsystem_summary", 40), 12)
        self.assertEqual(retrieval_node_budget("README installation usage", "doc_summary", 40), 12)
        self.assertEqual(retrieval_node_budget("auth service", "blast_radius", 40), 40)

    def test_mcp_query_context_without_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            response = dispatch({
                "jsonrpc": "2.0", "id": 55, "method": "tools/call",
                "params": {"name": "query_context", "arguments": {
                    "query": "auth service",
                    "query_class": "blast_radius",
                    "graph_path": str(graph_path),
                    "show_anchors": True,
                }},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["anchors"][0]["id"], "N1")
            self.assertIn("[e]", data["packet"])

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

    def test_mcp_query_context_honors_hops_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            response = dispatch({
                "jsonrpc": "2.0", "id": 56, "method": "tools/call",
                "params": {"name": "query_context", "arguments": {
                    "query": "auth service",
                    "query_class": "blast_radius",
                    "graph_path": str(graph_path),
                    "hops": 0,
                    "show_anchors": True,
                }},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["anchors"][0]["id"], "N1")
            self.assertIn("AuthService", data["packet"])
            self.assertNotIn("N2: TokenStore", data["packet"])

    def test_render_source_snippets_uses_node_line_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def helper():\n"
                "    return 1\n"
                "\n"
                "def login():\n"
                "    token = helper()\n"
                "    return token\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = Graph(nodes={
                "F": Node("F", "login", "function", "src/auth.py", summary="L4"),
            })
            save_graph(graph, graph_path)

            out = render_source_snippets(starts=["F"], graph_path=graph_path, context_lines=1, max_lines=5)
            self.assertIn("## login (F)", out)
            self.assertIn("src/auth.py:3", out)
            self.assertIn("4 | def login():", out)
            self.assertIn("5 |     token = helper()", out)
            self.assertNotIn("1 | def helper", out)

    def test_render_source_snippets_resolves_package_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "examples" / "multi-router"
            pkg.mkdir(parents=True)
            child = pkg / "index.js"
            child.write_text("function bootstrap() {\n  return true;\n}\n", encoding="utf-8")

            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = Graph(nodes={
                "P": Node("P", "multi-router", "package", "examples/multi-router"),
                "F": Node("F", "bootstrap", "function", "examples/multi-router/index.js", summary="L1"),
            })
            save_graph(graph, graph_path)

            out = render_source_snippets(starts=["P"], graph_path=graph_path, context_lines=0, max_lines=4)
            self.assertIn("## multi-router (P)", out)
            self.assertIn("examples/multi-router/index.js:1", out)
            self.assertIn("1 | function bootstrap()", out)

    def test_mcp_source_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir(parents=True)
            source.write_text("def login():\n    return 'ok'\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            save_graph(Graph(nodes={"F": Node("F", "login", "function", "src/auth.py", summary="L1")}), graph_path)

            response = dispatch({
                "jsonrpc": "2.0", "id": 57, "method": "tools/call",
                "params": {"name": "source_snippets", "arguments": {
                    "graph_path": str(graph_path),
                    "starts": ["login"],
                    "context_lines": 0,
                    "max_lines": 3,
                }},
            })
            assert response is not None
            text = response["result"]["content"][0]["text"]
            self.assertIn("## login (F)", text)
            self.assertIn("1 | def login():", text)

    def test_budget_edges_caps_weak_references(self) -> None:
        edges = [Edge("N1", f"N{i}", "references", 0.5) for i in range(30)]
        edges += [Edge("N1", "N2", "calls", 1.0) for _ in range(3)]
        kept = budget_edges(edges, max_nodes=20)
        self.assertEqual(len([e for e in kept if e.type == "references"]), 10)
        self.assertEqual(len([e for e in kept if e.type == "calls"]), 3)

    def test_budget_edges_shapes_mixed_weak_relations_by_utility(self) -> None:
        edges = [Edge("N1", f"R{i}", "references", confidence=0.9, provenance="regex_reference") for i in range(30)]
        edges += [Edge("N1", f"L{i}", "links", confidence=0.4, provenance="ambiguous") for i in range(30)]
        edges += [Edge("N1", f"M{i}", "mentions", confidence=0.3, provenance="semantic_llm") for i in range(30)]
        edges += [Edge("N1", "Core", "calls", confidence=1.0, provenance="tree_sitter")]

        kept = budget_edges(edges, max_nodes=20)
        kept_counts = {relation: len([edge for edge in kept if edge.type == relation]) for relation in {"references", "links", "mentions", "calls"}}

        self.assertLess(sum(count for relation, count in kept_counts.items() if relation != "calls"), 30)
        self.assertGreater(kept_counts["references"], kept_counts["links"])
        self.assertGreaterEqual(kept_counts["links"], 1)
        self.assertGreaterEqual(kept_counts["mentions"], 1)
        self.assertEqual(kept_counts["calls"], 1)

    def test_budget_edges_shaped_path_exact_quotas(self) -> None:
        edges = [Edge("N1", f"R{i}", "references", 1.0, confidence=0.9, provenance="regex_reference") for i in range(40)]
        edges += [Edge("N1", f"L{i}", "links", 1.0, confidence=0.4, provenance="ambiguous") for i in range(40)]
        edges += [Edge("N1", f"M{i}", "mentions", 1.0, confidence=0.3, provenance="semantic_llm") for i in range(40)]

        kept = budget_edges(edges, max_nodes=30)

        # _weak_edge_target(120,120,max_nodes=30,weak_limit=None):
        #   density=120/30=4.0; density_scale=1/sqrt(4.0)=0.5
        #   base=max(8,round(30*0.55*0.5))=max(8,8)=8; target=max(4,min(120,8))=8
        kept_counts = {rel: len([e for e in kept if e.type == rel]) for rel in {"references", "links", "mentions"}}
        self.assertEqual(sum(kept_counts.values()), 8)
        # _relation_quotas splits target=8 by sqrt(count)*strength*avg_utility across relations.
        self.assertEqual(kept_counts, {"references": 4, "links": 2, "mentions": 2})

        # Ties within a relation (identical confidence/provenance/weight) break by
        # (source, target) ascending string sort -- pins the tie-break behavior too.
        kept_refs = sorted((e.source, e.target) for e in kept if e.type == "references")
        self.assertEqual(kept_refs, [("N1", "R0"), ("N1", "R1"), ("N1", "R10"), ("N1", "R11")])

    def test_relation_ontology_drives_traversal_and_weak_budgeting(self) -> None:
        self.assertEqual(relation_spec("calls").family, "execution")
        self.assertEqual(relation_spec("explains").family, "document")
        self.assertGreater(traversal_strength("calls"), traversal_strength("references"))
        self.assertGreater(traversal_strength("references"), traversal_strength("section_of"))
        self.assertGreater(traversal_strength("explains"), traversal_strength("section_of"))
        self.assertGreater(provenance_confidence("tree_sitter"), provenance_confidence("regex_reference"))
        edges = [Edge("N1", f"N{i}", "unknown_relation", 0.5) for i in range(30)]
        kept = budget_edges(edges)
        self.assertEqual(len(kept), 12)

    def test_traversal_policy_is_query_class_specific(self) -> None:
        blast = traversal_policy("blast_radius")
        summary = traversal_policy("subsystem_summary")
        direct = traversal_policy("direct_lookup")
        reverse = traversal_policy("reverse_lookup")
        self.assertIn("tests", blast.preferred_relations)
        self.assertIn("contains", summary.preferred_relations)
        self.assertLess(relation_rank("calls", blast), relation_rank("references", blast))
        self.assertEqual(direct.direction, "out")
        self.assertEqual(reverse.direction, "in")

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

    def test_mcp_build_graph_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a small Python package
            (root / "main.py").write_text("from utils import helper\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            output = root / "graph.json"
            response = dispatch({
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "build_graph", "arguments": {
                    "directory": str(root),
                    "output_path": str(output),
                }},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["action"], "scanned")
            self.assertGreaterEqual(data["nodes"], 2)
            self.assertTrue(output.exists())

    def test_scanner_detects_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("from db import connect\nfrom utils import helper\n", encoding="utf-8")
            (root / "db.py").write_text("def connect(): pass\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 3)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.label == "utils.py")
            self.assertIn((app_id, db_id), edge_pairs)
            self.assertIn((app_id, utils_id), edge_pairs)

    def test_scanner_detects_python_multiline_parenthesized_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "from db import (\n    connect,\n    disconnect as close\n)\n",
                encoding="utf-8"
            )
            (root / "db.py").write_text("def connect(): pass\ndef disconnect(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            self.assertIn((app_id, db_id), edge_pairs)

    def test_scanner_detects_python_relative_imports_and_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "pkg"
            sub = pkg / "sub"
            sub.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (sub / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "core.py").write_text("def connect(): pass\n", encoding="utf-8")
            (pkg / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            (sub / "worker.py").write_text(
                "from ..core import connect\nfrom . import local\nimport pkg.utils as utils\n",
                encoding="utf-8",
            )
            (sub / "local.py").write_text("def local(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            edge_pairs = {(e.source, e.target, e.type) for e in graph.edges}
            worker_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/sub/worker.py")
            core_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/core.py")
            local_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/sub/local.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/utils.py")

            self.assertIn((worker_id, core_id, "imports"), edge_pairs)
            self.assertIn((worker_id, local_id, "imports"), edge_pairs)
            self.assertIn((worker_id, utils_id, "imports"), edge_pairs)
            self.assertTrue(any(e.type == "contains" and e.target == worker_id for e in graph.edges))

    def test_scanner_skips_pycache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"")
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root)
            for node in graph.nodes.values():
                self.assertNotIn("__pycache__", node.path)
            self.assertEqual(len(graph.nodes), 1)

    def test_scanner_max_nodes_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10):
                (root / f"mod_{i}.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root, max_nodes=5)
            self.assertLessEqual(len(graph.nodes), 5)

    def test_scanner_skips_tmp_directories_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tmp").mkdir()
            (root / "evidence").mkdir()
            (root / "artifacts").mkdir()
            (root / "graphify-out").mkdir()
            (root / ".code-review-graph").mkdir()
            (root / "src" / "app.py").write_text("def run(): pass\n", encoding="utf-8")
            (root / "tmp" / "vendored.lean").write_text("def noisy := 1\n", encoding="utf-8")
            (root / "evidence" / "status.md").write_text("# Old generated answer\n", encoding="utf-8")
            (root / "artifacts" / "report.py").write_text("def generated(): pass\n", encoding="utf-8")
            (root / "graphify-out" / "graph.json").write_text('{"nodes":[],"edges":[]}\n', encoding="utf-8")
            (root / ".code-review-graph" / "graph.json").write_text('{"nodes":[],"edges":[]}\n', encoding="utf-8")

            graph = scan_directory(root, depth="symbols")
            paths = {node.path for node in graph.nodes.values()}
            self.assertIn("src/app.py", paths)
            self.assertNotIn("tmp/vendored.lean", paths)
            self.assertNotIn("evidence/status.md", paths)
            self.assertNotIn("artifacts/report.py", paths)
            self.assertNotIn("graphify-out/graph.json", paths)
            self.assertNotIn(".code-review-graph/graph.json", paths)

    def test_python_module_cli_entrypoint_runs(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "graphgraph.cli", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("graphgraph", proc.stdout)

    def test_native_context_builds_graph_and_skips_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "evidence").mkdir()
            (root / "src" / "app.py").write_text("def run_context():\n    return 'ok'\n", encoding="utf-8")
            (root / "evidence" / "old_status.md").write_text("# Generated status\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"

            packet, status = render_native_context(
                query="run context",
                directory=root,
                graph_path=graph_path,
                rebuild=False,
                query_class="direct_lookup",
                max_nodes=20,
            )

            self.assertTrue(status.built)
            self.assertTrue(graph_path.exists())
            self.assertIn("run_context", packet)
            paths = {node.path for node in status.graph.nodes.values()}
            self.assertIn("src/app.py", paths)
            self.assertNotIn("evidence/old_status.md", paths)
            shape = graph_shape(status.graph)
            self.assertGreaterEqual(shape["source_nodes"], 1)

            packet2, status2 = render_native_context(
                query="run context",
                directory=root,
                graph_path=graph_path,
                rebuild=False,
                query_class="direct_lookup",
                max_nodes=20,
            )
            self.assertFalse(status2.built)
            self.assertEqual(packet2, packet)

            (root / "src" / "app.py").write_text("def run_context_clean():\n    return 'ok'\n", encoding="utf-8")
            packet3, status3 = render_native_context(
                query="run context clean",
                directory=root,
                graph_path=graph_path,
                rebuild=True,
                query_class="direct_lookup",
                max_nodes=20,
            )
            self.assertTrue(status3.built)
            self.assertIn("run_context_clean", packet3)
            self.assertNotIn("run_context():", packet3)

    def test_project_status_reports_validation_package_and_runtime_hint(self) -> None:
        from graphgraph.services.native import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "featherwaight").mkdir(parents=True)
            (root / "src" / "featherwaight" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\n"
                "name = \"featherwaight\"\n"
                "version = \"0.1.0\"\n"
                "[project.scripts]\n"
                "featherwaight = \"featherwaight.cli:main\"\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(Graph(nodes={"P": Node("P", "package", "python", "src/featherwaight/__init__.py")}), graph_path)

            report = build_project_status(directory=root, graph_path=graph_path, run_probes=True)

            self.assertTrue(report["graph"]["validation"]["ok"])
            self.assertEqual(report["package"]["name"], "featherwaight")
            self.assertEqual(report["package"]["module"], "featherwaight")
            self.assertTrue(report["package"]["src_layout"])
            self.assertIn("PYTHONPATH=src", report["package"]["import_hint"])
            probes = {probe["name"]: probe for probe in report["runtime_probes"]}
            self.assertFalse(probes["raw_import"]["ok"])
            self.assertTrue(probes["src_import"]["ok"])
            self.assertIn("script_target_import:featherwaight", probes)
            self.assertFalse(probes["raw_module_help"]["ok"])
            self.assertTrue(any("PYTHONPATH includes src" in note for note in report["runtime_notes"]))

    def test_mcp_project_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(sample_graph(), graph_path)
            response = dispatch({
                "jsonrpc": "2.0", "id": 16, "method": "tools/call",
                "params": {"name": "project_status", "arguments": {
                    "directory": str(root),
                    "graph_path": str(graph_path),
                }},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(data["graph"]["validation"]["ok"])
            self.assertEqual(data["graph"]["shape"]["nodes"], 3)

    def test_scanner_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.md").write_text("See [guide](./guide.md) for details.\n", encoding="utf-8")
            (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("links", edge_types)

    def test_document_context_extracts_sections_and_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "README.md"
            doc.write_text("# Auth System\n\nThe **Token Store** calls `AuthService`.\n", encoding="utf-8")
            file_map = {"README.md": "README_md", "auth.py": "auth_py"}
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "README.md", "README_md", doc.read_text(encoding="utf-8"))],
                file_map,
            )
            kinds = {node.kind for node in nodes.values()}
            edge_types = {edge.type for edge in edges}
            self.assertIn("section", kinds)
            self.assertIn("concept", kinds)
            self.assertIn("section_of", edge_types)
            self.assertIn("discusses", edge_types)
            self.assertEqual(
                relation_spec("explains").description,
                "Source text explains target concept or implementation detail.",
            )
            section = next(node for node in nodes.values() if node.kind == "section")
            self.assertTrue(section.facts)

    def test_document_context_normalizes_duplicate_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "README.md"
            doc.write_text("# Concepts\n\nThe **Token Store** relates to `token-store` and Token Store.\n", encoding="utf-8")
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "README.md", "README_md", doc.read_text(encoding="utf-8"))],
                {"README.md": "README_md"},
            )
            token_nodes = [node for node in nodes.values() if node.kind == "concept" and term_key(node.label) == "token store"]
            self.assertEqual(len(token_nodes), 1)
            discusses = [edge for edge in edges if edge.type == "discusses" and edge.target == token_nodes[0].id]
            self.assertEqual(len(discusses), 1)

    def test_scanner_docs_flag_adds_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Runtime Context Graph\n\nDocuments mention AuthService.\n", encoding="utf-8")
            graph = scan_directory(root, docs=True)
            self.assertEqual(graph.metadata["docs"], "true")
            self.assertIn("section", {node.kind for node in graph.nodes.values()})
            self.assertIn("concept", {node.kind for node in graph.nodes.values()})

    def test_scanner_docs_flag_links_symbols_to_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# API\n\nThe `render_packet` helper is used here.\n", encoding="utf-8")
            (root / "render.py").write_text("def render_packet():\n    return None\n", encoding="utf-8")
            graph = scan_directory(root, docs=True, depth="symbols", frontend="regex")
            edge_types = {e.type for e in graph.edges}
            self.assertIn("explains", edge_types)
            self.assertTrue(any(edge.type == "explains" for edge in graph.edges))

    def test_history_bugfix_and_maintenance_classification(self) -> None:
        from graphgraph.scanner.history import _is_bugfix_commit

        # Clear bug fix -> included.
        self.assertTrue(_is_bugfix_commit(
            "fix: cast scanner facts list to tuple to match Node dataclass typing"
        ))
        # Maintenance-only -> excluded (no bugfix keyword at all).
        self.assertFalse(_is_bugfix_commit(
            "chore: remove temporary web search lookup capabilities"
        ))
        # Contains a bugfix keyword AND a maintenance keyword -> excluded by the AND-NOT rule.
        self.assertFalse(_is_bugfix_commit(
            "style: fix ruff lint errors in scanner module"
        ))
        # Neutral feature commit -> excluded (no bugfix keyword).
        self.assertFalse(_is_bugfix_commit(
            "feat: add packet renderer for hybrid format"
        ))

    def test_history_parse_commit_log_output(self) -> None:
        from graphgraph.scanner.history import _parse_commit_log_output

        raw = (
            "COMMIT abc1234567890\x1ffix: handle empty file list\n"
            "2\t1\tsrc/graphgraph/scanner/core.py\n"
            "0\t3\tsrc/graphgraph/scanner/files.py\n"
            "\n"
            "COMMIT def4567890abc\x1fchore: bump dependency versions\n"
            "1\t1\tpyproject.toml\n"
        )
        records = _parse_commit_log_output(raw)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].sha, "abc1234567890")
        self.assertEqual(records[0].subject, "fix: handle empty file list")
        self.assertEqual(
            records[0].files,
            ("src/graphgraph/scanner/core.py", "src/graphgraph/scanner/files.py"),
        )
        self.assertEqual(records[1].files, ("pyproject.toml",))

    def test_history_skips_wide_commits_above_file_cap(self) -> None:
        # Found via real-data validation against this repo's own history: a large
        # refactor commit that happened to mention "fix" touched 84 files and would
        # otherwise become an artificially high-degree hub node.
        from graphgraph.scanner.history import extract_commit_history

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()

            def fake_run(*args, **kwargs):
                class _Result:
                    returncode = 0
                    stdout = (
                        "COMMIT wide0000001\x1frefactor codebase, fix imports along the way\n"
                        + "".join(f"1\t0\tfile{i}.py\n" for i in range(25))
                        + "\nCOMMIT narrow000001\x1ffix: off-by-one in loop\n"
                        "1\t0\tfile0.py\n"
                    )
                return _Result()

            file_map = {f"file{i}.py": f"file_{i}" for i in range(25)}
            with patch("graphgraph.scanner.history.subprocess.run", side_effect=fake_run):
                nodes, edges = extract_commit_history(root, file_map, max_files_per_commit=20)

            self.assertNotIn("commit_wide0000", nodes)
            self.assertIn("commit_narrow00", nodes)
            self.assertEqual(len(edges), 1)

    @unittest.skipUnless(shutil.which("git"), "git binary not available on PATH")
    def test_history_real_git_repo_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")

            (root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "feat: initial commit")

            (root / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "fix: correct add() returning subtraction result")

            (root / "app.py").write_text(
                "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
                encoding="utf-8",
            )
            run_git("add", ".")
            run_git("commit", "-q", "-m", "style: reformat with black")

            (root / "README.md").write_text("# demo\n\nUsage docs.\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "docs: add usage section")

            graph = scan_directory(root, depth="files", history=True)

            commit_nodes = {n.id: n for n in graph.nodes.values() if n.kind == "commit"}
            self.assertEqual(len(commit_nodes), 1, commit_nodes)
            commit_node = next(iter(commit_nodes.values()))
            self.assertIn("correct add()", commit_node.summary)

            fixes_edges = [e for e in graph.edges if e.type == "fixes"]
            self.assertEqual(len(fixes_edges), 1)
            app_file_node = next(n for n in graph.nodes.values() if n.path == "app.py")
            self.assertEqual(fixes_edges[0].source, commit_node.id)
            self.assertEqual(fixes_edges[0].target, app_file_node.id)

    def test_scanner_c_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.c").write_text('#include "utils.h"\nint main(){}\n', encoding="utf-8")
            (root / "utils.h").write_text("void helper();\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)
            self.assertEqual(graph.edges[0].type, "imports")

    def test_scanner_rust_mod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rs").write_text("mod utils;\nfn main(){}\n", encoding="utf-8")
            (root / "utils.rs").write_text("pub fn helper(){}\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)

    def test_scanner_go_relative_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text('import "./pkg"\nfunc main(){}\n', encoding="utf-8")
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "pkg.go").write_text("package pkg\n", encoding="utf-8")
            graph = scan_directory(root)
            # main.go and pkg/pkg.go should be nodes
            self.assertGreaterEqual(len(graph.nodes), 2)

    def test_scanner_generic_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.txt").write_text("See the config module for settings.\n", encoding="utf-8")
            (root / "config.py").write_text("# config\n", encoding="utf-8")
            graph = scan_directory(root, generic_mentions=True)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("references", edge_types)

    def test_scanner_html_href(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text('<a href="./about.html">About</a>\n', encoding="utf-8")
            (root / "about.html").write_text("<h1>About</h1>\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertTrue(any(e.type == "links" for e in graph.edges))

    def test_scanner_depth_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "class Server:\n    def handle(self):\n        pass\n\ndef run():\n    pass\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            self.assertEqual(graph.metadata["scan_depth"], "symbols")
            self.assertIn(graph.metadata["frontend"], {"regex", "tree_sitter"})
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)
            contains_edges = [e for e in graph.edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains_edges), 2)

    def test_scanner_depth_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib.rs").write_text(
                "pub struct Config { pub name: String }\npub fn load() -> Config { todo!() }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("struct", kinds)
            self.assertIn("function", kinds)

    def test_scanner_depth_symbols_cross_file_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_text(
                "def handle_request(config):\n    return config\n",
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                "from server import handle_request\nhandle_request(None)\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            ref_edges = [e for e in graph.edges if e.type == "references"]
            self.assertGreaterEqual(len(ref_edges), 1)

    def test_scanner_depth_symbols_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.js").write_text(
                "class Router {}\nexport function createApp() { return new Router(); }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)

    def test_extract_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("class Foo:\n    def bar(self): baz()\n\ndef baz(): pass\n", encoding="utf-8")
            tuples = [(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))]
            nodes, edges = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Foo", labels)
            self.assertIn("baz", labels)
            contains = [e for e in edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains), 2)
            calls = [e for e in edges if e.type == "calls"]
            self.assertGreaterEqual(len(calls), 1)

    def test_extract_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            f.write_text(
                "pub trait Metric {}\n"
                "pub struct Point { x: i32 }\n"
                "impl Metric for Point {}\n"
                "pub fn norm() -> f64 { 0.0 }\n"
                "pub fn distance(a: Point) -> f64 { norm() }\n",
                encoding="utf-8",
            )
            tuples = [(f, "lib.rs", "lib_rs", f.read_text(encoding="utf-8"))]
            nodes, edges = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("distance", labels)
            self.assertTrue(any(e.type == "calls" for e in edges))
            self.assertTrue(any(e.type == "implements" for e in edges))

    def test_extract_symbols_does_not_link_calls_across_languages(self) -> None:
        # Regression: a Rust call site invoking a std-library-style method
        # (e.g. `.as_deref()`) must not resolve to an unrelated Python function
        # of the same name elsewhere in the repo -- found via a real cross-repo
        # scan where `crates/.../algorithm_shape.rs::examine` calls into
        # `Option::as_deref()` and a vendored numpy test fixture happened to
        # define an unrelated `def as_deref(expr):` at module scope, producing
        # a nonsensical Rust-calls-Python edge purely from name collision.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rs = root / "shape.rs"
            rs.write_text(
                "pub fn examine(x: Option<String>) -> Option<&str> { x.as_deref() }\n",
                encoding="utf-8",
            )
            py = root / "vendor" / "symbolic.py"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("def as_deref(expr):\n    return expr\n", encoding="utf-8")
            tuples = [
                (rs, "shape.rs", "shape_rs", rs.read_text(encoding="utf-8")),
                (py, "vendor/symbolic.py", "vendor_symbolic_py", py.read_text(encoding="utf-8")),
            ]
            nodes, edges = extract_symbols(tuples)
            self.assertIn("examine", {n.label for n in nodes.values()})
            self.assertIn("as_deref", {n.label for n in nodes.values()})
            cross_lang = [
                e
                for e in edges
                if e.type in ("calls", "references") and e.target == "vendor_symbolic_py__as_deref"
            ]
            self.assertEqual(
                [], cross_lang, f"found Rust<->Python cross-language edges: {cross_lang}"
            )

    # --- .gg roundtrip tests ---

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
        from graphgraph.eval import ndcg_at_k, reciprocal_rank
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
        from graphgraph.eval import rank_nodes_by_subgraph_pagerank
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

    # --- CSV ingest tests ---

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

    # --- render_svo tests ---

    def test_render_svo_basic(self) -> None:
        g = sample_graph()
        nodes = set(g.nodes.keys())
        packet = render_svo(g, nodes, g.edges)
        self.assertIn("AuthService", packet)
        self.assertIn("-reads->", packet)
        self.assertIn("TokenStore", packet)

    def test_render_svo_omits_weight_when_one(self) -> None:
        g = Graph(
            nodes={"A": Node("A", "Alpha", "file", ""), "B": Node("B", "Beta", "file", "")},
            edges=[Edge("A", "B", "imports", 1.0)],
        )
        packet = render_svo(g, set(g.nodes.keys()), g.edges)
        self.assertNotIn("(1", packet)
        self.assertIn("Alpha -imports-> Beta", packet)

    def test_render_svo_includes_weight_when_not_one(self) -> None:
        g = Graph(
            nodes={"A": Node("A", "Alpha", "file", ""), "B": Node("B", "Beta", "file", "")},
            edges=[Edge("A", "B", "calls", 0.75)],
        )
        packet = render_svo(g, set(g.nodes.keys()), g.edges)
        self.assertIn("(0.75)", packet)

    def test_render_svo_empty_edges(self) -> None:
        g = sample_graph()
        packet = render_svo(g, set(g.nodes.keys()), [])
        self.assertEqual(packet, "")
    def test_incremental_scanner_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            
            # Setup files
            a_file = root / "a.py"
            b_file = root / "b.py"
            a_file.write_text("import b", encoding="utf-8")
            b_file.write_text("# clean file", encoding="utf-8")
            
            gg_dir = root / ".graphgraph"
            gg_dir.mkdir(parents=True, exist_ok=True)
            graph_path = gg_dir / "graph.json"
            manifest_path = gg_dir / "manifest.json"
            
            # Step 1: Initial full scan
            graph = scan_directory(
                root,
                depth="files",
                previous_graph_path=graph_path,
                manifest_path=manifest_path
            )
            save_graph(graph, graph_path)
            
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)
            
            # Verify manifest was created and populated
            self.assertTrue(manifest_path.exists())
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("a.py", manifest_data["files"])
            self.assertIn("b.py", manifest_data["files"])
            b_orig_hash = manifest_data["files"]["b.py"]["hash"]
            
            # Step 2: Modify a.py, add c.py (b.py remains unchanged)
            a_file.write_text("import b\nimport c", encoding="utf-8")
            c_file = root / "c.py"
            c_file.write_text("# new file", encoding="utf-8")
            
            # Scan incrementally
            graph2 = scan_directory(
                root,
                depth="files",
                previous_graph_path=graph_path,
                manifest_path=manifest_path
            )
            save_graph(graph2, graph_path)
            
            # Verify all nodes/edges are updated/reconstructed
            self.assertEqual(len(graph2.nodes), 3)
            self.assertEqual(len(graph2.edges), 2)
            
            # Check manifest update
            manifest_data2 = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("c.py", manifest_data2["files"])
            self.assertEqual(manifest_data2["files"]["b.py"]["hash"], b_orig_hash)
            
            # Verify b's nodes and edges were preserved from first run
            node_labels = {n.label for n in graph2.nodes.values()}
            self.assertIn("a.py", node_labels)
            self.assertIn("b.py", node_labels)
            self.assertIn("c.py", node_labels)

    def test_incremental_scan_drops_stale_cross_file_symbol_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_file = root / "a.py"
            b_file = root / "b.py"
            a_file.write_text(
                "from b import foo\n\n"
                "def use_foo():\n"
                "    return foo()\n",
                encoding="utf-8",
            )
            b_file.write_text(
                "def foo():\n"
                "    return 1\n",
                encoding="utf-8",
            )

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir(parents=True, exist_ok=True)
            graph_path = gg_dir / "graph.json"
            manifest_path = gg_dir / "manifest.json"

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)
            old_target_ids = {
                nid
                for nid, node in graph.nodes.items()
                if node.path == "b.py" and node.label == "foo"
            }
            self.assertEqual(len(old_target_ids), 1)
            old_target_id = next(iter(old_target_ids))
            self.assertTrue(any(edge.target == old_target_id for edge in graph.edges))

            b_file.write_text(
                "def bar():\n"
                "    return 2\n",
                encoding="utf-8",
            )

            graph2 = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

            self.assertNotIn(old_target_id, graph2.nodes)
            self.assertFalse(any(edge.source == old_target_id or edge.target == old_target_id for edge in graph2.edges))
            self.assertTrue(any(node.path == "b.py" and node.label == "bar" for node in graph2.nodes.values()))
            result = validate_graph_json(graph_to_json(graph2))
            self.assertTrue(result.ok, result.errors)

    def test_incremental_scan_links_dirty_file_to_restored_symbol_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_file = root / "a.py"
            b_file = root / "b.py"
            a_file.write_text(
                "def use_foo():\n"
                "    return 0\n",
                encoding="utf-8",
            )
            b_file.write_text(
                "def foo():\n"
                "    return 1\n",
                encoding="utf-8",
            )

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir(parents=True, exist_ok=True)
            graph_path = gg_dir / "graph.json"
            manifest_path = gg_dir / "manifest.json"

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)
            target_id = next(
                nid
                for nid, node in graph.nodes.items()
                if node.path == "b.py" and node.label == "foo"
            )

            a_file.write_text(
                "from b import foo\n\n"
                "def use_foo():\n"
                "    return foo()\n",
                encoding="utf-8",
            )

            graph2 = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

            self.assertIn(target_id, graph2.nodes)
            self.assertTrue(any(edge.target == target_id and edge.type == "calls" for edge in graph2.edges))
            self.assertTrue(any(edge.target == target_id and edge.type == "references" for edge in graph2.edges))
            result = validate_graph_json(graph_to_json(graph2))
            self.assertTrue(result.ok, result.errors)

    def test_kv_cache(self) -> None:
        import time

        from graphgraph.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            cache_path = tmp / "kv_cache.json"

            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(cache_path)
            key = compute_cache_key(["N1", "N2"], "blast_radius", 2, "gg_max")

            self.assertIsNone(cache.get(graph_path, key))
            cache.set(graph_path, key, "rendered_packet_data")
            self.assertEqual(cache.get(graph_path, key), "rendered_packet_data")
            self.assertEqual(cache.cache_data[key]["node_ids"], [])
            self.assertEqual(cache.cache_data[key]["paths"], [])

            time.sleep(0.01)
            graph_path.write_text('{"nodes": {}}', encoding="utf-8")
            self.assertIsNone(cache.get(graph_path, key))

    def test_kv_cache_records_packet_dependencies(self) -> None:
        from graphgraph.cache import TopologicalKVCache, compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            graph_path.write_text("{}", encoding="utf-8")
            cache = TopologicalKVCache(tmp / "kv_cache.json")
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg_max")
            cache.set(graph_path, key, "packet", node_ids={"B", "A"}, paths={"src/a.py", ""})

            loaded = TopologicalKVCache(tmp / "kv_cache.json")
            self.assertEqual(loaded.get(graph_path, key), "packet")
            self.assertEqual(loaded.cache_data[key]["node_ids"], ["A", "B"])
            self.assertEqual(loaded.cache_data[key]["paths"], ["src/a.py"])

    def _dependency_cache_fixture(self, tmp: Path) -> tuple[Path, "TopologicalKVCache"]:
        from graphgraph.cache import TopologicalKVCache

        (tmp / "src").mkdir()
        (tmp / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
        (tmp / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
        graph_path = tmp / ".graphgraph" / "graph.json"
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        graph_path.write_text("{}", encoding="utf-8")
        cache = TopologicalKVCache(tmp / ".graphgraph" / "kv_cache.json")
        return graph_path, cache

    def test_kv_cache_survives_rescan_when_dependency_unchanged(self) -> None:
        import time

        from graphgraph.cache import compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path, cache = self._dependency_cache_fixture(tmp)
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg_max")
            cache.set(graph_path, key, "packet-for-a", node_ids={"A"}, paths={"src/a.py"})

            # Rescan bumps the graph file's mtime (e.g. an incremental scan that
            # only touched b.py), but a.py itself is untouched.
            time.sleep(0.01)
            graph_path.write_text('{"nodes": {"rescanned": true}}', encoding="utf-8")

            self.assertEqual(cache.get(graph_path, key), "packet-for-a")

    def test_kv_cache_evicts_when_dependency_changes(self) -> None:
        import time

        from graphgraph.cache import compute_cache_key

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path, cache = self._dependency_cache_fixture(tmp)
            key = compute_cache_key(["A"], "direct_lookup", 1, "gg_max")
            cache.set(graph_path, key, "packet-for-a", node_ids={"A"}, paths={"src/a.py"})

            time.sleep(0.01)
            (tmp / "src" / "a.py").write_text("A = 2  # changed\n", encoding="utf-8")
            graph_path.write_text('{"nodes": {"rescanned": true}}', encoding="utf-8")

            self.assertIsNone(cache.get(graph_path, key))

    def test_kv_cache_stats(self) -> None:
        from graphgraph.cache import TopologicalKVCache, compute_cache_key

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
        from graphgraph.cache import TopologicalKVCache, compute_cache_key

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
        from graphgraph.cache import TopologicalKVCache, compute_cache_key

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

    def test_scan_directory_no_communities_param(self) -> None:
        """scan_directory must not accept a communities keyword argument."""
        import inspect

        from graphgraph.scanner import scan_directory
        sig = inspect.signature(scan_directory)
        self.assertNotIn("communities", sig.parameters)

    def test_cli_stdio_handles_unicode_on_cp1252_streams(self) -> None:
        import io
        import sys

        from graphgraph.cli import _configure_stdio

        original_stdout = sys.stdout
        raw = io.BytesIO()
        fake_stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        try:
            sys.stdout = fake_stdout
            _configure_stdio()
            print("query_context -> anchors -> packet")
            print("query_context \u2192 anchors \u2192 packet")
            sys.stdout.flush()
        finally:
            sys.stdout = original_stdout
            fake_stdout.detach()

    def test_cli_validate_empty_packet_exits_nonzero(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "graphgraph", "validate"],
            input="@nodes\n\n@edges\n",
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL semantic_arrow nodes=0 edges=0", proc.stdout)
        self.assertIn("empty packet: no nodes", proc.stdout)

    def test_cli_final_bad_start_exits_cleanly(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graphgraph",
                    "final",
                    "--graph",
                    str(graph_path),
                    "--query-class",
                    "blast_radius",
                    "--starts",
                    "totally_bogus_id",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("Error: No graph nodes matched the requested starts", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_local_context_validate_snippets_smoke_without_provider_keys(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        for name in (
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "PREFERRED_PROVIDER",
            "OPENAI_BASE_URL",
            "RUN_OPENAI_REASONING_EVAL",
            "RUN_GEMINI_REASONING_EVAL",
        ):
            env.pop(name, None)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "app.py").write_text(
                "class AlphaService:\n"
                "    def call_beta(self):\n"
                "        return beta()\n\n"
                "def beta():\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )

            context_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graphgraph",
                    "context",
                    "AlphaService call_beta beta",
                    "--query-class",
                    "direct_lookup",
                    "--scan-max-nodes",
                    "100",
                    "--show-stats",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(context_proc.returncode, 0, context_proc.stderr)
            self.assertIn("[n]", context_proc.stdout)
            self.assertIn("GraphGraph context built:", context_proc.stderr)
            self.assertNotIn("API Key", context_proc.stdout + context_proc.stderr)

            validate_proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "validate"],
                cwd=tmp,
                input=context_proc.stdout,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(validate_proc.returncode, 0, validate_proc.stdout + validate_proc.stderr)
            self.assertIn("PASS", validate_proc.stdout)

            snippet_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graphgraph",
                    "snippets",
                    "--starts",
                    "AlphaService",
                    "--max-lines",
                    "12",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(snippet_proc.returncode, 0, snippet_proc.stderr)
            self.assertIn("class AlphaService", snippet_proc.stdout)

    def test_doctor_marks_provider_keys_optional(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(name, None)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            gg_dir = tmp / ".graphgraph"
            gg_dir.mkdir()
            save_graph(sample_graph(), gg_dir / "graph.json")
            proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "doctor"],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[Optional External Benchmark Credentials]", proc.stdout)
        self.assertIn("Local GraphGraph scan/query/packet workflows do not require provider API keys.", proc.stdout)
        self.assertIn("OpenAI API Key: Not configured (OK; external OpenAI benchmarks will be skipped)", proc.stdout)
        self.assertNotIn("OpenAI API Key: Not found", proc.stdout)

    def test_cmd_install_project(self) -> None:
        import os

        from graphgraph.cli.commands import cmd_install

        class DummyArgs:
            project = True
            platform = "codex"

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cmd_install(DummyArgs())

                # Check workspace rules
                agents_md = Path(".agents") / "AGENTS.md"
                self.assertTrue(agents_md.exists())
                content = agents_md.read_text(encoding="utf-8")
                self.assertIn("# GraphGraph Workspace Rules", content)
                self.assertIn("One-step context packet", content)
                self.assertIn("graphgraph context", content)
                self.assertIn("Known-node packet only", content)
                self.assertIn("stable-skeleton", content)

                # Check skill
                skill_md = Path(".agents") / "skills" / "graphgraph" / "SKILL.md"
                self.assertTrue(skill_md.exists())
                skill_content = skill_md.read_text(encoding="utf-8")
                self.assertIn("name: graphgraph", skill_content)
                self.assertIn("query_context", skill_content)
                self.assertIn("| `direct_lookup` | Specific file/symbol details | 1 | `gg_max` | measured token floor |", skill_content)
                self.assertNotIn("| `direct_lookup` | Specific file/symbol details | 1 | `gg_max_hybrid`", skill_content)

                # Check complete Codex plugin bundle and marketplace.json
                plugin_json = Path("plugins") / "graphgraph" / ".codex-plugin" / "plugin.json"
                self.assertTrue(plugin_json.exists())
                plugin_data = json.loads(plugin_json.read_text(encoding="utf-8"))
                self.assertEqual(plugin_data["name"], "graphgraph")
                self.assertEqual(plugin_data["skills"], "./skills/")
                self.assertEqual(plugin_data["mcpServers"], "./.mcp.json")

                mcp_json = Path("plugins") / "graphgraph" / ".mcp.json"
                self.assertTrue(mcp_json.exists())
                mcp_data = json.loads(mcp_json.read_text(encoding="utf-8"))
                server = mcp_data["mcpServers"]["graphgraph"]
                # Codex plugin bundles are committed to git and consumed from many
                # clones/machines, so this must always be the portable form -- no
                # baked-in absolute path, no assumption that `uv` is on PATH.
                self.assertEqual(server, {"command": "graphgraph-mcp"})

                plugin_skill = Path("plugins") / "graphgraph" / "skills" / "graphgraph" / "SKILL.md"
                self.assertTrue(plugin_skill.exists())
                plugin_skill_content = plugin_skill.read_text(encoding="utf-8")
                self.assertIn("name: graphgraph", plugin_skill_content)
                self.assertIn("| `direct_lookup` | Specific file/symbol details | 1 | `gg_max` | measured token floor |", plugin_skill_content)

                marketplace_json = Path(".agents") / "plugins" / "marketplace.json"
                self.assertTrue(marketplace_json.exists())
                marketplace = json.loads(marketplace_json.read_text(encoding="utf-8"))
                entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "graphgraph")
                self.assertEqual(entry["source"]["path"], "./plugins/graphgraph")
                self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
                self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
            finally:
                os.chdir(orig_cwd)

    def test_cmd_install_claude_code_project(self) -> None:
        import os

        from graphgraph.cli.commands import cmd_install

        class DummyArgs:
            project = True
            platform = "claude-code"

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cmd_install(DummyArgs())

                # Project-scoped .mcp.json pinned to this checkout via uv --project
                mcp_json = Path(".mcp.json")
                self.assertTrue(mcp_json.exists())
                mcp_data = json.loads(mcp_json.read_text(encoding="utf-8"))
                server = mcp_data["mcpServers"]["graphgraph"]
                self.assertEqual(server["command"], "uv")
                self.assertIn("--project", server["args"])
                self.assertEqual(server["args"][-1], "graphgraph-mcp")

                # Claude Code skill file
                skill_md = Path(".claude") / "skills" / "graphgraph" / "SKILL.md"
                self.assertTrue(skill_md.exists())
                skill_content = skill_md.read_text(encoding="utf-8")
                self.assertIn("name: graphgraph", skill_content)
                self.assertIn("Claude Code", skill_content)
                self.assertIn("query_context", skill_content)

                # CLAUDE.md rule injection
                claude_md = Path("CLAUDE.md")
                self.assertTrue(claude_md.exists())
                claude_content = claude_md.read_text(encoding="utf-8")
                self.assertIn("# GraphGraph Workspace Rules", claude_content)
                self.assertIn("graphgraph/query_context", claude_content)

                # Codex plugin should NOT be written for a claude-code-only install
                self.assertFalse((Path("plugins") / "graphgraph").exists())
            finally:
                os.chdir(orig_cwd)

    def test_cmd_install_claude_code_idempotent(self) -> None:
        """Re-running install must not duplicate the injected CLAUDE.md rule block."""
        import os

        from graphgraph.cli.commands import cmd_install

        class DummyArgs:
            project = True
            platform = "claude-code"

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cmd_install(DummyArgs())
                cmd_install(DummyArgs())

                claude_content = Path("CLAUDE.md").read_text(encoding="utf-8")
                self.assertEqual(claude_content.count("# GraphGraph Workspace Rules"), 1)
            finally:
                os.chdir(orig_cwd)

    def test_imported_symbol_sources(self) -> None:
        from graphgraph.scanner.frontends import _imported_symbol_sources
        
        # Test python imports
        py_text = "from my_module import foo, bar as b\nfrom other.helper import transform"
        py_sources = _imported_symbol_sources(".py", py_text)
        self.assertEqual(py_sources.get("foo"), "my_module")
        self.assertEqual(py_sources.get("bar"), "my_module")
        self.assertEqual(py_sources.get("transform"), "helper")
        
        # Test js/ts imports
        js_text = "import { transform, load as l } from './my_helper';\nimport { other } from '../another';"
        js_sources = _imported_symbol_sources(".ts", js_text)
        self.assertEqual(js_sources.get("transform"), "my_helper")
        self.assertEqual(js_sources.get("load"), "my_helper")
        self.assertEqual(js_sources.get("other"), "another")

    def test_render_final_packet_injects_lessons(self) -> None:
        from graphgraph.core import Graph, Node
        from graphgraph.services import render_final_packet
        
        g = Graph(
            nodes={"A": Node("A", "AuthService", "service", "auth.py")},
            edges=[]
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            g_path = tmp / "graph.json"
            save_graph(g, g_path)
            
            # Write a dummy lessons file
            lessons_file = tmp / "lessons.md"
            lessons_file.write_text("Avoid exploring legacy routes", encoding="utf-8")
            
            # Mock find_lessons_path and find_graph_path
            import graphgraph.services.context as ctx
            orig_find_graph = ctx.find_graph_path
            orig_find_lessons = ctx.find_lessons_path
            ctx.find_graph_path = lambda: g_path
            ctx.find_lessons_path = lambda: lessons_file
            
            try:
                packet = render_final_packet(starts=["A"], query_class="direct_lookup")
                self.assertIn("LESSONS / PAST SESSION REFLECTIONS:", packet)
                self.assertIn("Avoid exploring legacy routes", packet)
            finally:
                ctx.find_graph_path = orig_find_graph
                ctx.find_lessons_path = orig_find_lessons

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
            ]
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

    def test_personalization_lexical_score_constants(self) -> None:
        from graphgraph.core import Edge, Graph, Node
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

    def test_tensor_spatial_bias(self) -> None:
        from graphgraph.packets import render_tensor_array
        g = Graph(
            nodes={
                "A": Node("A", "AuthService", "service", "auth.py", active=True),
                "B": Node("B", "TokenStore", "data", "tokens.py", active=True),
                "C": Node("C", "AuditLog", "data", "audit.py", active=True),
            },
            edges=[
                Edge("A", "B", "calls", 1.0),
                Edge("B", "C", "calls", 1.0),
            ]
        )
        res = render_tensor_array(g, {"A", "B", "C"}, g.edges)
        self.assertIn("@s", res)
        # Path distance A to C should be 2. Let's assert on distances.
        self.assertIn("[0,1,2]", res) or self.assertIn("[2,1,0]", res)

    def test_tree_knapsack_context_partition(self) -> None:
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition
        g = Graph(
            nodes={
                "A": Node("A", "A", "class", "a.py", active=True, facts=("f1",)),
                "B": Node("B", "B", "class", "b.py", active=True, facts=("f1",)),
                "C": Node("C", "C", "class", "c.py", active=True, facts=("f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8")),
            },
            edges=[
                Edge("A", "B", "calls", 1.0),
                Edge("A", "C", "calls", 1.0),
            ]
        )
        values = {"A": 10.0, "B": 5.0, "C": 8.0}
        
        # Test 1: Budget weight = 2 (approx 80 tokens). Fits A (w=1) + B (w=1). C (w=2) cannot fit with A.
        selected = tree_knapsack_context_partition(g, ("A",), {"A", "B", "C"}, values, 80)
        self.assertIn("A", selected)
        self.assertIn("B", selected)
        self.assertNotIn("C", selected)
        
        # Test 2: Budget weight = 3 (approx 120 tokens). Fits A (w=1) + C (w=2) because 10+8=18 > A+B=15.
        selected = tree_knapsack_context_partition(g, ("A",), {"A", "B", "C"}, values, 120)
        self.assertIn("A", selected)
        self.assertIn("C", selected)
        self.assertNotIn("B", selected)

    def test_build_bfs_tree_handles_start_node_outside_candidates(self) -> None:
        # Regression: tree was pre-seeded with keys only for `candidates`, but
        # BFS starts from `starts`. A start node not itself in candidates
        # (e.g. an anchor that graph.expand() dropped for being inactive or
        # out of scope) with a neighbor that IS a candidate raised KeyError
        # on `tree[curr].append(...)`.
        from graphgraph.retrieval.tree_knapsack import build_bfs_tree
        graph = Graph(
            nodes={"S": Node("S", "S"), "C1": Node("C1", "C1")},
            edges=[Edge("S", "C1", "calls")],
        )
        tree = build_bfs_tree(graph, starts=("S",), candidates={"C1"})
        self.assertEqual(tree.get("S"), ["C1"])

    def test_tree_knapsack_selects_orphan_candidates(self) -> None:
        # Regression: the orphan-detection loop marked every disconnected
        # candidate as visited via dfs() *before* the code that was supposed
        # to record them as roots ran, so `[nid for nid in candidates if nid
        # not in visited_dfs]` was always empty. Each orphan's DP table was
        # computed but it could never be selected at the top level.
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition
        graph = Graph(
            nodes={
                "S": Node("S", "S"),
                "ORPHAN": Node("ORPHAN", "orphan", "function", summary="x" * 200),
            },
            edges=[],  # ORPHAN is unreachable from S -- a disconnected component
        )
        selected = tree_knapsack_context_partition(
            graph, starts=("S",), candidates={"ORPHAN"},
            node_values={"ORPHAN": 100.0}, max_token_budget=4000,
        )
        self.assertIn("ORPHAN", selected)

    def test_tree_knapsack_handles_long_chain_without_recursion_error(self) -> None:
        # Regression: both the dfs() post-order traversal and
        # subtree_backtrack() were plain function recursion. A long
        # dependency chain -- plausible in a real 2000-node graph -- exceeds
        # Python's default recursion limit (~1000) and crashes with
        # RecursionError. Confirmed this exact input crashes the old
        # recursive implementation; both were converted to explicit-stack
        # iteration.
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition
        n = 1500
        nodes = {f"n{i}": Node(f"n{i}", f"n{i}", "function") for i in range(n)}
        edges = [Edge(f"n{i}", f"n{i + 1}", "calls") for i in range(n - 1)]
        graph = Graph(nodes=nodes, edges=edges)
        candidates = set(nodes.keys()) - {"n0"}
        values = {nid: 1.0 for nid in candidates}

        selected = tree_knapsack_context_partition(
            graph, starts=("n0",), candidates=candidates, node_values=values, max_token_budget=2000,
        )
        self.assertGreater(len(selected), 0)


if __name__ == "__main__":
    unittest.main()
