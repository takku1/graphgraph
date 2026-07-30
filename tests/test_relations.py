from __future__ import annotations

import unittest

from graphgraph import Edge, Graph, Node
from graphgraph.retrieval.relations import encode_relation_micro, query_relations


def _relation_graph() -> Graph:
    return Graph(
        nodes={
            "TARGET": Node("TARGET", "work", "function", "src/core.py", "L10"),
            "CONCEPT": Node("CONCEPT", "work", "concept", "docs/design.md"),
            "CALLER": Node("CALLER", "run", "function", "src/app.py", "L20"),
            "TEST": Node("TEST", "test_work", "function", "tests/test_core.py", "L30"),
            "CALLEE": Node("CALLEE", "helper", "function", "src/helper.py", "L40"),
            "EXTERNAL": Node("EXTERNAL", "append", "external"),
            "REFERENCE": Node("REFERENCE", "work_notes", "section", "docs/design.md"),
        },
        edges=[
            Edge("CALLER", "TARGET", "calls", confidence=0.95, provenance="tree_sitter"),
            Edge("TEST", "TARGET", "calls", confidence=0.9, provenance="tree_sitter"),
            Edge("REFERENCE", "TARGET", "references"),
            Edge("TARGET", "CALLEE", "calls", confidence=0.85, provenance="tree_sitter"),
            Edge("TARGET", "EXTERNAL", "calls", confidence=0.5, provenance="external"),
        ],
        metadata={
            "member_calls_global_resolved": "12",
            "member_calls_global_unknown_receiver": "0",
            "member_calls_global_ambiguous": "0",
            "member_calls_global_scope": "full_scan",
        },
    )


class RelationQueryTest(unittest.TestCase):
    def test_exact_code_symbol_beats_same_named_concept_and_filters_edge_type(self) -> None:
        result = query_relations(_relation_graph(), "work", direction="callers")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["target"]["id"], "TARGET")
        self.assertEqual([item["id"] for item in result["neighbors"]], ["CALLER", "TEST"])
        self.assertEqual([item["role"] for item in result["neighbors"]], ["production", "test"])
        self.assertEqual(result["matched_total"], 2)
        self.assertTrue(result["receipt"]["complete_within_graph"])
        self.assertEqual(result["receipt"]["call_topology_status"], "complete")
        self.assertFalse(result["receipt"]["answer_complete"])

    def test_qualified_path_symbol_resolves_one_real_collision(self) -> None:
        graph = _relation_graph()
        graph.nodes["OTHER"] = Node("OTHER", "work", "function", "src/other.py", "L5")
        graph.nodes["OTHER_CALLER"] = Node("OTHER_CALLER", "other_run", "function", "src/other_app.py")
        graph.edges.append(Edge("OTHER_CALLER", "OTHER", "calls"))

        result = query_relations(graph, "src/core.py::work", direction="callers")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["target"]["id"], "TARGET")
        self.assertEqual([item["id"] for item in result["neighbors"]], ["CALLER", "TEST"])

    def test_bare_duplicate_code_symbol_is_explicitly_ambiguous(self) -> None:
        graph = _relation_graph()
        graph.nodes["OTHER"] = Node("OTHER", "work", "function", "src/other.py", "L5")

        result = query_relations(graph, "work", direction="callers")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(
            [(item["id"], item["path"]) for item in result["candidates"]],
            [("TARGET", "src/core.py"), ("OTHER", "src/other.py")],
        )
        self.assertNotIn("CONCEPT", {item["id"] for item in result["candidates"]})

    def test_callees_exclude_external_nodes_by_default_and_report_filter(self) -> None:
        result = query_relations(_relation_graph(), "work", direction="callees")

        self.assertEqual([item["id"] for item in result["neighbors"]], ["CALLEE"])
        self.assertEqual(result["matched_total"], 2)
        self.assertEqual(result["filtered"], {"tests": 0, "external": 1})

    def test_truncation_is_distinct_from_topology_coverage(self) -> None:
        result = query_relations(_relation_graph(), "work", direction="callers", limit=1)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["omitted"], 1)
        self.assertFalse(result["receipt"]["complete_within_graph"])
        self.assertEqual(result["receipt"]["call_topology_status"], "complete")
        self.assertFalse(result["receipt"]["answer_complete"])

    def test_missing_call_telemetry_is_unknown_not_proven_complete(self) -> None:
        graph = _relation_graph()
        graph.metadata.clear()

        result = query_relations(graph, "work", direction="callers")

        self.assertEqual(result["receipt"]["call_topology_status"], "unknown")
        self.assertFalse(result["receipt"]["answer_complete"])

    def test_micro_v2_is_self_decoding_and_emits_next_actions(self) -> None:
        result = query_relations(
            _relation_graph(),
            "work",
            direction="callers",
            limit=1,
            freshness="unchecked",
        )

        payload = encode_relation_micro(result)

        self.assertEqual(payload["v"], 2)
        self.assertEqual(payload["tk"], ["id", "label", "kind", "path", "line"])
        self.assertEqual(payload["k"], ["label", "kind", "path", "line", "role", "confidence"])
        self.assertEqual(payload["r"]["filtered"], {"tests": 0, "external": 0})
        self.assertEqual(
            payload["a"],
            ["raise_limit", "sync_if_completeness_required"],
        )

    def test_fresh_complete_graph_licenses_complete_answer(self) -> None:
        result = query_relations(
            _relation_graph(),
            "work",
            direction="callers",
            freshness="fresh",
        )

        self.assertTrue(result["receipt"]["answer_complete"])

    def test_not_found_micro_emits_composable_recovery(self) -> None:
        payload = encode_relation_micro(query_relations(_relation_graph(), "missing", direction="callers"))

        self.assertEqual(payload["a"], ["search_nodes", "retry_exact_id_or_path_symbol"])


if __name__ == "__main__":
    unittest.main()
