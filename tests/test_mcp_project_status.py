from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import sample_graph

from graphgraph import (
    Edge,
    Graph,
    Node,
)
from graphgraph.io import (
    save_graph,
)
from graphgraph.mcp import dispatch
from graphgraph.services.freshness import inspect_saved_graph_freshness


class McpProjectStatusTest(unittest.TestCase):
    def test_build_receipt_doc_nodes_matches_project_status(self) -> None:
        # Slice-round finding (docs/bugs/2026-07-17-locus-blackbox-slice-implementation-round.md):
        # the build receipt's docs counters read as "no docs" (docs_files: 0)
        # even when doc nodes landed, because docs_files counts documents parsed
        # into sections, not doc-kind file nodes. The receipt now also reports
        # doc_nodes (what actually landed), and it must agree with the count
        # project_status reports for the same graph.
        from graphgraph.mcp.server import handle_build_graph
        from graphgraph.services.project_status import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            (root / "README.md").write_text("# Title\n\nProse about the module.\n", encoding="utf-8")
            out_path = root / ".graphgraph" / "graph.gg"
            receipt = json.loads(
                handle_build_graph(
                    {
                        "directory": str(root),
                        "output_path": str(out_path),
                        "depth": "symbols",
                        "docs": True,
                    }
                )
            )
            profile = receipt["phase_profile"]
            self.assertIn("doc_nodes", profile)
            self.assertGreater(profile["doc_nodes"], 0)  # the README landed
            self.assertGreater(profile["wall_ms"], 0)
            self.assertGreaterEqual(profile["attributed_ratio"], 0.9)
            self.assertLessEqual(profile["unattributed_ms"], profile["wall_ms"] * 0.1)
            self.assertIn("symbols", profile["phases"])
            self.assertIn("validate_save", profile["phases"])
            status = build_project_status(directory=root, graph_path=out_path)
            self.assertEqual(profile["doc_nodes"], status["graph"]["shape"]["doc_nodes"])

    def test_project_status_cold_repo_returns_graceful_no_graph_status(self) -> None:
        # Slice-round finding (docs/bugs/2026-07-17-locus-blackbox-slice-implementation-round.md):
        # project_status on a cold repo hard-errored (MCP -32000) instead of an
        # actionable "no graph yet" status. A status probe is the natural first
        # call on a fresh repo, so absence of a graph is an expected state, not
        # an exception -- it must return an inspectable, actionable status and
        # the MCP handler must serialize it rather than raise.
        from graphgraph.mcp.server import handle_project_status
        from graphgraph.services.project_status import build_project_status

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
        from graphgraph.services.project_status import build_project_status

        symbol_graph = Graph(
            nodes={
                "F": Node("F", "foo", "function", "a.py"),
                "M": Node("M", "bar", "method", "a.py"),
                "FILE": Node("FILE", "a.py", "python", "a.py"),
            }
        )
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
        from graphgraph.services.project_status import build_project_status

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
                "member_calls_global_by_language": json.dumps(
                    {
                        "python": {
                            "resolved": 3,
                            "ambiguous": 0,
                            "unknown_receiver": 7,
                            "external_resolved": 80,
                            "unmatched": 10,
                        }
                    }
                ),
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
        self.assertEqual(
            calls["by_language"]["python"]["receiver_resolution_ratio"],
            0.3,
        )
        self.assertEqual(calls["by_language"]["python"]["unmatched"], 10)
        self.assertIn("7 member-call sites lack receiver evidence", calls["warning"])

    def test_project_status_marks_legacy_member_call_telemetry_unclassified(self) -> None:
        from graphgraph.services.project_status import build_project_status

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
        from graphgraph.services.project_status import build_project_status

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
        from graphgraph.services.project_status import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers = ["crates/core", "crates/cli"]\n',
                encoding="utf-8",
            )
            for crate in ("core", "cli"):
                member = root / "crates" / crate
                member.mkdir(parents=True)
                (member / "Cargo.toml").write_text(
                    f'[package]\nname = "{crate}"\nversion = "0.1.0"\n',
                    encoding="utf-8",
                )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(Graph(nodes={"R": Node("R", "workspace", "rust", "crates/core/src/lib.rs")}), graph_path)

            report = build_project_status(directory=root, graph_path=graph_path)

        self.assertEqual(report["package"]["ecosystem"], "rust")
        self.assertEqual(report["package"]["rust"]["kind"], "workspace")
        self.assertEqual(report["package"]["rust"]["members"], ["crates/core", "crates/cli"])

    def test_project_status_reports_npm_manifest_and_test_script(self) -> None:
        from graphgraph.services.project_status import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "express",
                        "version": "5.2.1",
                        "main": "index.js",
                        "scripts": {
                            "test": "mocha --require test/support/env test/ test/acceptance/"
                        },
                    }
                ),
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(
                Graph(nodes={"J": Node("J", "index.js", "javascript", "index.js")}),
                graph_path,
            )

            report = build_project_status(directory=root, graph_path=graph_path)

        package = report["package"]
        self.assertEqual(package["ecosystem"], "npm")
        self.assertEqual(package["ecosystems"], ["npm"])
        self.assertEqual(package["name"], "express")
        self.assertEqual(package["version"], "5.2.1")
        self.assertEqual(package["javascript"]["main"], "index.js")
        self.assertEqual(
            package["scripts"]["test"],
            "mocha --require test/support/env test/ test/acceptance/",
        )

    def test_project_status_expands_cargo_workspace_globs_and_excludes(self) -> None:
        from graphgraph.services.project_status import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/dev-only"]\n',
                encoding="utf-8",
            )
            for crate in ("advisors", "cli", "core", "dev-only", "engine", "frontends", "pipeline"):
                member = root / "crates" / crate
                member.mkdir(parents=True)
                (member / "Cargo.toml").write_text(
                    f'[package]\nname = "{crate}"\nversion = "0.1.0"\n',
                    encoding="utf-8",
                )
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            save_graph(
                Graph(
                    nodes={
                        "R": Node(
                            "R",
                            "workspace",
                            "rust",
                            "crates/core/src/lib.rs",
                        )
                    }
                ),
                graph_path,
            )

            report = build_project_status(directory=root, graph_path=graph_path)

        rust = report["package"]["rust"]
        self.assertEqual(rust["member_patterns"], ["crates/*"])
        self.assertEqual(rust["exclude_patterns"], ["crates/dev-only"])
        self.assertEqual(
            rust["members"],
            [
                "crates/advisors",
                "crates/cli",
                "crates/core",
                "crates/engine",
                "crates/frontends",
                "crates/pipeline",
            ],
        )

    def test_project_status_surfaces_scan_truncation(self) -> None:
        # Found via live dogfooding: doctor already surfaces
        # files_truncated/symbols_truncated (fixed earlier this session for
        # cmd_scan), but project_status -- also explicitly documented as
        # "the is-something-wrong-with-my-graph surface" -- didn't check
        # graph.metadata for the same flags at all, so it could report a
        # graph as fully validated/healthy while silently built from an
        # incomplete scan.
        from graphgraph.services.project_status import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / ".graphgraph" / "graph.json"
            graph_path.parent.mkdir(parents=True)
            graph = Graph(
                nodes={"N1": Node("N1", "AuthService", "service", "server/auth.py")},
                metadata={
                    "files_truncated": "true",
                    "files_total_matched": "500",
                    "symbols_truncated": "true",
                    "symbols_cap": "100",
                },
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

    def test_tracked_file_listed_in_gitignore_still_reports_stale(self) -> None:
        # Git's rule is that .gitignore governs untracked files only: a
        # tracked file listed there still reports its edits. Filtering the
        # tracked set through ignore rules dropped those edits, so the graph
        # went stale while freshness reported clean -- silent, and worst for
        # generated-then-committed files, which change often.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            def git(*args: str) -> None:
                subprocess.run(("git", *args), cwd=root, capture_output=True, check=False)

            git("init", "-q", ".")
            (root / ".gitignore").write_text("generated.py\nbuild/\n", encoding="utf-8")
            (root / "generated.py").write_text("def a():\n    return 1\n", encoding="utf-8")
            (root / "app.py").write_text("def b():\n    return 2\n", encoding="utf-8")
            git("add", "-f", "generated.py", "app.py", ".gitignore")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

            graph_path = root / ".graphgraph" / "graph.gg"
            from graphgraph.services.lifecycle import scan_validated_graph

            scan_validated_graph(directory=root, output_path=graph_path, depth="symbols")

            (root / "generated.py").write_text("def a():\n    return 99\n", encoding="utf-8")
            freshness = inspect_saved_graph_freshness(directory=root, output_path=graph_path)
            self.assertFalse(freshness["fresh"])
            self.assertIn("generated.py", freshness["changed_paths"])

            # ...while an untracked ignored file stays excluded, which is the
            # property the secret-boundary case depends on.
            (root / "build").mkdir(exist_ok=True)
            (root / "build" / "junk.py").write_text("def junk():\n    pass\n", encoding="utf-8")
            after = inspect_saved_graph_freshness(directory=root, output_path=graph_path)
            self.assertNotIn("build/junk.py", after["changed_paths"])

    def test_commit_after_scan_reports_stale_until_every_changed_path_is_refreshed(self) -> None:
        """A clean worktree is not evidence that the saved graph matches HEAD."""
        from graphgraph.services.lifecycle import (
            scan_validated_graph,
            update_paths_validated_graph,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            def git(*args: str) -> None:
                subprocess.run(("git", *args), cwd=root, capture_output=True, check=True)

            git("init", "-q", ".")
            (root / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
            git("add", "a.py", "b.py")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "initial")

            graph_path = root / ".graphgraph" / "graph.gg"
            scan_validated_graph(directory=root, output_path=graph_path, depth="symbols")

            (root / "a.py").write_text("VALUE = 10\n", encoding="utf-8")
            (root / "b.py").write_text("VALUE = 20\n", encoding="utf-8")
            git("add", "a.py", "b.py")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "change")

            stale = inspect_saved_graph_freshness(directory=root, output_path=graph_path)
            self.assertFalse(stale["fresh"])
            self.assertEqual(stale["changed_paths"], ["a.py", "b.py"])

            update_paths_validated_graph(
                directory=root,
                output_path=graph_path,
                paths=["a.py"],
                depth="symbols",
            )
            partial = inspect_saved_graph_freshness(directory=root, output_path=graph_path)
            self.assertFalse(partial["fresh"])
            self.assertEqual(partial["changed_paths"], ["b.py"])

            update_paths_validated_graph(
                directory=root,
                output_path=graph_path,
                paths=["b.py"],
                depth="symbols",
            )
            current = inspect_saved_graph_freshness(directory=root, output_path=graph_path)
            self.assertTrue(current["fresh"])
            self.assertEqual(current["changed_paths"], [])

    def test_member_call_staleness_fires_only_after_an_incremental_scan(self) -> None:
        # The STALE note exists because incremental scans copy the global
        # member-call counts across untouched, so a resolver change reads as
        # having done nothing. Its first implementation compared scanned-file
        # count against nodes-carrying-a-path (302 vs 6239) and fired on every
        # graph, including one full-scanned seconds earlier -- a warning that
        # is always on teaches readers to ignore it.
        from graphgraph.services.lifecycle import scan_validated_graph
        from graphgraph.services.project_status import build_project_status

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "app.py").write_text(
                "class Runner:\n"
                "    def go(self):\n"
                "        return self.step()\n\n"
                "    def step(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.gg"
            scan_validated_graph(directory=root, output_path=graph_path, depth="symbols")

            status = build_project_status(directory=root, graph_path=graph_path)
            member_calls = status["graph"]["member_calls"]
            self.assertFalse(
                member_calls["snapshot_may_be_stale"],
                "a freshly full-scanned graph must not be reported stale",
            )

            # An incremental pass carries the counts forward; say so.
            (root / "other.py").write_text("def added():\n    return 2\n", encoding="utf-8")
            scan_validated_graph(directory=root, output_path=graph_path, depth="symbols")
            after = build_project_status(directory=root, graph_path=graph_path)["graph"]["member_calls"]
            self.assertTrue(after["snapshot_may_be_stale"])
            self.assertIn("--no-incremental", after["staleness_note"])


if __name__ == "__main__":
    unittest.main()
