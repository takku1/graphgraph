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
    load_any,
    save_graph,
)
from graphgraph.mcp_server import dispatch
from graphgraph.packets import (
    render_gg_max,
)
from graphgraph.scanner import scan_directory
from graphgraph.services.native import (
    GraphBuildStatus,
    graph_shape,
    refresh_receipt,
    render_native_context,
    scope_freshness,
)
from graphgraph.validate import validate_graph_json


class CliMcpTest(unittest.TestCase):
    def test_scope_freshness_separates_requested_slice_from_repository_drift(self) -> None:
        freshness = scope_freshness(
            {
                "fresh": False,
                "changed_count": 1,
                "deleted_count": 0,
                "changed_paths": ["src/unrelated.py"],
                "deleted_paths": [],
            },
            ("src/requested.py",),
        )

        self.assertTrue(freshness["requested_scope_fresh"])
        self.assertFalse(freshness["repository_fresh"])
        self.assertEqual(freshness["remaining_stale_count"], 1)
        self.assertEqual(freshness["remaining_stale_paths"], ["src/unrelated.py"])
        self.assertEqual(freshness["unrelated_changed_paths"], ["src/unrelated.py"])

    def test_refresh_receipt_separates_request_work_and_graph_mutations(self) -> None:
        status = GraphBuildStatus(
            Path("graph.gg"),
            sample_graph(),
            built=True,
            changed_paths=("src/a.py",),
            deleted_paths=("src/old.py",),
        )

        receipt = refresh_receipt(
            status,
            mode="explicit",
            requested_changed_paths=("src/a.py", "src/a.py"),
            requested_deleted_paths=("src/old.py",),
        )

        self.assertEqual(receipt["requested_paths"], ["src/a.py", "src/old.py"])
        self.assertEqual(receipt["refreshed_paths"], ["src/a.py"])
        self.assertEqual(receipt["removed_paths"], ["src/old.py"])
        self.assertEqual(receipt["graph_mutations"]["updated_path_count"], 1)
        self.assertEqual(receipt["graph_mutations"]["removed_path_count"], 1)

    def test_cli_version_is_discoverable(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "graphgraph.cli", "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(proc.stdout.strip(), r"^graphgraph \S+$")

    def test_context_cli_accepts_work_loop_sync_inputs(self) -> None:
        from graphgraph.cli.parser import build_parser

        args = build_parser().parse_args(
            [
                "context",
                "what changed",
                "--sync",
                "git",
                "--changed",
                "src/a.py",
                "--deleted",
                "src/old.py",
            ]
        )
        self.assertEqual(args.sync, "git")
        self.assertEqual(args.changed, ["src/a.py"])
        self.assertEqual(args.deleted, ["src/old.py"])

    def test_context_cli_compact_json_defaults_and_detailed_opt_in(self) -> None:
        from graphgraph.cli.parser import build_parser

        compact = build_parser().parse_args(["context", "what changed", "--json"])
        detailed = build_parser().parse_args(
            ["context", "what changed", "--json", "--details"]
        )

        self.assertFalse(compact.details)
        self.assertTrue(detailed.details)

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
        self.assertIn('"packet": "gg"', text)

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
        self.assertEqual(data["packet"], "gg")
        self.assertEqual(data["hops"], 1)

    def test_mcp_describe_formats(self) -> None:
        response = dispatch(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "describe_formats", "arguments": {}}}
        )
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        formats = [f["format"] for f in data]
        self.assertIn("gg", formats)
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
        self.assertEqual(data["format"], "gg")

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

    def test_bare_scan_reuses_single_existing_graph_shape_and_owns_its_manifest(self) -> None:
        from graphgraph.cli.commands import cmd_scan

        class Args:
            directory = "."
            output = ""
            incremental = True
            skip_dirs = []
            exclude_dirs = []
            include = []
            max_nodes = 2000
            generic_mentions = False
            depth = None
            frontend = None
            docs = None
            history = None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "app.py"
            source.parent.mkdir()
            source.write_text("def run():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            established = sample_graph()
            established.metadata.update(
                {"scan_depth": "symbols", "frontend": "tree_sitter+regex", "docs": "true", "history": "false"}
            )
            save_graph(established, graph_path)
            args = Args()
            args.directory = str(root)

            cmd_scan(args)

            refreshed = load_any(graph_path)
            self.assertEqual(refreshed.metadata["scan_depth"], "symbols")
            self.assertEqual(refreshed.metadata["docs"], "true")
            self.assertFalse((root / ".graphgraph" / "graph.gg").exists())
            self.assertTrue((root / ".graphgraph" / "graph.json.manifest.json").exists())

    def test_graph_auto_detection_refuses_multiple_native_candidates(self) -> None:
        from graphgraph.io import find_graph_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_dir = root / ".graphgraph"
            graph_dir.mkdir()
            save_graph(sample_graph(), graph_dir / "graph.json")
            save_graph(sample_graph(), graph_dir / "graph.gg")

            with self.assertRaisesRegex(RuntimeError, "Multiple GraphGraph files"):
                find_graph_path(root)

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

    def test_mcp_full_graph_renders_everything_and_errors_over_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)

            response = dispatch({
                "jsonrpc": "2.0", "id": 9, "method": "tools/call",
                "params": {"name": "full_graph", "arguments": {"graph_path": str(graph_path)}},
            })
            assert response is not None
            packet = response["result"]["content"][0]["text"]
            self.assertIn("AuthService", packet)
            self.assertIn("AuditLog", packet)

            response_guard = dispatch({
                "jsonrpc": "2.0", "id": 10, "method": "tools/call",
                "params": {"name": "full_graph", "arguments": {"graph_path": str(graph_path), "max_tokens": 1}},
            })
            assert response_guard is not None
            self.assertIn("error", response_guard)

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

    def test_mcp_query_context_auto_routes_when_class_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 560,
                    "method": "tools/call",
                    "params": {
                        "name": "query_context",
                        "arguments": {
                            "query": "what calls AuthService",
                            "graph_path": str(graph_path),
                            "show_anchors": True,
                        },
                    },
                }
            )
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["query_class"], "reverse_lookup")
            self.assertEqual(data["routing"]["version"], "query_router_v3_calibrated_recovery")
            self.assertEqual(
                data["actionable"]["status"],
                data["retrieval"]["answerability"]["status"],
            )
            self.assertTrue(data["actionable"]["change_points"])
            self.assertIn("reverse dependency intent", data["routing"]["reasons"])

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

    def test_mcp_query_context_can_fuse_bounded_source_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "auth.py"
            source.parent.mkdir()
            source.write_text(
                "def login():\n"
                "    token = 'ok'\n"
                "    return token\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            save_graph(
                Graph(nodes={
                    "LOGIN": Node(
                        "LOGIN",
                        "login",
                        "function",
                        "src/auth.py",
                        summary="L1",
                    ),
                }),
                graph_path,
            )

            response = dispatch({
                "jsonrpc": "2.0",
                "id": 559,
                "method": "tools/call",
                "params": {
                    "name": "query_context",
                    "arguments": {
                        "query": "login",
                        "query_class": "direct_lookup",
                        "graph_path": str(graph_path),
                        "include_snippets": True,
                        "snippet_limit": 1,
                        "snippet_context_lines": 1,
                        "snippet_max_lines": 2,
                    },
                },
            })

            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertIn("1 | def login():", data["source_snippets"])
            self.assertIn("2 |     token = 'ok'", data["source_snippets"])
            self.assertNotIn("3 |", data["source_snippets"])

            source.write_text(
                "def login():\n"
                "    token = 'fresh'\n"
                "    return token\n",
                encoding="utf-8",
            )
            second = dispatch({
                "jsonrpc": "2.0",
                "id": 558,
                "method": "tools/call",
                "params": {
                    "name": "query_context",
                    "arguments": {
                        "query": "login",
                        "query_class": "direct_lookup",
                        "graph_path": str(graph_path),
                        "show_anchors": True,
                        "include_snippets": True,
                        "snippet_limit": 1,
                        "snippet_context_lines": 1,
                        "snippet_max_lines": 2,
                    },
                },
            })
            assert second is not None
            second_data = json.loads(second["result"]["content"][0]["text"])
            self.assertIn("token = 'fresh'", second_data["source_snippets"])
            self.assertNotIn("token = 'ok'", second_data["source_snippets"])

    def test_mcp_query_context_splices_changed_and_deleted_paths_before_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.py"
            removed = root / "removed.py"
            source.write_text("def old_handler():\n    return 1\n", encoding="utf-8")
            removed.write_text("def obsolete_worker():\n    return 0\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            manifest_path = graph_path.parent / "manifest.json"
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)

            source.write_text("def fused_fresh_handler():\n    return 2\n", encoding="utf-8")
            # Keep this file on disk deliberately: deleted_paths is an
            # authoritative graph instruction, not an existence heuristic.
            with patch(
                "graphgraph.services.context._load_graph_cached",
                side_effect=AssertionError("fused query reloaded the just-written graph"),
            ):
                response = dispatch(
                    {
                        "jsonrpc": "2.0",
                        "id": 561,
                        "method": "tools/call",
                        "params": {
                            "name": "query_context",
                            "arguments": {
                                "query": "fused_fresh_handler",
                                "query_class": "direct_lookup",
                                "directory": str(root),
                                "graph_path": str(graph_path),
                                "changed_paths": ["main.py", "main.py"],
                                "deleted_paths": ["removed.py"],
                                "show_anchors": True,
                            },
                        },
                    }
                )

            assert response is not None
            self.assertNotIn("error", response)
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["anchors"][0]["label"], "fused_fresh_handler")
            self.assertIn("fused_fresh_handler", data["packet"])
            self.assertTrue(data["actionable"]["freshness"]["requested_scope_fresh"])
            self.assertEqual(data["refresh"]["requested_paths"], ["main.py", "removed.py"])
            self.assertEqual(data["refresh"]["refreshed_paths"], ["main.py"])
            self.assertEqual(data["refresh"]["removed_paths"], ["removed.py"])
            self.assertTrue(data["refresh"]["graph_mutations"]["write_performed"])
            self.assertEqual(data["actionable"]["freshness"]["remaining_stale_paths"], [])

            refreshed = load_any(graph_path)
            labels = {node.label for node in refreshed.nodes.values()}
            self.assertIn("fused_fresh_handler", labels)
            self.assertNotIn("old_handler", labels)
            self.assertFalse(any(node.path == "removed.py" for node in refreshed.nodes.values()))

    def test_mcp_query_context_refresh_inherits_saved_docs_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme = root / "README.md"
            readme.write_text("# Old Documentation\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            manifest_path = graph_path.parent / "manifest.json"
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=True,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)

            readme.write_text("# Fused Fresh Documentation\n\nUpdated agent instructions.\n", encoding="utf-8")
            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 562,
                    "method": "tools/call",
                    "params": {
                        "name": "query_context",
                        "arguments": {
                            "query": "Fused Fresh Documentation",
                            "query_class": "doc_summary",
                            "directory": str(root),
                            "graph_path": str(graph_path),
                            "changed_paths": ["README.md"],
                            "show_anchors": True,
                        },
                    },
                }
            )

            assert response is not None
            self.assertNotIn("error", response)
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(any(anchor["label"] == "Fused Fresh Documentation" for anchor in data["anchors"]))
            refreshed = load_any(graph_path)
            self.assertTrue(
                any(node.kind == "section" and node.label == "Fused Fresh Documentation" for node in refreshed.nodes.values())
            )

    def test_mcp_query_context_git_sync_refreshes_only_manifest_stale_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "worker.py"
            source.write_text("def old_worker():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                previous_graph_path=None,
                manifest_path=graph_path.parent / "manifest.json",
            )
            save_graph(graph, graph_path)
            source.write_text("def synced_worker():\n    return 2\n", encoding="utf-8")

            arguments = {
                "query": "synced_worker",
                "query_class": "direct_lookup",
                "directory": str(root),
                "graph_path": str(graph_path),
                "sync": "git",
                "show_anchors": True,
            }
            with patch(
                "graphgraph.services.native.get_git_worktree_paths",
                return_value=(("worker.py",), ()),
            ):
                first = dispatch(
                    {
                        "jsonrpc": "2.0",
                        "id": 564,
                        "method": "tools/call",
                        "params": {"name": "query_context", "arguments": arguments},
                    }
                )
                with patch(
                    "graphgraph.services.native.update_paths_validated_graph",
                    side_effect=AssertionError("manifest-current path was refreshed twice"),
                ):
                    second = dispatch(
                        {
                            "jsonrpc": "2.0",
                            "id": 565,
                            "method": "tools/call",
                            "params": {"name": "query_context", "arguments": arguments},
                        }
                    )

            assert first is not None and second is not None
            first_data = json.loads(first["result"]["content"][0]["text"])
            second_data = json.loads(second["result"]["content"][0]["text"])
            self.assertEqual(first_data["refresh"]["changed_paths"], ["worker.py"])
            self.assertEqual(second_data["refresh"]["changed_paths"], [])
            self.assertEqual(first_data["anchors"][0]["label"], "synced_worker")
            self.assertEqual(second_data["anchors"][0]["label"], "synced_worker")

    def test_mcp_query_context_git_sync_reconciles_changed_ignore_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "worker.py").write_text("def worker():\n    return 1\n", encoding="utf-8")
            ignored_note = root / "docs" / "bugs" / "note.md"
            ignored_note.parent.mkdir(parents=True)
            ignored_note.write_text("# Temporary Bug Note\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir()
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=True,
                previous_graph_path=None,
                manifest_path=graph_path.parent / "manifest.json",
            )
            save_graph(graph, graph_path)
            self.assertTrue(any(node.path == "docs/bugs/note.md" for node in graph.nodes.values()))
            (root / ".gitignore").write_text("docs/bugs/\n", encoding="utf-8")

            with patch(
                "graphgraph.services.native.get_git_worktree_paths",
                return_value=((".gitignore",), ()),
            ), patch(
                "graphgraph.services.native.get_git_ignored_paths",
                side_effect=[("docs/bugs/note.md",), ()],
            ):
                response = dispatch(
                    {
                        "jsonrpc": "2.0",
                        "id": 566,
                        "method": "tools/call",
                        "params": {
                            "name": "query_context",
                            "arguments": {
                                "query": "worker",
                                "query_class": "direct_lookup",
                                "directory": str(root),
                                "graph_path": str(graph_path),
                                "sync": "git",
                                "show_anchors": True,
                            },
                        },
                    }
                )

            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["refresh"]["changed_paths"], [])
            self.assertEqual(data["refresh"]["deleted_paths"], ["docs/bugs/note.md"])
            refreshed = load_any(graph_path)
            self.assertFalse(any(node.path == "docs/bugs/note.md" for node in refreshed.nodes.values()))
            self.assertFalse(any(node.path == ".gitignore" for node in refreshed.nodes.values()))

    def test_mcp_query_context_schema_exposes_fused_refresh_inputs(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 563, "method": "tools/list", "params": {}})
        assert response is not None
        tool = next(item for item in response["result"]["tools"] if item["name"] == "query_context")
        properties = tool["inputSchema"]["properties"]
        self.assertIn("changed_paths", properties)
        self.assertIn("deleted_paths", properties)
        self.assertIn("scan_max_nodes", properties)
        self.assertIn("sync", properties)

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
            (root / ".ignore").write_text("corpus/\n", encoding="utf-8")
            (root / "corpus").mkdir()
            (root / "corpus" / "noise.py").write_text("def noise(): pass\n", encoding="utf-8")
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
            self.assertEqual(data["frontend"], "files")
            self.assertEqual(data["exclusions"]["ignore_files"], [".ignore"])
            self.assertEqual(data["exclusions"]["ignored_dirs"], 1)
            self.assertEqual(data["exclusions"]["ignored_dir_sample"], ["corpus"])
            self.assertIn("docs_truncated_files", data["phase_profile"])
            self.assertTrue(output.exists())

    def test_build_receipt_doc_nodes_matches_project_status(self) -> None:
        # Slice-round finding (docs/bugs/2026-07-17-locus-blackbox-slice-implementation-round.md):
        # the build receipt's docs counters read as "no docs" (docs_files: 0)
        # even when doc nodes landed, because docs_files counts documents parsed
        # into sections, not doc-kind file nodes. The receipt now also reports
        # doc_nodes (what actually landed), and it must agree with the count
        # project_status reports for the same graph.
        from graphgraph.mcp.server import handle_build_graph
        from graphgraph.services.native import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            (root / "README.md").write_text("# Title\n\nProse about the module.\n", encoding="utf-8")
            out_path = root / ".graphgraph" / "graph.gg"
            receipt = json.loads(handle_build_graph({
                "directory": str(root), "output_path": str(out_path),
                "depth": "symbols", "docs": True,
            }))
            profile = receipt["phase_profile"]
            self.assertIn("doc_nodes", profile)
            self.assertGreater(profile["doc_nodes"], 0)  # the README landed
            status = build_project_status(directory=root, graph_path=out_path)
            self.assertEqual(profile["doc_nodes"], status["graph"]["shape"]["doc_nodes"])

    def test_splice_tools_require_paths_with_actionable_error(self) -> None:
        # Friction finding: remove_graph_files/update_graph_files errored with a
        # cryptic MCP `-32000: 'paths'` (a bare KeyError message) when the
        # required `paths` arg was omitted. They must instead fail with a message
        # that names the tool and says what to pass -- the schema marks `paths`
        # required, but the server should not assume the client enforced it.
        from graphgraph.mcp.server import handle_remove_graph_files, handle_update_graph_files

        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / ".graphgraph" / "graph.gg")
            for handler, tool in (
                (handle_remove_graph_files, "remove_graph_files"),
                (handle_update_graph_files, "update_graph_files"),
            ):
                with self.assertRaises(ValueError) as ctx:
                    handler({"directory": tmp, "output_path": out})  # no 'paths'
                message = str(ctx.exception)
                self.assertIn("paths", message)
                self.assertIn(tool, message)
                # a non-list paths value is also rejected clearly
                with self.assertRaises(ValueError):
                    handler({"directory": tmp, "output_path": out, "paths": "a.py"})

    def test_mcp_missing_required_arg_returns_actionable_error(self) -> None:
        # Eval BUG-2 + systemic gap (blackbox-eval-2026-07-18): omitting a
        # required MCP arg leaked a raw `-32000: 'query_class'` KeyError. The
        # dispatch boundary now validates every tool's declared required args and
        # names them, enumerating allowed values from the schema description.
        from graphgraph.mcp.server import handle_tools_call

        with self.assertRaises(ValueError) as ctx:
            handle_tools_call({"name": "plan_context", "arguments": {"query": "x"}})
        message = str(ctx.exception)
        self.assertIn("query_class", message)
        self.assertIn("blast_radius", message)  # choices surfaced, not just the key name

    def test_source_snippets_composes_with_search_nodes_ids(self) -> None:
        # Eval BUG-1 (blackbox-eval-2026-07-18): source_snippets required `starts`
        # but search_nodes returns `id`, so the tools didn't compose, and a
        # missing id leaked a raw `-32000: 'starts'`. It now accepts `node_ids`
        # (what search_nodes hands you) and errors clearly when neither is given.
        from graphgraph.mcp.server import handle_source_snippets
        from graphgraph.retrieval.search import search_nodes
        from graphgraph.scanner import scan_directory

        with self.assertRaises(ValueError) as ctx:
            handle_source_snippets({})
        self.assertIn("node_ids", str(ctx.exception))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            graph = scan_directory(root, depth="symbols")
            gp = root / "g.json"
            save_graph(graph, gp)
            node_id = search_nodes(graph, "foo", limit=1)[0].node.id
            out = handle_source_snippets({"node_ids": [node_id], "graph_path": str(gp)})
            self.assertIn("foo", out)

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

    def test_native_json_abstention_does_not_claim_packet_validation_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text(
                "def worker_implementation():\n    return 'wired'\n",
                encoding="utf-8",
            )
            packet, _status = render_native_context(
                query="Where is the nonexistent quantum banana scheduler implemented?",
                directory=root,
                graph_path=root / ".graphgraph" / "graph.json",
                query_class="negative_query",
                json_output=True,
                max_nodes=20,
            )

        payload = json.loads(packet)
        self.assertEqual(payload["retrieval"]["answerability"]["status"], "unanswerable")
        self.assertTrue(payload["retrieval"]["answerability"]["abstained"])
        self.assertIsNone(payload["workflow"]["packet_validation"]["ok"])
        self.assertEqual(payload["workflow"]["packet_validation"]["status"], "not_applicable")

    def test_native_json_validation_covers_packet_and_semantic_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text(
                "def compile_formula():\n    return 'ok'\n",
                encoding="utf-8",
            )
            packet, _status = render_native_context(
                query="where is compile_formula",
                directory=root,
                graph_path=root / ".graphgraph" / "graph.json",
                query_class="direct_lookup",
                json_output=True,
                max_nodes=20,
            )

        payload = json.loads(packet)
        validation = payload["workflow"]["packet_validation"]
        self.assertTrue(validation["ok"])
        self.assertEqual(validation["status"], "packet_and_receipt_pass")
        self.assertEqual(validation["scope"], "packet_and_receipt")

    def test_native_compact_json_keeps_actionable_tests_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text(
                "def test_compile_formula():\n"
                "    assert compile_formula()\n",
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                "def compile_formula():\n"
                "    return True\n",
                encoding="utf-8",
            )
            packet, _status = render_native_context(
                query="which direct tests cover compile_formula",
                directory=root,
                graph_path=root / ".graphgraph" / "graph.json",
                query_class="affected_tests",
                json_output=True,
                json_details=False,
                max_nodes=20,
            )

        payload = json.loads(packet)
        self.assertEqual(payload["details"]["included"], False)
        self.assertIn("--json --details", payload["details"]["hint"])
        self.assertNotIn("packet", payload)
        self.assertNotIn("retrieval", payload)
        self.assertIn("direct", payload["actionable"]["tests"])
        self.assertIn("transitive", payload["actionable"]["tests"])
        self.assertIn("packet_validation", payload["workflow"])

    def test_project_status_cold_repo_returns_graceful_no_graph_status(self) -> None:
        # Slice-round finding (docs/bugs/2026-07-17-locus-blackbox-slice-implementation-round.md):
        # project_status on a cold repo hard-errored (MCP -32000) instead of an
        # actionable "no graph yet" status. A status probe is the natural first
        # call on a fresh repo, so absence of a graph is an expected state, not
        # an exception -- it must return an inspectable, actionable status and
        # the MCP handler must serialize it rather than raise.
        from graphgraph.mcp.server import handle_project_status
        from graphgraph.services.native import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)  # deliberately empty: no .graphgraph graph
            report = build_project_status(directory=root)
            self.assertEqual(report["status"], "no_graph")
            self.assertEqual(report["next_action"], "build_graph")
            self.assertIn("build_graph", report["message"])
            # MCP surface must not crash -- it serializes the status object.
            payload = json.loads(handle_project_status({"directory": str(root)}))
            self.assertEqual(payload["status"], "no_graph")

    def test_project_status_reports_symbol_extraction_from_content(self) -> None:
        # Slice-round finding: an incremental scan that preserves prior symbols
        # can reset the frontend/scan_depth label to "files", so the label alone
        # can't answer "did symbol extraction happen?". project_status now reports
        # symbol_extraction derived from actual node kinds -- authoritative even
        # when the label is stale.
        from graphgraph.services.native import build_project_status

        symbol_graph = Graph(nodes={
            "F": Node("F", "foo", "function", "a.py"),
            "M": Node("M", "bar", "method", "a.py"),
            "FILE": Node("FILE", "a.py", "python", "a.py"),
        })
        files_only = Graph(nodes={"FILE": Node("FILE", "a.py", "python", "a.py")})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sym_path = root / "sym.json"
            files_path = root / "files.json"
            save_graph(symbol_graph, sym_path)
            # Simulate the misreporting label: symbols present but frontend "files".
            symbol_graph.metadata["frontend"] = "files"
            save_graph(symbol_graph, sym_path)
            save_graph(files_only, files_path)

            sym = build_project_status(directory=root, graph_path=sym_path)["graph"]["symbol_extraction"]
            self.assertTrue(sym["present"])
            self.assertEqual(sym["symbol_nodes"], 2)  # authoritative despite frontend="files"

            files = build_project_status(directory=root, graph_path=files_path)["graph"]["symbol_extraction"]
            self.assertFalse(files["present"])
            self.assertEqual(files["symbol_nodes"], 0)

    def test_project_status_separates_member_call_trust_coverage_and_external_sites(self) -> None:
        from graphgraph.services.native import build_project_status

        graph = Graph(
            nodes={
                "A": Node("A", "caller", "function", "a.py"),
                "B": Node("B", "target", "method", "a.py"),
                "C": Node("C", "other", "method", "a.py"),
            },
            edges=[Edge("A", "C", "calls_candidate")],
            metadata={
                "member_calls_global_resolved": "3",
                "member_calls_global_ambiguous": "0",
                "member_calls_global_unknown_receiver": "7",
                "member_calls_global_unresolved": "90",
                "member_calls_global_version": "2",
                "member_calls_global_scope": "full_scan_snapshot",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            save_graph(graph, graph_path)
            calls = build_project_status(directory=root, graph_path=graph_path)["graph"]["member_calls"]

        self.assertEqual(calls["trust"], "high")
        self.assertEqual(calls["coverage"], "partial")
        self.assertEqual(calls["resolved_ratio"], 0.3)
        self.assertEqual(calls["trusted_resolution_ratio"], 1.0)
        self.assertEqual(calls["receiver_evidence_ratio"], 0.3)
        self.assertEqual(calls["external_or_unmatched"], 90)
        self.assertEqual(calls["candidate_edges"], 1)
        self.assertIn("7 member-call sites lack receiver evidence", calls["warning"])

    def test_project_status_marks_legacy_member_call_telemetry_unclassified(self) -> None:
        from graphgraph.services.native import build_project_status

        graph = Graph(
            nodes={"A": Node("A", "caller", "function", "a.py")},
            metadata={
                "member_calls_global_resolved": "2",
                "member_calls_global_ambiguous": "8",
                "member_calls_global_unresolved": "20",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            save_graph(graph, graph_path)
            calls = build_project_status(directory=root, graph_path=graph_path)["graph"]["member_calls"]

        self.assertEqual(calls["trust"], "legacy_unclassified")
        self.assertEqual(calls["coverage"], "unknown")
        self.assertIn("full symbol scan", calls["warning"])

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

    def test_project_status_reports_cargo_workspace_metadata(self) -> None:
        from graphgraph.services.native import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers = ["crates/core", "crates/cli"]\n',
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(Graph(nodes={"R": Node("R", "workspace", "rust", "crates/core/src/lib.rs")}), graph_path)

            report = build_project_status(directory=root, graph_path=graph_path)

        self.assertEqual(report["package"]["ecosystem"], "rust")
        self.assertEqual(report["package"]["rust"]["kind"], "workspace")
        self.assertEqual(report["package"]["rust"]["members"], ["crates/core", "crates/cli"])

    def test_cli_validate_graph_accepts_positional_path(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)
            proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "validate-graph", str(graph_path)],
                text=True,
                capture_output=True,
                env=env,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("STRUCTURAL PASS", proc.stdout)

    def test_project_status_surfaces_scan_truncation(self) -> None:
        # Found via live dogfooding: doctor already surfaces
        # files_truncated/symbols_truncated (fixed earlier this session for
        # cmd_scan), but project_status -- also explicitly documented as
        # "the is-something-wrong-with-my-graph surface" -- didn't check
        # graph.metadata for the same flags at all, so it could report a
        # graph as fully validated/healthy while silently built from an
        # incomplete scan.
        from graphgraph.services.native import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            graph = Graph(
                nodes={"N1": Node("N1", "AuthService", "service", "server/auth.py")},
                metadata={"files_truncated": "true", "files_total_matched": "500", "symbols_truncated": "true", "symbols_cap": "100"},
            )
            save_graph(graph, graph_path)

            report = build_project_status(directory=root, graph_path=graph_path)
            self.assertTrue(report["graph"]["files_truncated"])
            self.assertEqual(report["graph"]["files_total_matched"], "500")
            self.assertTrue(report["graph"]["symbols_truncated"])
            self.assertEqual(report["graph"]["symbols_cap"], "100")

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
        self.assertIn("STRUCTURAL FAIL semantic_arrow nodes=0 edges=0", proc.stdout)
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

    def test_cli_final_full_graph_renders_everything_and_refuses_over_guard(self) -> None:
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(sample_graph(), graph_path)

            proc = subprocess.run(
                [sys.executable, "-m", "graphgraph", "final", "--graph", str(graph_path), "--full-graph"],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("[n]", proc.stdout)
            self.assertIn("AuthService", proc.stdout)
            self.assertIn("AuditLog", proc.stdout)

            proc_guard = subprocess.run(
                [
                    sys.executable, "-m", "graphgraph", "final", "--graph", str(graph_path),
                    "--full-graph", "--full-graph-max-tokens", "1",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc_guard.returncode, 1)
            self.assertIn("Error:", proc_guard.stderr)
            self.assertNotIn("Traceback", proc_guard.stderr)

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
        # Which rendering appears depends on whether a keyring backend exists:
        # dev machines have one and list each provider key as "Not configured
        # (OK...)", while a bare CI runner has none and reports the credential
        # lookup was skipped. Both frame missing keys as OK -- the invariant this
        # test guards -- so accept either, and never the alarming "Not found".
        per_provider = "OpenAI API Key: Not configured (OK; external OpenAI benchmarks will be skipped)" in proc.stdout
        lookup_skipped = "Credential lookup skipped/failed (OK for local GraphGraph use)" in proc.stdout
        self.assertTrue(per_provider or lookup_skipped, proc.stdout)
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
                self.assertIn("Audit exclusions before building", skill_content)
                self.assertIn(
                    "SYNC -> EXTRACT -> NORMALIZE IR -> ANCHOR -> EXPAND -> SELECT -> PACK",
                    skill_content,
                )
                self.assertIn('sync: "git"', skill_content)
                self.assertIn("--test-command", skill_content)
                skill_harness = Path(".agents") / "skills" / "graphgraph" / "scripts" / "validate_live.py"
                self.assertTrue(skill_harness.exists())
                harness_content = skill_harness.read_text(encoding="utf-8")
                self.assertIn("graphgraph.live_validation", harness_content)
                self.assertIn('shutil.which("graphgraph")', harness_content)
                self.assertIn("owning_python", harness_content)

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
                self.assertEqual(plugin_skill_content, skill_content)
                plugin_harness = plugin_skill.parent / "scripts" / "validate_live.py"
                self.assertEqual(
                    plugin_harness.read_text(encoding="utf-8"),
                    skill_harness.read_text(encoding="utf-8"),
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

    def test_live_validation_detects_repo_ecosystem_and_supports_override(self) -> None:
        from graphgraph.live_validation import detect_test_command, split_command

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Cargo.toml").write_text("[package]\nname='foreign-rust-repo'\nversion='0.1.0'\n", encoding="utf-8")
            command, ecosystem = detect_test_command(root)

        self.assertEqual(command, ["cargo", "test", "--workspace"])
        self.assertEqual(ecosystem, "cargo")
        self.assertEqual(split_command('cargo test --package "locus engine"'), ["cargo", "test", "--package", "locus engine"])

    def test_live_validation_saved_reports_are_explicitly_optional(self) -> None:
        from graphgraph.live_validation import load_saved_reports

        with tempfile.TemporaryDirectory() as tmpdir:
            status = load_saved_reports(Path(tmpdir), enabled=False)

        self.assertEqual(status["status"], "skipped")
        self.assertIn("--saved-reports", status["reason"])

    def test_live_validation_reports_exclusion_and_truncation_evidence(self) -> None:
        from graphgraph.live_validation import scan_policy_receipt

        graph = Graph(
            nodes={"APP": Node("APP", "app", "python", "src/app.py")},
            metadata={"symbols_truncated": "true", "docs_truncated_count": "2"},
        )

        receipt = scan_policy_receipt(graph, 1800)

        self.assertTrue(receipt["exclusions_valid"])
        self.assertTrue(all(row["indexed_nodes"] == 0 for row in receipt["exclusions"]))
        self.assertEqual(receipt["max_files"], 1800)
        self.assertFalse(receipt["truncation"]["files"])
        self.assertTrue(receipt["truncation"]["symbols"])
        self.assertEqual(receipt["truncation"]["docs_count"], 2)

    def test_live_validation_custom_queries_auto_route_and_check_actionability(self) -> None:
        from types import SimpleNamespace

        from graphgraph.live_validation import validate_queries

        query = "Which direct tests cover TransformPlanner and what Cargo command should run?"
        response = json.dumps({
            "query_class": "affected_tests",
            "anchors": [{"id": "PLAN"}],
            "packet": "#gg/v1",
            "retrieval": {
                "semantic_validation": {"ok": True, "errors": []},
                "affected_tests": {
                    "direct": [{"id": "TEST"}],
                    "transitive": [],
                    "commands": ["cargo test -p locus-frontends planner::tests --lib"],
                },
            },
            "actionable": {"status": "ready", "missing_evidence": []},
        })
        with (
            patch("graphgraph.services.render_query_context", return_value=response) as render,
            patch(
                "graphgraph.validate.validate_packet",
                return_value=SimpleNamespace(
                    ok=True,
                    format="gg",
                    node_count=2,
                    edge_count=1,
                    errors=(),
                ),
            ),
        ):
            rows = validate_queries(sample_graph(), Path("live.graph.json"), [query])

        self.assertEqual(len(rows), 1)
        self.assertEqual(render.call_args.kwargs["query_class"], "auto")
        self.assertEqual(rows[0]["query_class"], "affected_tests")
        self.assertTrue(rows[0]["query_valid"])
        self.assertTrue(rows[0]["actionable_valid"])
        self.assertEqual(rows[0]["direct_tests"], 1)
        self.assertEqual(len(rows[0]["commands"]), 1)

    def test_live_validation_rejects_structurally_valid_but_inactionable_test_answer(self) -> None:
        from graphgraph.live_validation import validate_query_actionability

        errors = validate_query_actionability(
            "Return direct behavioral tests and minimal runnable Cargo commands.",
            {
                "retrieval": {
                    "affected_tests": {
                        "direct": [],
                        "transitive": [{"id": "TRANSITIVE"}],
                        "commands": [],
                    },
                },
            },
        )

        self.assertIn("query requests direct tests but affected_tests.direct is empty", errors)
        self.assertIn("query requests runnable commands but affected_tests.commands is empty", errors)

    def test_live_validation_gate_failures_explain_expectation_mismatches(self) -> None:
        from types import SimpleNamespace

        from graphgraph.live_validation import validate_gate_packets

        graph = Graph(
            nodes={
                "A": Node("A", "source", "function", "src/a.py"),
                "B": Node("B", "target", "function", "src/b.py"),
            },
            edges=[Edge("A", "B", "calls")],
        )
        with (
            patch("graphgraph.services.render_final_packet", return_value="GRAPH:\n#gg/v1"),
            patch(
                "graphgraph.validate.validate_packet",
                return_value=SimpleNamespace(
                    ok=True,
                    format="gg",
                    node_count=1,
                    edge_count=0,
                    errors=(),
                ),
            ),
        ):
            rows = validate_gate_packets(graph, Path("live.graph.json"))

        self.assertTrue(rows)
        self.assertTrue(all(not row["ok"] for row in rows))
        self.assertTrue(all(row["failure_reason"] for row in rows))
        self.assertIn("expected packet format semantic_arrow", rows[0]["failure_reason"])
        self.assertIn("expected at least one structural edge", rows[1]["failure_reason"])

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
