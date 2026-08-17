from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphgraph import Graph, Node
from graphgraph.benchmark.resident_query import (
    REQUIRED_SESSION_TOOLS,
    SESSION_EXACT_P95_TARGET_MS,
    quantile,
    session_tool_names,
)
from graphgraph.io import clear_graph_cache, load_any, save_graph
from graphgraph.mcp import dispatch


class QuantileTest(unittest.TestCase):
    def test_nearest_rank_p95_is_monotonic(self) -> None:
        samples = [float(i) for i in range(1, 21)]
        self.assertLessEqual(quantile(samples, 0.5), quantile(samples, 0.95))
        self.assertEqual(quantile([3.0], 0.95), 3.0)

    def test_empty_samples_raise(self) -> None:
        with self.assertRaises(ValueError):
            quantile([], 0.95)


class SessionCatalogTest(unittest.TestCase):
    def test_initialize_then_tools_list_exposes_retrieval_tools(self) -> None:
        names = session_tool_names()
        for tool in REQUIRED_SESSION_TOOLS:
            self.assertIn(tool, names, tool)
        hello = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert hello is not None
        self.assertIn("tools", hello["result"]["capabilities"])


class WarmGraphReuseTest(unittest.TestCase):
    def test_second_load_of_the_same_path_reuses_the_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            save_graph(Graph(nodes={"F": Node("F", "login", "function", "a.py")}), path)
            clear_graph_cache()
            first = load_any(path)
            second = load_any(path)
            self.assertIs(first, second)


class ResidentSloTest(unittest.TestCase):
    def test_session_slo_is_a_positive_bound(self) -> None:
        self.assertGreater(SESSION_EXACT_P95_TARGET_MS, 0.0)
        self.assertLessEqual(SESSION_EXACT_P95_TARGET_MS, 1000.0)
