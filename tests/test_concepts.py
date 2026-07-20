from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph import Edge, Graph, Node, retrieve_context, scan_directory, update_paths
from graphgraph.concepts import (
    INTERPRETATION_CONCEPT_IDS,
    SOURCE_CONCEPT_RELATIONS,
    concept_link_health,
    link_source_interpretation_concepts,
)
from graphgraph.io import save_graph


class ConceptLinkingTest(unittest.TestCase):
    def test_normalized_ir_facts_emit_typed_proven_edges(self) -> None:
        source = Node(
            "compare_and_unique",
            "compare_and_unique",
            "function",
            "src/logic.rs",
            facts=(
                "semantic_operator:equality",
                "semantic_operation:deduplication",
            ),
        )

        nodes, edges = link_source_interpretation_concepts(source)

        self.assertEqual(
            {(edge.type, nodes[edge.target].label) for edge in edges},
            {
                ("uses_semantic_operator", "Equality Comparison"),
                ("performs_semantic_operation", "Deduplication"),
            },
        )
        self.assertTrue(all(edge.provenance == "interpretation_registry_fact" for edge in edges))
        self.assertTrue(all(edge.confidence == 0.98 for edge in edges))
        self.assertEqual(
            {edge.evidence for edge in edges},
            {
                "normalized_ir_fact:semantic_operator:equality",
                "normalized_ir_fact:semantic_operation:deduplication",
            },
        )

    def test_semantic_words_without_frontend_facts_do_not_link(self) -> None:
        source = Node(
            "equality_report",
            "equality_report",
            "function",
            "src/equality_helpers.py",
            summary="Describe equality and deduplication behavior.",
        )

        nodes, edges = link_source_interpretation_concepts(source)

        self.assertEqual(nodes, {})
        self.assertEqual(edges, [])

    def test_exact_closed_registry_alias_remains_supported(self) -> None:
        source = Node(
            "dynamic_programming",
            "dynamic_programming",
            "function",
            "src/planner.py",
        )

        nodes, edges = link_source_interpretation_concepts(source)

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].type, "implements_algorithm")
        self.assertEqual(edges[0].provenance, "interpretation_registry")
        self.assertEqual(nodes[edges[0].target].label, "Tree Knapsack Dynamic Programming")

    def test_scanner_projects_python_fact_but_rejects_label_only_and_self_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logic.py").write_text(
                "def compare(left, right):\n"
                "    return left == right\n\n"
                "def equality_report():\n"
                "    marker = 'left == right'\n"
                "    # self.assertEqual(left, right)\n"
                "    return 'equality only'\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "# Planner\n\nBellman optimality guides the planner.\n",
                encoding="utf-8",
            )

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                docs=True,
            )

        compare_id = next(node.id for node in graph.nodes.values() if node.label == "compare")
        report_id = next(node.id for node in graph.nodes.values() if node.label == "equality_report")
        typed_edges = [
            edge for edge in graph.edges
            if edge.type == "uses_semantic_operator"
        ]
        self.assertEqual(len(typed_edges), 1)
        self.assertEqual(typed_edges[0].source, compare_id)
        self.assertNotEqual(typed_edges[0].source, report_id)
        self.assertFalse(any(
            edge.type in SOURCE_CONCEPT_RELATIONS
            and edge.source in INTERPRETATION_CONCEPT_IDS
            for edge in graph.edges
        ))
        self.assertEqual(
            graph.metadata["source_concepts_mode"],
            "closed_registry_typed_fact_or_exact_alias_v2",
        )
        self.assertEqual(graph.metadata["source_concepts_typed_fact_links"], "1")
        self.assertEqual(graph.metadata["source_concepts_exact_alias_links"], "0")
        self.assertGreaterEqual(int(graph.metadata["source_concepts_linked_concepts"]), 1)

    def test_targeted_update_strips_legacy_registry_self_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logic.py").write_text("def compare(a, b):\n    return a == b\n", encoding="utf-8")
            (root / "README.md").write_text("Bellman optimality.\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                docs=True,
                manifest_path=manifest_path,
            )
            bellman_id = next(
                node_id for node_id, node in graph.nodes.items()
                if node.label == "Bellman Optimality Equation"
            )
            graph.edges.append(Edge(
                bellman_id,
                bellman_id,
                "implements_algorithm",
                provenance="interpretation_registry",
            ))
            save_graph(graph, graph_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["README.md"]["edges"].append(
                [bellman_id, bellman_id, "implements_algorithm"]
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            (root / "logic.py").write_text("def compare(a, b):\n    return a != b\n", encoding="utf-8")
            updated = update_paths(
                root,
                ["logic.py"],
                depth="symbols",
                frontend="tree_sitter",
                docs=True,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

        self.assertFalse(any(
            edge.source == bellman_id
            and edge.target == bellman_id
            and edge.type in SOURCE_CONCEPT_RELATIONS
            for edge in updated.edges
        ))

    def test_health_reports_verified_evidence_and_support_threshold(self) -> None:
        unavailable = concept_link_health(100, 0)
        partial = concept_link_health(100, 20)

        self.assertIn("no verified registry-evidence links", unavailable["diagnostic_reason"])
        self.assertFalse(unavailable["supported"])
        self.assertEqual(partial["status"], "partial")
        self.assertTrue(partial["supported"])

    def test_reverse_lookup_compiles_embedded_concept_label_to_typed_root(self) -> None:
        source = Node(
            "compare",
            "compare",
            "function",
            "src/logic.py",
            facts=("semantic_operator:equality",),
        )
        concept_nodes, concept_edges = link_source_interpretation_concepts(source)
        noise = Node(
            "source_symbols",
            "source_symbols",
            "function",
            "src/source_symbols.py",
        )
        graph = Graph(
            nodes={source.id: source, noise.id: noise, **concept_nodes},
            edges=concept_edges,
            metadata={
                "source_concepts_eligible": "2",
                "source_concepts_linked_nodes": "1",
                "source_concepts_links": "1",
                "source_concepts_typed_fact_links": "1",
                "source_concepts_exact_alias_links": "0",
                "source_concepts_linked_concepts": "1",
                "source_concepts_scope": "full_graph_snapshot",
            },
        )

        result = retrieve_context(
            graph,
            "Which source symbols use Equality Comparison?",
            "reverse_lookup",
            hops=1,
            anchor_limit=1,
            max_nodes=8,
        )

        concept_id = next(iter(concept_nodes))
        self.assertEqual(result.starts, (concept_id,))
        self.assertEqual(result.matches[0].node.id, concept_id)
        self.assertIn("exact_fast_path", result.matches[0].reasons)
        self.assertIn(source.id, result.nodes)
        self.assertNotIn(noise.id, result.nodes)
        self.assertTrue(any(
            edge.source == source.id
            and edge.target == concept_id
            and edge.type == "uses_semantic_operator"
            for edge in result.edges
        ))


if __name__ == "__main__":
    unittest.main()
