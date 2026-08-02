from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph import Edge, Graph, Node
from graphgraph.io import save_graph
from graphgraph.mcp import dispatch
from graphgraph.packets import validate_packet
from graphgraph.planning.query_compiler import QueryOperator, compile_query
from graphgraph.services.query import execute_query


class QueryCompilerTest(unittest.TestCase):
    def test_exact_callers_query_uses_relation_operator(self) -> None:
        plan = compile_query("what calls render_query_context")

        self.assertEqual(plan.operator, QueryOperator.RELATIONS)
        self.assertEqual(plan.arguments["target"], "render_query_context")
        self.assertEqual(plan.arguments["direction"], "callers")
        self.assertEqual(plan.cost_class, "indexed_one_hop")
        self.assertFalse(plan.mutating)

    def test_exact_callees_query_uses_relation_operator(self) -> None:
        plan = compile_query("what does GraphRuntime::compile call?")

        self.assertEqual(plan.operator, QueryOperator.RELATIONS)
        self.assertEqual(plan.arguments["target"], "GraphRuntime::compile")
        self.assertEqual(plan.arguments["direction"], "callees")

    def test_compound_relation_and_test_query_stays_in_context(self) -> None:
        plan = compile_query(
            "what calls render_query_context and which tests should run if it changes?"
        )

        self.assertEqual(plan.operator, QueryOperator.CONTEXT)
        self.assertIn("compound", " ".join(plan.reasons))

    def test_typed_predicate_dsl_uses_select_only_after_validation(self) -> None:
        plan = compile_query(
            "production_callers = 0 and path contains src and include_tests = false",
            result_mode="count",
        )

        self.assertEqual(plan.operator, QueryOperator.SELECT)
        self.assertEqual(plan.arguments["mode"], "count")

    def test_unsupported_predicate_like_prose_does_not_silently_approximate(self) -> None:
        plan = compile_query("how many important functions look unused?")

        self.assertEqual(plan.operator, QueryOperator.CONTEXT)
        self.assertNotIn("predicate", plan.arguments)

    def test_status_question_uses_status_operator(self) -> None:
        plan = compile_query("is the project graph fresh and healthy?")

        self.assertEqual(plan.operator, QueryOperator.STATUS)

    def test_mutation_language_never_compiles_to_a_mutating_operator(self) -> None:
        plan = compile_query("delete the graph and rebuild everything")

        self.assertFalse(plan.mutating)
        self.assertEqual(plan.operator, QueryOperator.CONTEXT)

    def test_explicit_context_override_wins(self) -> None:
        plan = compile_query("what calls render_query_context", mode="context")

        self.assertEqual(plan.operator, QueryOperator.CONTEXT)
        self.assertEqual(plan.confidence, 1.0)

    def test_execute_query_dispatches_exact_relation_and_exposes_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.gg"
            graph_path.parent.mkdir()
            save_graph(
                Graph(
                    nodes={
                        "CALLER": Node("CALLER", "caller", "function", "src/a.py"),
                        "TARGET": Node("TARGET", "target", "function", "src/b.py"),
                    },
                    edges=[Edge("CALLER", "TARGET", "calls")],
                ),
                graph_path,
            )

            response = execute_query(
                "what calls target", directory=root, graph_path=graph_path
            )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["operator"], "relations")
        self.assertFalse(response["receipt"]["mutating"])
        self.assertEqual(response["result"]["r"]["returned"], 1)

    def test_execute_query_missing_graph_returns_action_without_building(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            response = execute_query("how does auth work?", directory=root)

            self.assertEqual(response["status"], "needs_index")
            self.assertTrue(response["action"]["requires_explicit_execution"])
            self.assertFalse(response["receipt"]["mutating"])
            self.assertFalse((root / ".graphgraph").exists())

    def test_mcp_query_is_registered_and_dispatches(self) -> None:
        listed = dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        self.assertIsNotNone(listed)
        tools = listed["result"]["tools"]
        query_tool = next(tool for tool in tools if tool["name"] == "query")
        self.assertEqual(query_tool["inputSchema"]["required"], ["query"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "query",
                        "arguments": {"query": "how does auth work?", "directory": str(root)},
                    },
                }
            )
        self.assertIsNotNone(response)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "needs_index")

    def test_context_query_selects_minimum_safe_rendered_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.gg"
            graph_path.parent.mkdir()
            save_graph(
                Graph(
                    nodes={
                        "FILE": Node("FILE", "module.py", "python", "module.py"),
                        "TARGET": Node("TARGET", "target", "function", "module.py"),
                    },
                    edges=[Edge("FILE", "TARGET", "contains")],
                ),
                graph_path,
            )

            response = execute_query(
                "target",
                directory=root,
                graph_path=graph_path,
                mode="context",
                query_class="direct_lookup",
            )

        context = response["result"]
        selection = context["retrieval"]["format_selection"]
        self.assertEqual(selection["chosen_tokens"], selection["minimum_tokens"])
        self.assertLessEqual(selection["ratio_to_minimum"], 1.05)
        self.assertTrue(validate_packet(context["packet"]).ok)


if __name__ == "__main__":
    unittest.main()
