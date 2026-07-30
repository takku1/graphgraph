from __future__ import annotations

import json
import unittest

from graphgraph.mcp import dispatch
from graphgraph.mcp.machine_contract import (
    MACHINE_CONTRACT_CHAR_CEILING,
    tool_contract_size_receipt,
    tool_schema_snapshot,
)
from graphgraph.mcp.server import TOOLS, handle_tools_call

TOOL_NAMES = (
    "plan_context",
    "final_packet",
    "full_graph",
    "query_context",
    "project_status",
    "query_relations",
    "validate_packet",
    "source_snippets",
    "build_graph",
    "update_graph_files",
    "remove_graph_files",
    "export_graph",
    "search_nodes",
    "select_symbols",
    "describe_formats",
    "describe_ontology",
    "describe_frontends",
    "describe_traversal",
    "compile_context",
    "repair_context",
    "graph_change",
    "memory_context",
    "graph_at_time",
)

QUERY_CLASSES = (
    "direct_lookup",
    "reverse_lookup",
    "affected_tests",
    "multi_hop_path",
    "blast_radius",
    "subsystem_summary",
    "doc_summary",
    "negative_query",
    "recent_changes",
    "spreading_activation",
)

PACKET_FORMATS = (
    "lowlevel",
    "sql",
    "hybrid",
    "semantic_arrow",
    "gg",
    "gg_hybrid",
    "gg_lex",
    "gg_lex_hybrid",
    "svo",
    "doc_summary",
)

BASELINE_TOOL_CHARS = {
    "plan_context": 797,
    "final_packet": 1605,
    "full_graph": 898,
    "query_context": 4217,
    "query_relations": 900,
    "project_status": 547,
    "validate_packet": 611,
    "source_snippets": 831,
    "build_graph": 2514,
    "update_graph_files": 1370,
    "remove_graph_files": 900,
    "export_graph": 489,
    "search_nodes": 1120,
    "select_symbols": 1677,
    "describe_formats": 178,
    "describe_ontology": 253,
    "describe_frontends": 179,
    "describe_traversal": 586,
    "compile_context": 1366,
    "repair_context": 357,
    "graph_change": 349,
    "memory_context": 562,
    "graph_at_time": 276,
}


class McpMachineContractTest(unittest.TestCase):
    def test_names_and_schema_constraints_are_stable(self) -> None:
        self.assertEqual(tuple(tool["name"] for tool in TOOLS), TOOL_NAMES)
        snapshot = tool_schema_snapshot(TOOLS)
        self.assertEqual(
            {name: contract["required"] for name, contract in snapshot.items() if contract["required"]},
            {
                "plan_context": ("query_class",),
                "final_packet": ("query_class", "starts"),
                "query_context": ("query",),
                "query_relations": ("target", "direction"),
                "update_graph_files": ("paths",),
                "remove_graph_files": ("paths",),
                "search_nodes": ("query",),
                "select_symbols": ("predicate",),
                "compile_context": ("query",),
                "repair_context": ("issue",),
                "graph_change": ("before_path", "after_path"),
                "memory_context": ("operation",),
                "graph_at_time": ("timestamp",),
            },
        )
        self.assertEqual(
            {name: contract["enums"] for name, contract in snapshot.items() if contract["enums"]},
            {
                "plan_context": {"query_class": QUERY_CLASSES},
                "final_packet": {"query_class": QUERY_CLASSES, "packet": PACKET_FORMATS},
                "query_context": {
                    "query_class": ("auto", *QUERY_CLASSES),
                    "packet": PACKET_FORMATS,
                    "scope_mode": ("strict", "expand"),
                    "source_mode": ("auto", "off", "all"),
                    "depth": ("files", "symbols"),
                    "frontend": ("auto", "regex", "tree_sitter"),
                    "sync": ("none", "git"),
                },
                "query_relations": {
                    "direction": ("callers", "callees"),
                    "format": ("micro", "detailed"),
                    "sync": ("none", "git"),
                },
                "build_graph": {
                    "depth": ("files", "symbols"),
                    "frontend": ("auto", "regex", "tree_sitter"),
                },
                "update_graph_files": {
                    "depth": ("files", "symbols"),
                    "frontend": ("auto", "regex", "tree_sitter"),
                },
                "remove_graph_files": {
                    "depth": ("files", "symbols"),
                    "frontend": ("auto", "regex", "tree_sitter"),
                },
                "select_symbols": {"mode": ("select", "count", "exists")},
                "describe_traversal": {"query_class": QUERY_CLASSES},
                "compile_context": {
                    "query_class": ("auto", *QUERY_CLASSES),
                    "packet": PACKET_FORMATS,
                },
                "memory_context": {"operation": ("add", "query", "list")},
            },
        )
        self.assertEqual(
            {name: contract["defaults"] for name, contract in snapshot.items() if contract["defaults"]},
            {
                "query_context": {"query_class": "auto"},
                "query_relations": {
                    "limit": 20,
                    "include_tests": False,
                    "format": "micro",
                    "sync": "none",
                },
                "compile_context": {"query_class": "auto", "packet": "gg"},
                "repair_context": {"max_nodes": 30, "hops": 2},
                "graph_change": {"impact_hops": 2},
                "memory_context": {
                    "store_path": ".graphgraph/memory.json",
                    "kind": "fact",
                    "limit": 10,
                },
            },
        )

    def test_routing_and_safety_cues_survive_compaction(self) -> None:
        descriptions = {tool["name"]: tool["description"].lower() for tool in TOOLS}
        self.assertTrue(all(description.startswith("act:") for description in descriptions.values()))
        self.assertFalse(
            any("description" in spec for tool in TOOLS for spec in tool["inputSchema"].get("properties", {}).values())
        )
        cues = {
            "query_context": ("natural-language", "node ids"),
            "query_relations": ("one-hop", "complete_within_graph"),
            "final_packet": ("starts", "packet"),
            "source_snippets": ("source", "code lines"),
            "project_status": ("status", "validity"),
            "repair_context": ("error", "repair"),
            "graph_change": ("before/after", "blast radius"),
            "memory_context": ("memory", "add"),
            "graph_at_time": ("timestamp", "graph"),
        }
        for tool, required_cues in cues.items():
            for cue in required_cues:
                self.assertIn(cue, descriptions[tool], (tool, cue))

        safety = {
            "full_graph": ("every", "max_tokens", "not the default"),
            "update_graph_files": ("exactly", "prior"),
            "remove_graph_files": ("removed", "prior"),
            "build_graph": ("exclusions",),
            "select_symbols": ("caller_evidence_complete", "upper bound"),
            "query_relations": ("call_topology_status",),
        }
        for tool, required_cues in safety.items():
            for cue in required_cues:
                self.assertIn(cue, descriptions[tool], (tool, cue))

    def test_pre_compaction_size_baseline_is_recorded_per_tool(self) -> None:
        receipt = tool_contract_size_receipt(TOOLS)
        self.assertEqual(receipt["tools"], 23)
        self.assertLessEqual(receipt["aggregate_chars"], MACHINE_CONTRACT_CHAR_CEILING)
        self.assertLessEqual(receipt["proxy_tokens"], 2_600)
        for name, baseline in BASELINE_TOOL_CHARS.items():
            self.assertLessEqual(receipt["per_tool_chars"][name], baseline, name)

    def test_public_result_envelope_and_representative_json_shapes(self) -> None:
        listed = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert listed is not None
        self.assertEqual(tuple(tool["name"] for tool in listed["result"]["tools"]), TOOL_NAMES)

        planned = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "plan_context",
                    "arguments": {"query_class": "blast_radius"},
                },
            }
        )
        assert planned is not None
        content = planned["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertNotIn("\n", content[0]["text"])
        self.assertNotIn(": ", content[0]["text"])
        payload = json.loads(content[0]["text"])
        self.assertTrue({"hops", "packet", "reason"} <= payload.keys())

        with self.assertRaisesRegex(ValueError, "query_class.*blast_radius"):
            handle_tools_call({"name": "plan_context", "arguments": {"query": "impact"}})


if __name__ == "__main__":
    unittest.main()
