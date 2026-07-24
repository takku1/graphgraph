from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.io.core import save_graph
from graphgraph.retrieval.context import retrieve_context
from graphgraph.retrieval.subsystems import build_subsystem_map, subsystem_for_path
from graphgraph.services.context import render_query_context


class SubsystemMapTest(unittest.TestCase):
    def test_source_layout_defines_subsystems(self) -> None:
        self.assertEqual(subsystem_for_path("src/graphgraph/retrieval/context.py"), "retrieval")
        self.assertEqual(subsystem_for_path("src/graphgraph/core.py"), "graphgraph")
        self.assertEqual(subsystem_for_path("crates/locus-engine/src/lib.rs"), "locus-engine")
        self.assertIsNone(subsystem_for_path("tests/test_retrieval.py"))
        self.assertIsNone(subsystem_for_path("benchmarks/context_graph/shape.py"))
        self.assertIsNone(subsystem_for_path("scripts/rebuild_graph.py"))

    def test_map_is_deterministic_and_centrality_selects_api(self) -> None:
        nodes = {
            "scan": Node("scan", "scan", "function", "src/pkg/scanner/api.py"),
            "helper": Node("helper", "_helper", "function", "src/pkg/scanner/helpers.py"),
            "parse": Node("parse", "parse", "function", "src/pkg/scanner/parser.py"),
            "retrieve": Node("retrieve", "retrieve_context", "function", "src/pkg/retrieval/context.py"),
            "test": Node("test", "test_scan", "function", "tests/test_scanner.py"),
        }
        graph = Graph(
            nodes=nodes,
            edges=[
                Edge("helper", "scan", "calls"),
                Edge("parse", "scan", "calls"),
                Edge("retrieve", "scan", "calls"),
            ],
        )

        first = build_subsystem_map(graph)
        second = build_subsystem_map(graph)

        self.assertEqual(first, second)
        by_name = {row["subsystem"]: row for row in first["subsystems"]}
        self.assertEqual(by_name["scanner"]["api"][0], "scan")
        self.assertEqual(by_name["scanner"]["n"], 3)
        self.assertNotIn("tests", by_name)

    def test_broad_architecture_query_gets_map_but_narrow_summary_does_not(self) -> None:
        graph = Graph(
            nodes={
                "retrieval": Node(
                    "retrieval",
                    "retrieve_context",
                    "function",
                    "src/graphgraph/retrieval/context.py",
                )
            }
        )
        broad = retrieve_context(
            graph,
            "what are the main subsystems and what does each do",
            "subsystem_summary",
            hops=0,
        )
        narrow = retrieve_context(
            graph,
            "how does retrieve_context work",
            "subsystem_summary",
            hops=0,
        )

        self.assertIn("subsystem_map", broad.metadata)
        self.assertNotIn("subsystem_map", narrow.metadata)


class SubsystemMapTransportTest(unittest.TestCase):
    """The map must reach the agent-facing payload, not just retrieval metadata.

    Compact JSON keeps only `actionable`, so the map has to live there or it is
    silently dropped before the agent ever sees it (the reported regression).
    """

    def _graph(self) -> Graph:
        return Graph(
            nodes={
                "retrieve": Node("retrieve", "retrieve_context", "function",
                                 "src/graphgraph/retrieval/context.py"),
                "search": Node("search", "search_nodes", "function",
                               "src/graphgraph/retrieval/search.py"),
                "scan": Node("scan", "scan_directory", "function",
                             "src/graphgraph/scanner/core.py"),
                "save": Node("save", "save_graph", "function",
                             "src/graphgraph/io/core.py"),
            },
            edges=[
                Edge("scan", "save", "calls"),
                Edge("retrieve", "search", "calls"),
            ],
        )

    def test_broad_query_surfaces_map_in_actionable_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(self._graph(), path)
            payload = json.loads(render_query_context(
                query="what are the main subsystems and what does each do",
                query_class="subsystem_summary",
                graph_path=path,
                json_anchors=True,
                show_anchors=True,
            ))
        # `actionable` is the one key compact JSON preserves verbatim.
        subsystem_map = payload["actionable"].get("subsystem_map")
        self.assertIsNotNone(subsystem_map)
        names = {row["subsystem"] for row in subsystem_map["subsystems"]}
        self.assertIn("retrieval", names)
        self.assertIn("scanner", names)

    def test_narrow_query_does_not_carry_a_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg"
            save_graph(self._graph(), path)
            payload = json.loads(render_query_context(
                query="how does retrieve_context work",
                query_class="direct_lookup",
                graph_path=path,
                json_anchors=True,
                show_anchors=True,
            ))
        self.assertNotIn("subsystem_map", payload["actionable"])


if __name__ == "__main__":
    unittest.main()
