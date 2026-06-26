from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
    graph_at,
    merge_node,
    operation_to_json,
    policy_to_node,
    read_operations,
    scan_directory,
    select_policies,
    validate_packet,
)
from graphgraph.ast_scanner import extract_symbols
from graphgraph.communities import add_community_nodes, detect_path_communities
from graphgraph.doc_scanner import DocumentInput, extract_document_context
from graphgraph.eval import EvalTask, estimate_tokens, evaluate_graph
from graphgraph.frontends import RegexExtractor, SourceFile, _imported_symbol_names, available_frontends, select_extractor, tree_sitter_available
from graphgraph.io import load_graph, load_policies, save_graph, load_gg, save_gg, load_csv_edges, load_any
from graphgraph.mcp_server import dispatch
from graphgraph.metrics import compare_graphs, summarize_graph
from graphgraph.packets import render_doc_summary, render_lowlevel, render_semantic_arrow, render_gg_max, render_sql, render_svo
from graphgraph.policies import render_policy_packet
from graphgraph.retrieval import budget_edges, default_anchor_limit, retrieve_context, retrieval_node_budget, search_nodes, tokenize
from graphgraph.ontology import provenance_confidence, relation_spec, traversal_strength
from graphgraph.semantic import SemanticTriple, merge_semantic_triples
from graphgraph.terms import canonical_concept_label, concept_id, term_key
from graphgraph.traversal import traversal_policy, relation_rank


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

    def test_policy_selection(self) -> None:
        policies = [
            Policy("P1", "frontend", "must", ("src/ui/**",), ("frontend",), "UI compact"),
            Policy("P2", "security", "must", ("server/auth/**",), ("security",), "SEC compact"),
        ]
        query = Query("update button", "direct_lookup", paths=("src/ui/Button.tsx",), tags=("frontend",))
        selected = select_policies(policies, query)
        self.assertEqual([policy.id for policy in selected], ["P1"])
        self.assertEqual(render_policy_packet(selected), "P1:must:UI compact")

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
        # Empirical data: direct/reverse → sql (low overhead at 1-hop)
        self.assertEqual(choose_packet("direct_lookup").packet, "sql")
        self.assertEqual(choose_packet("direct_lookup").hops, 1)
        self.assertEqual(choose_packet("reverse_lookup").packet, "sql")
        self.assertEqual(choose_packet("reverse_lookup").hops, 1)
        # blast_radius / multi_hop → gg_max 2-hop (token floor for topology)
        self.assertEqual(choose_packet("blast_radius").hops, 2)
        self.assertEqual(choose_packet("blast_radius").packet, "gg_max")
        self.assertEqual(choose_packet("multi_hop_path").hops, 2)
        self.assertEqual(choose_packet("multi_hop_path").packet, "gg_max")
        # summary → hybrid (needs inline facts)
        self.assertEqual(choose_packet("subsystem_summary").packet, "gg_max_hybrid")
        self.assertEqual(choose_packet("subsystem_summary", "README installation usage").packet, "doc_summary")
        self.assertEqual(choose_packet("doc_summary").packet, "doc_summary")
        # unknown → conservative 2-hop gg_max
        self.assertEqual(choose_packet("unknown_xyz").hops, 2)
        self.assertEqual(choose_packet("unknown_xyz").packet, "gg_max")

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

    def test_merge_semantic_triples_adds_provenanced_edges(self) -> None:
        graph = Graph(nodes={"A": Node("A", "AuthService")})
        merged = merge_semantic_triples(graph, [
            SemanticTriple("AuthService", "supports", "Security Policy", confidence=0.7, evidence="README")
        ])
        self.assertIn("semantic_triples", merged.metadata)
        self.assertTrue(any(node.label == "Security Policy" for node in merged.nodes.values()))
        edge = next(edge for edge in merged.edges if edge.type == "supports")
        self.assertEqual(edge.provenance, "semantic_llm")
        self.assertEqual(edge.confidence, 0.7)

    def test_terms_normalize_concepts_consistently(self) -> None:
        self.assertEqual(term_key("Token Store"), "token store")
        self.assertEqual(term_key("token-store"), "token store")
        self.assertEqual(term_key("TokenStore"), "token store")
        self.assertEqual(concept_id("Token Store"), "concept_token_store")
        self.assertEqual(canonical_concept_label("token store"), "Token Store")

    def test_semantic_triples_merge_with_existing_normalized_concepts(self) -> None:
        graph = Graph(nodes={"concept_token_store": Node("concept_token_store", "Token Store", "concept")})
        merged = merge_semantic_triples(graph, [
            SemanticTriple("token-store", "relates", "AuthService", confidence=0.7)
        ])
        self.assertEqual(len([node for node in merged.nodes.values() if term_key(node.label) == "token store"]), 1)
        self.assertTrue(any(edge.source == "concept_token_store" for edge in merged.edges))

    def test_eval_graph_reports_recall_and_token_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), path)
            results = evaluate_graph(path, [EvalTask("auth service", "blast_radius", expected_nodes=("server/auth.py", "AuthService()"))])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].node_recall, 1.0)
            self.assertGreater(results[0].token_estimate, 0)
            self.assertGreater(estimate_tokens("A -calls-> B"), 0)

    def test_path_communities_add_summary_nodes(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "A", path="crates/core/a.rs"),
                "B": Node("B", "B", path="crates/core/b.rs"),
                "C": Node("C", "C", path="docs/readme.md"),
            },
            edges=[],
        )
        communities = detect_path_communities(graph)
        self.assertTrue(any(c.label == "crates/core/a.rs".rsplit("/", 1)[0] or c.label == "crates/core" for c in communities))
        enriched = add_community_nodes(graph)
        self.assertIn("community", {node.kind for node in enriched.nodes.values()})

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

    def test_graph_at_filters_temporal_edges(self) -> None:
        graph = Graph(
            nodes={
                "N1": Node("N1", "A", created_at="2026-01-01T00:00:00Z"),
                "N2": Node("N2", "B", created_at="2026-01-01T00:00:00Z"),
            },
            edges=[
                Edge("N1", "N2", "calls", valid_from="2026-01-01T00:00:00Z", valid_to="2026-06-01T00:00:00Z"),
            ],
        )
        before = graph_at(graph, "2026-05-01T00:00:00Z")
        after = graph_at(graph, "2026-07-01T00:00:00Z")
        self.assertEqual(len(before.edges), 1)
        self.assertEqual(len(after.edges), 0)

    def test_default_path_resolution(self) -> None:
        from graphgraph.io import find_graph_path, find_policies_path
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
        self.assertEqual(data["packet"], "sql")
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
        matches = search_nodes(graph, "what calls compile_rules_slice", limit=3)
        self.assertEqual(matches[0].node.id, "F")
        result = retrieve_context(graph, "what calls compile_rules_slice", "reverse_lookup", hops=1, max_nodes=5)
        self.assertIn("C", result.nodes)

    def test_subsystem_summary_uses_compact_node_budget(self) -> None:
        self.assertEqual(default_anchor_limit("README installation usage", "subsystem_summary"), 3)
        self.assertEqual(retrieval_node_budget("matrix transpose orthogonal symmetric square vector rules", "subsystem_summary", 40), 24)
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

    def test_budget_edges_caps_weak_references(self) -> None:
        edges = [Edge("N1", f"N{i}", "references", 0.5) for i in range(30)]
        edges += [Edge("N1", "N2", "calls", 1.0) for _ in range(3)]
        kept = budget_edges(edges, max_nodes=20)
        self.assertEqual(len([e for e in kept if e.type == "references"]), 10)
        self.assertEqual(len([e for e in kept if e.type == "calls"]), 3)

    def test_relation_ontology_drives_traversal_and_weak_budgeting(self) -> None:
        self.assertEqual(relation_spec("calls").family, "execution")
        self.assertGreater(traversal_strength("calls"), traversal_strength("references"))
        self.assertGreater(provenance_confidence("tree_sitter"), provenance_confidence("regex_reference"))
        edges = [Edge("N1", f"N{i}", "unknown_relation", 0.5) for i in range(30)]
        kept = budget_edges(edges)
        self.assertEqual(len(kept), 12)

    def test_traversal_policy_is_query_class_specific(self) -> None:
        blast = traversal_policy("blast_radius")
        summary = traversal_policy("subsystem_summary")
        self.assertIn("tests", blast.preferred_relations)
        self.assertIn("contains", summary.preferred_relations)
        self.assertLess(relation_rank("calls", blast), relation_rank("references", blast))

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

    def test_retrieve_context_respects_scope(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "Alpha", path="backend/a.py"),
                "B": Node("B", "Beta", path="backend/b.py"),
                "C": Node("C", "Client", path="frontend/c.ts"),
            },
            edges=[Edge("A", "B", "calls"), Edge("A", "C", "calls")],
        )
        result = retrieve_context(graph, "alpha", "blast_radius", hops=1, scopes=("backend",))
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

    def test_scanner_communities_flag_adds_community_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "a.py").write_text("pass\n", encoding="utf-8")
            (pkg / "b.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root, communities=True)
            self.assertEqual(graph.metadata["communities"], "path")
            self.assertIn("community", {node.kind for node in graph.nodes.values()})

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


    # --- .gg roundtrip tests ---

    def test_save_load_gg_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g = sample_graph()
            path = Path(tmp) / "graph.gg"
            save_gg(g, path)
            g2 = load_gg(path)
            self.assertEqual(set(n.label for n in g.nodes.values()),
                             set(n.label for n in g2.nodes.values()))
            self.assertEqual(len(g.edges), len(g2.edges))
            edge_types = {e.type for e in g2.edges}
            self.assertIn("reads", edge_types)
            self.assertIn("writes", edge_types)

    def test_save_gg_omits_weight_when_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g = Graph(
                nodes={"A": Node("A", "Alpha", "file", "a.py"), "B": Node("B", "Beta", "file", "b.py")},
                edges=[Edge("A", "B", "imports", 1.0)],
            )
            path = Path(tmp) / "g.gg"
            save_gg(g, path)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("1.0", content)
            self.assertIn("imports Beta", content)

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

    def test_kv_cache(self) -> None:
        import time
        from graphgraph.cache import TopologicalKVCache, compute_cache_key
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            graph_path = tmp / "graph.json"
            cache_path = tmp / "kv_cache.json"
            
            # Create a mock graph file
            graph_path.write_text("{}", encoding="utf-8")
            
            cache = TopologicalKVCache(cache_path)
            key = compute_cache_key(["N1", "N2"], "blast_radius", 2, "gg_max")
            
            # Verify cache get returns None initially
            self.assertIsNone(cache.get(graph_path, key))
            
            # Set cache
            cache.set(graph_path, key, "rendered_packet_data")
            
            # Verify cache get returns value
            self.assertEqual(cache.get(graph_path, key), "rendered_packet_data")
            
            # Modify the graph file to simulate invalidation
            time.sleep(0.01)
            graph_path.write_text("{\"nodes\": {}}", encoding="utf-8")
            
            # Verify cache get returns None (invalidated by modification time check)
            self.assertIsNone(cache.get(graph_path, key))


if __name__ == "__main__":
    unittest.main()
