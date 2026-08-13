"""Public-interface characterization for the private retrieval phases."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph import Edge, Graph, Node
from graphgraph.io import save_graph
from graphgraph.retrieval import retrieve_context
from graphgraph.services.compiler_driver import CompilerDriver, DriverRequest


def _graph() -> Graph:
    nodes = {
        "run": Node("run", "run", "function", "src/app.py", summary="Run the application."),
        "sink": Node("sink", "sink", "function", "src/app.py", summary="Receive output."),
        "other": Node("other", "other", "function", "src/other.py", summary="Other helper."),
    }
    for index in range(10):
        nodes[f"f{index}"] = Node(
            f"f{index}", f"helper_{index}", "function", "src/helpers.py", summary=f"Utility {index}."
        )
    return Graph(nodes=nodes, edges=[Edge("run", "sink", "calls")])


class RetrievalPhaseCharacterizationTest(unittest.TestCase):
    def test_feasibility_terminal_preserves_abstention_result(self) -> None:
        result = retrieve_context(_graph(), "kubernetes grpc teleport relay", "direct_lookup", 2)

        self.assertEqual(result.starts, ())
        self.assertEqual(result.nodes, set())
        self.assertEqual(result.edges, [])
        self.assertEqual(result.metadata["answerability"]["status"], "unanswerable")
        self.assertTrue(result.metadata["answerability"]["abstained"])

    def test_exact_ranked_and_source_anchor_routes_remain_observable(self) -> None:
        graph = _graph()

        exact = retrieve_context(graph, "run", "direct_lookup", 1)
        ranked = retrieve_context(graph, "application output", "direct_lookup", 1)
        sourced = retrieve_context(graph, "application output", "direct_lookup", 1, seed_ids=("other",))

        self.assertEqual(exact.metadata["anchor_strategy"], "exact_fast_path")
        self.assertEqual(ranked.metadata["anchor_strategy"], "ranked")
        self.assertEqual(sourced.starts[0], "other")
        self.assertEqual(sourced.matches[0].reasons, ("source_planner",))

    def test_public_compile_preserves_assembled_result_and_receipt(self) -> None:
        graph = _graph()
        result = retrieve_context(graph, "run", "direct_lookup", 1)
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.gg"
            save_graph(graph, graph_path)
            packet, _status = CompilerDriver().compile(
                DriverRequest(query="run", query_class="direct_lookup", graph_path=graph_path, json_output=True)
            )
            payload = json.loads(packet)

        self.assertEqual(result.starts, ("run",))
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in result.edges], [("run", "sink", "calls")])
        self.assertIn("run", payload["packet"])
        self.assertEqual(payload["retrieval"]["answerability"]["status"], result.metadata["answerability"]["status"])


if __name__ == "__main__":
    unittest.main()
