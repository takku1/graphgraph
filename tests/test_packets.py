from __future__ import annotations

import unittest

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
    Policy,
    Query,
    add_policy_node,
    policy_to_node,
    select_policies,
    validate_packet,
)
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
from graphgraph.policies import render_policy_packet
from graphgraph.retrieval import (
    budget_edges,
)
from graphgraph.traversal import relation_rank, traversal_policy


class PacketsTest(unittest.TestCase):
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

    def test_gg_max_validation_survives_node_content_containing_marker_substrings(self) -> None:
        # Found live-testing full-graph (unfiltered, unbounded) rendering:
        # validate_gg_max detected/split sections by searching for "[r]"/
        # "[n]"/"[e]" as a bare substring anywhere in the packet text. A doc
        # -scanned concept node whose label happened to literally contain
        # those characters (e.g. quoted example packet output captured
        # verbatim from a docstring/comment, such as
        # "[r]\\n[n]\\n1 Widget\\n[e]") corrupted parsing for the entire rest
        # of the packet -- confirmed with a real repro rendering this
        # project's own full graph. The real renderer always emits these
        # markers as standalone lines, so validation must anchor on that
        # structural guarantee instead of a substring search.
        graph = Graph(
            nodes={
                "A": Node("A", "AuthService", "service", "server/auth.py"),
                # This label contains literal "[r]"/"[n]"/"[e]" substrings,
                # but never as a standalone line by itself.
                "B": Node("B", "example output: [r]\\n[n]\\n1 Widget\\n[e]", "concept"),
                "C": Node("C", "TokenStore", "data", "server/tokens.py"),
            },
            edges=[Edge("A", "C", "reads", 0.9)],
        )
        packet = render_gg_max(graph, {"A", "B", "C"}, graph.edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 1)

    def test_gg_max_hybrid_scales_facts_per_node_to_selection_size(self) -> None:
        # New: every hybrid renderer used to hardcode facts[:2]/facts[:3]
        # regardless of how many nodes were actually selected -- a small
        # project got the exact same fixed allowance as a huge one, so
        # "more detail for a small project" was never a deliberate behavior,
        # just less competition for a static budget. recommend_facts_per_node
        # makes this an explicit function of selection size.
        many_facts = tuple(f"fact_{i}" for i in range(8))

        # Small selection: one richly-detailed node should show close to
        # the max allowance.
        small_graph = Graph(nodes={"A": Node("A", "Widget", "class", "a.py", facts=many_facts)})
        small_packet = render_gg_max(small_graph, {"A"}, [], hybrid=True)
        small_fact_lines = [line for line in small_packet.splitlines() if line.startswith(" fact_")]
        self.assertGreaterEqual(len(small_fact_lines), 4, small_packet)

        # Large selection: the same richly-detailed node, now competing
        # with many other selected nodes, should show fewer facts.
        large_nodes = {"A": Node("A", "Widget", "class", "a.py", facts=many_facts)}
        for i in range(60):
            large_nodes[f"N{i}"] = Node(f"N{i}", f"Other{i}", "function", f"n{i}.py")
        large_graph = Graph(nodes=large_nodes)
        large_packet = render_gg_max(large_graph, set(large_nodes), [], hybrid=True)
        large_fact_lines = [line for line in large_packet.splitlines() if line.startswith(" fact_")]
        self.assertLess(len(large_fact_lines), len(small_fact_lines))
        self.assertLessEqual(len(large_fact_lines), 2)

    def test_render_and_validate_gg_max_with_default_weights(self) -> None:
        graph = Graph(
            nodes={
                "N1": Node("N1", "AuthService", "service", "server/auth.py"),
                "N2": Node("N2", "TokenStore", "data", "server/tokens.py"),
            },
            edges=[
                Edge("N1", "N2", "reads", 1.0),
            ],
        )
        nodes, edges = graph.expand(["N1"], hops=1)
        packet = render_gg_max(graph, nodes, edges)
        self.assertNotIn("1.0", packet)  # weight omitted
        self.assertIn("1:", packet.split("[e]")[1])  # relation opcode group
        self.assertIn("1 2", packet.split("[e]")[1])  # endpoint row under opcode
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

    def test_gg_max_hybrid_detected_with_multi_word_labels(self) -> None:
        # Regression: doc-scanned "section" nodes use free-text titles as their
        # label (e.g. "Getting Started"), which can contain spaces. The hybrid
        # node line is "{idx} {label} [{kind}] {summary}"; the old detection
        # regex required exactly one single-token label before the "[kind]"
        # bracket, so any multi-word label made a real gg_max_hybrid packet
        # misreport its format as plain "gg_max" (and gg_lex_hybrid as "gg_lex").
        graph = Graph(
            nodes={
                "S1": Node("S1", "Getting Started", "section", "README.md", summary="Intro."),
                "S2": Node("S2", "Installation Guide", "section", "README.md", summary="Setup."),
            },
            edges=[Edge("S1", "S2", "section_of", 1.0)],
        )
        nodes = set(graph.nodes.keys())
        packet = render_packet(graph, nodes, graph.edges, "gg_max_hybrid")
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_max_hybrid")

        packet_lex = render_packet(graph, nodes, graph.edges, "gg_lex_hybrid")
        result_lex = validate_packet(packet_lex)
        self.assertTrue(result_lex.ok, result_lex.errors)
        self.assertEqual(result_lex.format, "gg_lex_hybrid")

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

    def test_policy_can_be_graph_node(self) -> None:
        policy = Policy(
            "P1",
            "security",
            "must",
            ("server/auth/**",),
            ("security",),
            "Use constant-time token checks",
            "Full policy",
        )
        node = policy_to_node(policy)
        self.assertEqual(node.id, "policy_P1")
        self.assertEqual(node.kind, "policy")
        self.assertEqual(node.scope, "server/auth/**")
        self.assertEqual(node.facts, ("Full policy",))

        graph, op = add_policy_node(Graph(), policy)
        self.assertEqual(op.op, "AddNode")
        self.assertIn("policy_P1", graph.nodes)

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
        kept_counts = {
            relation: len([edge for edge in kept if edge.type == relation])
            for relation in {"references", "links", "mentions", "calls"}
        }

        self.assertLess(sum(count for relation, count in kept_counts.items() if relation != "calls"), 30)
        self.assertGreater(kept_counts["references"], kept_counts["links"])
        self.assertGreaterEqual(kept_counts["links"], 1)
        self.assertGreaterEqual(kept_counts["mentions"], 1)
        self.assertEqual(kept_counts["calls"], 1)

    def test_budget_edges_shaped_path_exact_quotas(self) -> None:
        edges = [
            Edge("N1", f"R{i}", "references", 1.0, confidence=0.9, provenance="regex_reference") for i in range(40)
        ]
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
