from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

from graphgraph import Edge, Graph, Node
from graphgraph.cli.parser import build_parser
from graphgraph.io import save_graph
from graphgraph.mcp import dispatch
from graphgraph.platform.service import create_server


def _graph() -> Graph:
    return Graph(
        nodes={
            "app": Node("app", "app.py", "python", "src/app.py"),
            "run": Node("run", "run", "function", "src/app.py"),
            "db": Node("db", "database_adapter", "class", "src/db.py"),
        },
        edges=(Edge("app", "run", "contains"), Edge("run", "db", "calls")),
    )


def _receipt_projection(payload: dict[str, object]) -> dict[str, object]:
    receipt = payload["receipt"]
    assert isinstance(receipt, dict)
    return {
        key: receipt[key]
        for key in (
            "query_class",
            "packet",
            "passes",
            "nodes",
            "edges",
            "valid",
            "structural_validation",
            "semantic_validation",
            "answerability",
            "source_receipt",
        )
    }


class RuntimeFactoryParityTest(unittest.TestCase):
    def test_cli_mcp_and_http_compile_the_same_program(self) -> None:
        query = "blast radius of database_adapter"
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(_graph(), graph_path)

            args = build_parser().parse_args(
                [
                    "platform",
                    "compile",
                    query,
                    "--graph",
                    str(graph_path),
                    "--query-class",
                    "direct_lookup",
                    "--packet",
                    "gg",
                    "--pass",
                    "hierarchy",
                    "--max-nodes",
                    "20",
                ]
            )
            output = io.StringIO()
            with redirect_stdout(output):
                args.func(args)
            cli = json.loads(output.getvalue())

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "compile_context",
                        "arguments": {
                            "query": query,
                            "graph_path": str(graph_path),
                            "query_class": "direct_lookup",
                            "packet": "gg",
                            "passes": ["hierarchy"],
                            "max_nodes": 20,
                        },
                    },
                }
            )
            assert response is not None
            mcp = json.loads(response["result"]["content"][0]["text"])

            server = create_server(graph_path, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/query",
                    data=json.dumps(
                        {
                            "query": query,
                            "query_class": "direct_lookup",
                            "packet": "gg",
                            "passes": ["hierarchy"],
                            "max_nodes": 20,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as http_response:
                    http = json.loads(http_response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(_receipt_projection(cli), _receipt_projection(mcp))
        self.assertEqual(_receipt_projection(mcp), _receipt_projection(http))
        self.assertEqual(cli["packet"], mcp["packet"])
        self.assertEqual(mcp["packet"], http["packet"])

    def test_factory_owns_runtime_dependencies_and_defaults(self) -> None:
        from graphgraph.platform.runtime import create_graph_runtime

        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            graph = _graph()
            save_graph(graph, graph_path)

            runtime = create_graph_runtime(graph_path, graph=graph)

        self.assertEqual(runtime.source_mode, "auto")
        self.assertEqual(runtime.memory_scopes, ("project", "session"))
        self.assertEqual(
            tuple(capability["name"] for capability in runtime.providers.capabilities()),
            ("structural", "cpg"),
        )
        self.assertIsNotNone(runtime.evidence_store)
        self.assertIsNotNone(runtime.source_planner)


if __name__ == "__main__":
    unittest.main()
