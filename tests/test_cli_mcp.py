from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
)
from graphgraph.io import (
    save_graph,
)
from graphgraph.mcp_server import dispatch
from graphgraph.packets import (
    render_gg_max,
)
from graphgraph.scanner import scan_directory
from graphgraph.services.native import graph_shape, render_native_context
from graphgraph.validate import validate_graph_json


class CliMcpTest(unittest.TestCase):
    def test_mcp_plan_context(self) -> None:
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "plan_context", "arguments": {"query_class": "blast_radius"}},
            }
        )
        assert response is not None
        text = response["result"]["content"][0]["text"]
        self.assertIn('"hops": 2', text)
        self.assertIn('"packet": "gg_max"', text)

    def test_mcp_plan_context_direct_lookup(self) -> None:
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "plan_context", "arguments": {"query_class": "direct_lookup"}},
            }
        )
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        self.assertEqual(data["packet"], "gg_max")
        self.assertEqual(data["hops"], 1)

    def test_mcp_describe_formats(self) -> None:
        response = dispatch(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "describe_formats", "arguments": {}}}
        )
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        formats = [f["format"] for f in data]
        self.assertIn("gg_max", formats)
        self.assertIn("sql", formats)
        self.assertIn("semantic_arrow", formats)

    def test_mcp_describe_ontology(self) -> None:
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {"name": "describe_ontology", "arguments": {"family": "execution"}},
            }
        )
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(data[0]["name"], "calls")
        self.assertEqual(data[0]["family"], "execution")

    def test_mcp_describe_frontends(self) -> None:
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 32,
                "method": "tools/call",
                "params": {"name": "describe_frontends", "arguments": {}},
            }
        )
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("regex", {item["name"] for item in data})

    def test_mcp_describe_traversal(self) -> None:
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 33,
                "method": "tools/call",
                "params": {"name": "describe_traversal", "arguments": {"query_class": "blast_radius"}},
            }
        )
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(data["query_class"], "blast_radius")
        self.assertIn("calls", data["preferred_relations"])

    def test_mcp_validate_packet(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_gg_max(graph, nodes, edges)
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "validate_packet", "arguments": {"packet": packet}},
            }
        )
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["format"], "gg_max")

    def test_mcp_validate_packet_falls_back_to_graph_file_when_packet_omitted(self) -> None:
        # Regression: the MCP validate_packet tool required `packet` and could
        # only validate rendered packet text, unlike `graphgraph validate`
        # (CLI), which auto-detects and validates the saved graph JSON when no
        # packet/stdin is given. An agent using only MCP tools had no way to
        # validate a raw saved graph file at all -- a real capability gap
        # between the CLI and MCP surfaces for the same underlying feature.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            save_graph(sample_graph(), graph_path)
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "validate_packet", "arguments": {"graph_path": str(graph_path)}},
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(data["ok"], data)
            self.assertGreater(data["node_count"], 0)

    def test_mcp_search_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "N1", "label": "AuthService", "kind": "service", "path": "server/auth.py"},
                            {"id": "N2", "label": "TokenStore", "kind": "data", "path": "server/tokens.py"},
                        ],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "search_nodes", "arguments": {"query": "auth", "graph_path": str(graph_path)}},
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            ids = [m["id"] for m in data["matches"]]
            self.assertIn("N1", ids)
            self.assertNotIn("N2", ids)

    def test_mcp_search_nodes_returns_line_number_directly(self) -> None:
        # search_nodes previously returned only path, never the line number,
        # even though the scanner already records it (encoded as an "L<N>"
        # token in node.summary) -- an agent had to make a separate
        # source_snippets round-trip just to learn where in the file a match
        # actually was. Now search_nodes surfaces `line` directly via the new
        # Node.line property, so one call answers "where is X" completely.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def unrelated():\n    pass\n\n\ndef find_this_function():\n    return 1\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.gg"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            graph = scan_directory(root, depth="symbols", frontend="regex")
            save_graph(graph, graph_path)

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {
                        "name": "search_nodes",
                        "arguments": {"query": "find_this_function", "graph_path": str(graph_path)},
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            match = next(m for m in data["matches"] if m["label"] == "find_this_function")
            self.assertEqual(match["line"], 5)

    def test_mcp_search_nodes_reports_score_gap_confidence_signal(self) -> None:
        # New: search_nodes now reports top_score_gap_ratio (top match's score
        # / runner-up's) and a provisional `ambiguous` flag, so a caller can
        # tell a single dominant answer apart from several genuinely tied
        # candidates instead of silently trusting whichever happened to sort
        # first. Verified empirically against this project: exact-symbol-style
        # queries produced ratios >= ~1.8-3x; queries matching several equally
        # generic nodes produced ratios near 1.0.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Case 1: one node is an exact label match, the other only a weak
            # partial match -- should NOT be ambiguous.
            clear_graph = root / "clear.json"
            clear_graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "N1", "label": "resolve_modified_node_ids", "kind": "function", "path": "a.py"},
                            {"id": "N2", "label": "resolve_start_nodes", "kind": "function", "path": "b.py"},
                        ],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            resp = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "search_nodes",
                        "arguments": {"query": "resolve_modified_node_ids", "graph_path": str(clear_graph)},
                    },
                }
            )
            data = json.loads(resp["result"]["content"][0]["text"])
            self.assertFalse(data["ambiguous"], data)
            self.assertIsNotNone(data["top_score_gap_ratio"])
            self.assertGreater(data["top_score_gap_ratio"], 1.3)

            # Case 2: two nodes share the exact same label -- genuinely tied,
            # should BE ambiguous (ratio == 1.0).
            tied_graph = root / "tied.json"
            tied_graph.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "N1", "label": "Widget", "kind": "class", "path": "a.py"},
                            {"id": "N2", "label": "Widget", "kind": "class", "path": "b.py"},
                        ],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            resp2 = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "search_nodes", "arguments": {"query": "widget", "graph_path": str(tied_graph)}},
                }
            )
            data2 = json.loads(resp2["result"]["content"][0]["text"])
            self.assertTrue(data2["ambiguous"], data2)
            self.assertEqual(data2["top_score_gap_ratio"], 1.0)

    def test_cmd_scan_refuses_invalid_graph_without_overwrite(self) -> None:
        from graphgraph.cli.commands import cmd_scan

        class Args:
            directory = "."
            output = ""
            incremental = True
            skip_dirs = []
            exclude_dirs = []
            max_nodes = 2000
            generic_mentions = False
            depth = "symbols"
            frontend = "regex"
            docs = True
            history = False

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            save_graph(sample_graph(), graph_path)
            before = graph_path.read_text(encoding="utf-8")
            bad_graph = Graph(nodes={"A": Node("A", "A")}, edges=[Edge("A", "B", "calls")])
            args = Args()
            args.directory = str(root)
            args.output = str(graph_path)

            with patch("graphgraph.services.native.scan_directory", return_value=bad_graph):
                with self.assertRaisesRegex(ValueError, "Refusing to write invalid graph JSON"):
                    cmd_scan(args)

            self.assertEqual(graph_path.read_text(encoding="utf-8"), before)

    def test_scan_validated_graph_repairs_invalid_incremental_scan(self) -> None:
        from graphgraph.services.native import scan_validated_graph

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            bad_graph = Graph(nodes={"A": Node("A", "A")}, edges=[Edge("A", "B", "calls")])
            clean_graph = sample_graph()

            with patch("graphgraph.services.native.scan_directory", side_effect=[bad_graph, clean_graph]):
                status = scan_validated_graph(directory=root, output_path=graph_path, incremental=True)

            self.assertTrue(status.repaired)
            self.assertTrue(graph_path.exists())
            result = validate_graph_json(graph_path.read_text(encoding="utf-8"))
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.node_count, 3)

    def test_mcp_query_context_without_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 55,
                    "method": "tools/call",
                    "params": {
                        "name": "query_context",
                        "arguments": {
                            "query": "auth service",
                            "query_class": "blast_radius",
                            "graph_path": str(graph_path),
                            "show_anchors": True,
                        },
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["anchors"][0]["id"], "N1")
            self.assertIn("[e]", data["packet"])

    def test_mcp_query_context_honors_hops_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 56,
                    "method": "tools/call",
                    "params": {
                        "name": "query_context",
                        "arguments": {
                            "query": "auth service",
                            "query_class": "blast_radius",
                            "graph_path": str(graph_path),
                            "hops": 0,
                            "show_anchors": True,
                        },
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["anchors"][0]["id"], "N1")
            self.assertIn("AuthService", data["packet"])
            self.assertNotIn("N2: TokenStore", data["packet"])

    def test_mcp_source_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir(parents=True)
            source.write_text("def login():\n    return 'ok'\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            save_graph(Graph(nodes={"F": Node("F", "login", "function", "src/auth.py", summary="L1")}), graph_path)

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 57,
                    "method": "tools/call",
                    "params": {
                        "name": "source_snippets",
                        "arguments": {
                            "graph_path": str(graph_path),
                            "starts": ["login"],
                            "context_lines": 0,
                            "max_lines": 3,
                        },
                    },
                }
            )
            assert response is not None
            text = response["result"]["content"][0]["text"]
            self.assertIn("## login (F)", text)
            self.assertIn("1 | def login():", text)

    def test_mcp_build_graph_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a small Python package
            (root / "main.py").write_text("from utils import helper\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            output = root / "graph.json"
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "build_graph",
                        "arguments": {
                            "directory": str(root),
                            "output_path": str(output),
                        },
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["action"], "scanned")
            self.assertGreaterEqual(data["nodes"], 2)
            self.assertTrue(output.exists())

    def test_python_module_cli_entrypoint_runs(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "graphgraph.cli", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("graphgraph", proc.stdout)

    def test_native_context_builds_graph_and_skips_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "evidence").mkdir()
            (root / "src" / "app.py").write_text("def run_context():\n    return 'ok'\n", encoding="utf-8")
            (root / "evidence" / "old_status.md").write_text("# Generated status\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"

            packet, status = render_native_context(
                query="run context",
                directory=root,
                graph_path=graph_path,
                rebuild=False,
                query_class="direct_lookup",
                max_nodes=20,
            )

            self.assertTrue(status.built)
            self.assertTrue(graph_path.exists())
            self.assertIn("run_context", packet)
            paths = {node.path for node in status.graph.nodes.values()}
            self.assertIn("src/app.py", paths)
            self.assertNotIn("evidence/old_status.md", paths)
            shape = graph_shape(status.graph)
            self.assertGreaterEqual(shape["source_nodes"], 1)

            packet2, status2 = render_native_context(
                query="run context",
                directory=root,
                graph_path=graph_path,
                rebuild=False,
                query_class="direct_lookup",
                max_nodes=20,
            )
            self.assertFalse(status2.built)
            self.assertEqual(packet2, packet)

            (root / "src" / "app.py").write_text("def run_context_clean():\n    return 'ok'\n", encoding="utf-8")
            packet3, status3 = render_native_context(
                query="run context clean",
                directory=root,
                graph_path=graph_path,
                rebuild=True,
                query_class="direct_lookup",
                max_nodes=20,
            )
            self.assertTrue(status3.built)
            self.assertIn("run_context_clean", packet3)
            self.assertNotIn("run_context():", packet3)

    def test_project_status_reports_validation_package_and_runtime_hint(self) -> None:
        from graphgraph.services.native import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "featherwaight").mkdir(parents=True)
            (root / "src" / "featherwaight" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\n"
                'name = "featherwaight"\n'
                'version = "0.1.0"\n'
                "[project.scripts]\n"
                'featherwaight = "featherwaight.cli:main"\n',
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(Graph(nodes={"P": Node("P", "package", "python", "src/featherwaight/__init__.py")}), graph_path)

            report = build_project_status(directory=root, graph_path=graph_path, run_probes=True)

            self.assertTrue(report["graph"]["validation"]["ok"])
            self.assertEqual(report["package"]["name"], "featherwaight")
            self.assertEqual(report["package"]["module"], "featherwaight")
            self.assertTrue(report["package"]["src_layout"])
            self.assertIn("PYTHONPATH=src", report["package"]["import_hint"])
            probes = {probe["name"]: probe for probe in report["runtime_probes"]}
            self.assertFalse(probes["raw_import"]["ok"])
            self.assertTrue(probes["src_import"]["ok"])
            self.assertIn("script_target_import:featherwaight", probes)
            self.assertFalse(probes["raw_module_help"]["ok"])
            self.assertTrue(any("PYTHONPATH includes src" in note for note in report["runtime_notes"]))

    def test_mcp_project_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(sample_graph(), graph_path)
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 16,
                    "method": "tools/call",
                    "params": {
                        "name": "project_status",
                        "arguments": {
                            "directory": str(root),
                            "graph_path": str(graph_path),
                        },
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(data["graph"]["validation"]["ok"])
            self.assertEqual(data["graph"]["shape"]["nodes"], 3)

    def test_cli_stdio_handles_unicode_on_cp1252_streams(self) -> None:
        import io
        import sys

        from graphgraph.cli import _configure_stdio

        original_stdout = sys.stdout
        raw = io.BytesIO()
        fake_stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        try:
            sys.stdout = fake_stdout
            _configure_stdio()
            print("query_context -> anchors -> packet")
            print("query_context \u2192 anchors \u2192 packet")
            sys.stdout.flush()
        finally:
            sys.stdout = original_stdout
            fake_stdout.detach()

    def test_cli_validate_empty_packet_exits_nonzero(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "graphgraph", "validate"],
            input="@nodes\n\n@edges\n",
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL semantic_arrow nodes=0 edges=0", proc.stdout)
        self.assertIn("empty packet: no nodes", proc.stdout)

    def test_cli_final_bad_start_exits_cleanly(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graphgraph",
                    "final",
                    "--graph",
                    str(graph_path),
                    "--query-class",
                    "blast_radius",
                    "--starts",
                    "totally_bogus_id",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("Error: No graph nodes matched the requested starts", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_local_context_validate_snippets_smoke_without_provider_keys(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        for name in (
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "PREFERRED_PROVIDER",
            "OPENAI_BASE_URL",
            "RUN_OPENAI_REASONING_EVAL",
            "RUN_GEMINI_REASONING_EVAL",
        ):
            env.pop(name, None)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "app.py").write_text(
                "class AlphaService:\n"
                "    def call_beta(self):\n"
                "        return beta()\n\n"
                "def beta():\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )

            context_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graphgraph",
                    "context",
                    "AlphaService call_beta beta",
                    "--query-class",
                    "direct_lookup",
                    "--scan-max-nodes",
                    "100",
                    "--show-stats",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(context_proc.returncode, 0, context_proc.stderr)
            self.assertIn("[n]", context_proc.stdout)
            self.assertIn("GraphGraph context built:", context_proc.stderr)
            self.assertNotIn("API Key", context_proc.stdout + context_proc.stderr)

            validate_proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "validate"],
                cwd=tmp,
                input=context_proc.stdout,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(validate_proc.returncode, 0, validate_proc.stdout + validate_proc.stderr)
            self.assertIn("PASS", validate_proc.stdout)

            snippet_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "graphgraph",
                    "snippets",
                    "--starts",
                    "AlphaService",
                    "--max-lines",
                    "12",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(snippet_proc.returncode, 0, snippet_proc.stderr)
            self.assertIn("class AlphaService", snippet_proc.stdout)

    def test_doctor_marks_provider_keys_optional(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(name, None)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            gg_dir = tmp / ".graphgraph"
            gg_dir.mkdir()
            save_graph(sample_graph(), gg_dir / "graph.json")
            proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "doctor"],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[Optional External Benchmark Credentials]", proc.stdout)
        self.assertIn("Local GraphGraph scan/query/packet workflows do not require provider API keys.", proc.stdout)
        self.assertIn("OpenAI API Key: Not configured (OK; external OpenAI benchmarks will be skipped)", proc.stdout)
        self.assertNotIn("OpenAI API Key: Not found", proc.stdout)

    def test_cmd_install_project(self) -> None:
        import os

        from graphgraph.cli.commands import cmd_install

        class DummyArgs:
            project = True
            platform = "codex"

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cmd_install(DummyArgs())

                # Check workspace rules
                agents_md = Path(".agents") / "AGENTS.md"
                self.assertTrue(agents_md.exists())
                content = agents_md.read_text(encoding="utf-8")
                self.assertIn("# GraphGraph Workspace Rules", content)
                self.assertIn("One-step context packet", content)
                self.assertIn("graphgraph context", content)
                self.assertIn("Known-node packet only", content)
                self.assertIn("stable-skeleton", content)

                # Check skill
                skill_md = Path(".agents") / "skills" / "graphgraph" / "SKILL.md"
                self.assertTrue(skill_md.exists())
                skill_content = skill_md.read_text(encoding="utf-8")
                self.assertIn("name: graphgraph", skill_content)
                self.assertIn("query_context", skill_content)
                self.assertIn(
                    "| `direct_lookup` | Specific file/symbol details | 1 | `gg_max` | measured token floor |",
                    skill_content,
                )
                self.assertNotIn(
                    "| `direct_lookup` | Specific file/symbol details | 1 | `gg_max_hybrid`", skill_content
                )

                # Check complete Codex plugin bundle and marketplace.json
                plugin_json = Path("plugins") / "graphgraph" / ".codex-plugin" / "plugin.json"
                self.assertTrue(plugin_json.exists())
                plugin_data = json.loads(plugin_json.read_text(encoding="utf-8"))
                self.assertEqual(plugin_data["name"], "graphgraph")
                self.assertEqual(plugin_data["skills"], "./skills/")
                self.assertEqual(plugin_data["mcpServers"], "./.mcp.json")

                mcp_json = Path("plugins") / "graphgraph" / ".mcp.json"
                self.assertTrue(mcp_json.exists())
                mcp_data = json.loads(mcp_json.read_text(encoding="utf-8"))
                server = mcp_data["mcpServers"]["graphgraph"]
                # Codex plugin bundles are committed to git and consumed from many
                # clones/machines, so this must always be the portable form -- no
                # baked-in absolute path, no assumption that `uv` is on PATH.
                self.assertEqual(server, {"command": "graphgraph-mcp"})

                plugin_skill = Path("plugins") / "graphgraph" / "skills" / "graphgraph" / "SKILL.md"
                self.assertTrue(plugin_skill.exists())
                plugin_skill_content = plugin_skill.read_text(encoding="utf-8")
                self.assertIn("name: graphgraph", plugin_skill_content)
                self.assertIn(
                    "| `direct_lookup` | Specific file/symbol details | 1 | `gg_max` | measured token floor |",
                    plugin_skill_content,
                )

                marketplace_json = Path(".agents") / "plugins" / "marketplace.json"
                self.assertTrue(marketplace_json.exists())
                marketplace = json.loads(marketplace_json.read_text(encoding="utf-8"))
                entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "graphgraph")
                self.assertEqual(entry["source"]["path"], "./plugins/graphgraph")
                self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
                self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
            finally:
                os.chdir(orig_cwd)

    def test_cmd_install_claude_code_project(self) -> None:
        import os

        from graphgraph.cli.commands import cmd_install

        class DummyArgs:
            project = True
            platform = "claude-code"

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cmd_install(DummyArgs())

                # Project-scoped .mcp.json pinned to this checkout via uv --project
                mcp_json = Path(".mcp.json")
                self.assertTrue(mcp_json.exists())
                mcp_data = json.loads(mcp_json.read_text(encoding="utf-8"))
                server = mcp_data["mcpServers"]["graphgraph"]
                self.assertEqual(server["command"], "uv")
                self.assertIn("--project", server["args"])
                self.assertEqual(server["args"][-1], "graphgraph-mcp")

                # Claude Code skill file
                skill_md = Path(".claude") / "skills" / "graphgraph" / "SKILL.md"
                self.assertTrue(skill_md.exists())
                skill_content = skill_md.read_text(encoding="utf-8")
                self.assertIn("name: graphgraph", skill_content)
                self.assertIn("Claude Code", skill_content)
                self.assertIn("query_context", skill_content)

                # CLAUDE.md rule injection
                claude_md = Path("CLAUDE.md")
                self.assertTrue(claude_md.exists())
                claude_content = claude_md.read_text(encoding="utf-8")
                self.assertIn("# GraphGraph Workspace Rules", claude_content)
                self.assertIn("graphgraph/query_context", claude_content)

                # Codex plugin should NOT be written for a claude-code-only install
                self.assertFalse((Path("plugins") / "graphgraph").exists())
            finally:
                os.chdir(orig_cwd)

    def test_cmd_install_claude_code_idempotent(self) -> None:
        """Re-running install must not duplicate the injected CLAUDE.md rule block."""
        import os

        from graphgraph.cli.commands import cmd_install

        class DummyArgs:
            project = True
            platform = "claude-code"

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                cmd_install(DummyArgs())
                cmd_install(DummyArgs())

                claude_content = Path("CLAUDE.md").read_text(encoding="utf-8")
                self.assertEqual(claude_content.count("# GraphGraph Workspace Rules"), 1)
            finally:
                os.chdir(orig_cwd)

    def test_render_final_packet_injects_lessons(self) -> None:
        from graphgraph.core import Graph, Node
        from graphgraph.services import render_final_packet

        g = Graph(nodes={"A": Node("A", "AuthService", "service", "auth.py")}, edges=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            g_path = tmp / "graph.json"
            save_graph(g, g_path)

            # Write a dummy lessons file
            lessons_file = tmp / "lessons.md"
            lessons_file.write_text("Avoid exploring legacy routes", encoding="utf-8")

            # Mock find_lessons_path and find_graph_path
            import graphgraph.services.context as ctx

            orig_find_graph = ctx.find_graph_path
            orig_find_lessons = ctx.find_lessons_path
            ctx.find_graph_path = lambda: g_path
            ctx.find_lessons_path = lambda: lessons_file

            try:
                packet = render_final_packet(starts=["A"], query_class="direct_lookup")
                self.assertIn("LESSONS / PAST SESSION REFLECTIONS:", packet)
                self.assertIn("Avoid exploring legacy routes", packet)
            finally:
                ctx.find_graph_path = orig_find_graph
                ctx.find_lessons_path = orig_find_lessons

    def test_mcp_source_snippets_honors_explicit_zero_context_lines(self) -> None:
        """An explicit context_lines=0 (falsy but meaningful) must not fall back to the default of 4.

        handle_source_snippets used `int(args.get("context_lines") or 4)`, so a caller asking for
        "just the matched line, no surrounding context" (context_lines=0) silently got 4 lines of
        context instead -- a degraded packet with no error or explanation.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def login():\n    return 'ok'\n    # extra1\n    # extra2\n    # extra3\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            save_graph(Graph(nodes={"F": Node("F", "login", "function", "src/auth.py", summary="L1")}), graph_path)

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 58,
                    "method": "tools/call",
                    "params": {
                        "name": "source_snippets",
                        "arguments": {
                            "graph_path": str(graph_path),
                            "starts": ["login"],
                            "context_lines": 0,
                            "max_lines": 10,
                        },
                    },
                }
            )
            assert response is not None
            text = response["result"]["content"][0]["text"]
            self.assertIn("1 | def login():", text)
            self.assertNotIn("2 |", text)
            self.assertNotIn("extra1", text)

    def test_mcp_search_nodes_honors_explicit_zero_limit(self) -> None:
        """An explicit limit=0 must return zero matches, not fall back to the default of 20."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": "N1", "label": "AuthService", "kind": "service", "path": "server/auth.py"},
                        ],
                        "edges": [],
                    }
                ),
                encoding="utf-8",
            )
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 59,
                    "method": "tools/call",
                    "params": {
                        "name": "search_nodes",
                        "arguments": {"query": "auth", "graph_path": str(graph_path), "limit": 0},
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["matches"], [])

    def test_cli_missing_graph_exits_cleanly_without_traceback(self) -> None:
        """A missing .graphgraph/ (e.g. a fresh clone with no scan yet) must print a clean
        'Error: ...' message and exit 1, not dump a raw Python traceback.

        `cli/__init__.py::main()` only caught ValueError; `find_graph_path()` raises
        FileNotFoundError, which propagated uncaught and crashed with a traceback instead of the
        helpful message the exception text already contains.
        """
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "render", "--query-class", "direct_lookup", "--starts", "foo"],
                cwd=tmp,
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Error: Could not find a native GraphGraph file", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_cli_query_show_stats_flag_supported(self) -> None:
        """`query --show-stats` must be accepted, matching the equivalent `context --show-stats`.

        The `query` subparser lacked a `--show-stats` flag while the near-identical `context`
        subcommand had one, so users following the documented CLI pattern of adding `--show-stats`
        for diagnostics got an argparse "unrecognized arguments" error on `query` specifically.
        """
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(sample_graph(), graph_path)
            proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "query", "auth", "--query-class", "direct_lookup", "--show-stats"],
                cwd=root,
                text=True,
                capture_output=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("GraphGraph query:", proc.stderr)
        self.assertIn("nodes=3", proc.stderr)
