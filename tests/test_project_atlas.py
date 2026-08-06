from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from graphgraph.cli.parser import build_parser
from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.io.core import save_graph
from graphgraph.mcp import dispatch
from graphgraph.services.project_atlas import build_project_atlas


class ProjectAtlasTest(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        (root / "pyproject.toml").write_text(
            "[project]\n"
            'name = "atlas-fixture"\n'
            'version = "1.2.3"\n'
            "[project.scripts]\n"
            'atlas-fixture = "pkg.cli:main"\n',
            encoding="utf-8",
        )
        graph = Graph(
            nodes={
                "scan_file": Node("scan_file", "api.py", "python", "src/pkg/scanner/api.py"),
                "scan": Node("scan", "scan_project", "function", "src/pkg/scanner/api.py", "L12"),
                "parse": Node("parse", "parse_file", "function", "src/pkg/scanner/parser.py", "L4"),
                "retrieve_file": Node(
                    "retrieve_file", "context.py", "python", "src/pkg/retrieval/context.py"
                ),
                "retrieve": Node(
                    "retrieve", "retrieve_context", "function", "src/pkg/retrieval/context.py", "L21"
                ),
                "test_file": Node("test_file", "test_api.py", "python", "tests/test_api.py"),
                "test_scan": Node("test_scan", "test_scan_project", "function", "tests/test_api.py", "L8"),
            },
            edges=[
                Edge("parse", "scan", "calls"),
                Edge("scan", "retrieve", "calls"),
                Edge("test_scan", "scan", "calls"),
            ],
            metadata={
                "scan_depth": "symbols",
                "frontend": "tree_sitter",
                "ignore_rule_file_count": "1",
                "ignore_rule_files": ".gitignore",
                "ignore_pruned_dir_count": "1",
                "ignore_pruned_dirs": "vendor",
                "default_pruned_dir_count": "1",
                "default_pruned_dirs": ".venv",
            },
        )
        graph_path = root / ".graphgraph" / "graph.gg"
        graph_path.parent.mkdir()
        save_graph(graph, graph_path)
        return graph_path

    def test_atlas_is_grounded_deterministic_and_receipted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = self._project(root)
            first = build_project_atlas(directory=root, graph_path=graph_path)
            second = build_project_atlas(directory=root, graph_path=graph_path)

        first_without_timing = {**first, "receipt": {**first["receipt"]}}
        second_without_timing = {**second, "receipt": {**second["receipt"]}}
        first_without_timing["receipt"].pop("timings_ms")
        second_without_timing["receipt"].pop("timings_ms")
        self.assertEqual(first_without_timing, second_without_timing)
        self.assertEqual(first["schema"], "project_atlas_v1")
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["project"]["name"], "atlas-fixture")
        self.assertEqual(first["languages"], [{"language": "python", "files": 2}])
        self.assertEqual(first["entry_points"][0]["target"], "pkg.cli:main")
        by_name = {row["name"]: row for row in first["subsystems"]}
        self.assertEqual(by_name["scanner"]["representatives"][0]["path"], "src/pkg/scanner/api.py")
        self.assertIn("line", by_name["scanner"]["representatives"][0])
        self.assertEqual(first["couplings"][0]["from"], "scanner")
        self.assertEqual(first["couplings"][0]["to"], "retrieval")
        self.assertEqual(first["couplings"][0]["relations"], {"calls": 1})
        self.assertEqual(first["tests"]["files"], 1)
        self.assertEqual(first["tests"]["commands"][0]["confidence"], "candidate")
        self.assertEqual(first["coverage"]["exclusions"]["ignored_directories"], ["vendor"])
        self.assertEqual(first["receipt"]["nodes_considered"], 7)
        selection = first["receipt"]["selection"]
        self.assertEqual(selection["algorithm"], "prerequisite_marginal_coverage_per_character_v1")
        self.assertLessEqual(selection["evidence_chars"], selection["budget_chars"])
        selected_names = {row["name"] for row in first["subsystems"]}
        self.assertTrue(all(
            row["from"] in selected_names and row["to"] in selected_names
            for row in first["couplings"]
        ))

    def test_budget_smaller_than_base_payload_fails_visible_without_orphan_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = self._project(root)
            result = build_project_atlas(
                directory=root,
                graph_path=graph_path,
                evidence_budget_chars=1,
            )

        self.assertEqual(result["receipt"]["selection"]["binding"], "base_payload")
        self.assertEqual(result["subsystems"], [])
        self.assertEqual(result["couplings"], [])

    def test_cold_repo_returns_build_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_project_atlas(directory=Path(tmp))
        self.assertEqual(result["status"], "no_graph")
        self.assertEqual(result["next_action"], "build_graph")

    def test_cli_and_mcp_expose_same_atlas_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = self._project(root)

            args = build_parser().parse_args([
                "orient", "--directory", str(root), "--graph", str(graph_path), "--json"
            ])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                args.func(args)
            cli_payload = json.loads(stdout.getvalue())

            response = dispatch({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "project_status",
                    "arguments": {
                        "directory": str(root),
                        "graph_path": str(graph_path),
                        "view": "atlas",
                    },
                },
            })
            assert response is not None
            self.assertNotIn("error", response)
            mcp_payload = json.loads(response["result"]["content"][0]["text"])

        self.assertEqual(cli_payload["schema"], "project_atlas_v1")
        self.assertEqual(mcp_payload["schema"], cli_payload["schema"])
        self.assertEqual(mcp_payload["subsystems"], cli_payload["subsystems"])


class GoEcosystemAtlasTest(unittest.TestCase):
    """T-A05: found scanning a real Go repo (chartr) as part of building the
    held-out cross-language panel. Go was silently invisible on three axes at
    once -- no ecosystem/module detection (only pyproject.toml/package.json/
    Cargo.toml were read), no entry-point detection (only Rust's src/main.rs
    had a rule), and _test.go files were not recognized as tests (the suffix
    allowlist had _test.py/.test.js/.test.ts but not Go's own convention) --
    even though the underlying scan correctly extracted every node.
    """

    def _go_project(self, root: Path) -> Path:
        (root / "go.mod").write_text(
            "module github.com/example/widget\n\ngo 1.22\n",
            encoding="utf-8",
        )
        graph = Graph(
            nodes={
                "main_file": Node("main_file", "main.go", "go", "cmd/widget/main.go"),
                "main_fn": Node("main_fn", "main", "function", "cmd/widget/main.go", "L5"),
                "run_fn": Node("run_fn", "Run", "function", "internal/app/run.go", "L3"),
                "test_file": Node("test_file", "run_test.go", "go", "internal/app/run_test.go"),
                "test_fn": Node("test_fn", "TestRun", "function", "internal/app/run_test.go", "L4"),
            },
            edges=[Edge("main_fn", "run_fn", "calls")],
        )
        graph_path = root / ".graphgraph" / "graph.gg"
        graph_path.parent.mkdir()
        save_graph(graph, graph_path)
        return graph_path

    def test_go_module_binary_and_tests_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = self._go_project(root)
            result = build_project_atlas(directory=root, graph_path=graph_path)

        self.assertEqual(result["project"]["name"], "widget")
        self.assertEqual(result["project"]["version"], "1.22")
        self.assertEqual(len(result["entry_points"]), 1)
        self.assertEqual(result["entry_points"][0]["target"], "cmd/widget/main.go")
        self.assertEqual(result["entry_points"][0]["kind"], "go_entry")
        self.assertEqual(result["tests"]["files"], 1)
        self.assertIn(
            "go test ./...",
            {row["command"] for row in result["tests"]["commands"]},
        )


class UnparsedEcosystemAtlasTest(unittest.TestCase):
    """The Go fix above was originally written as one more hand-added branch,
    which would have left Java/C#/Ruby/PHP/Kotlin/Scala/Swift/C/C++ failing
    identically -- discoverable only by someone happening to scan one. These
    ecosystems have no bespoke manifest parser and still must be detected,
    still must recognize their own test-file conventions, and still must
    surface a runnable test command.
    """

    def _java_project(self, root: Path) -> Path:
        (root / "pom.xml").write_text(
            "<project><artifactId>widget</artifactId></project>", encoding="utf-8"
        )
        graph = Graph(
            nodes={
                "app": Node("app", "App", "class", "src/main/java/com/example/App.java", "L5"),
                "main_fn": Node("main_fn", "main", "method", "src/main/java/com/example/App.java", "L7"),
                # Java's convention is a `*Test.java` suffix, not a `test_`
                # prefix or a `tests/` directory -- neither of the rules that
                # existed before the registry would have caught this file.
                "test": Node("test", "AppTest", "class", "src/main/java/com/example/AppTest.java", "L4"),
            },
            edges=[],
        )
        graph_path = root / ".graphgraph" / "graph.gg"
        graph_path.parent.mkdir()
        save_graph(graph, graph_path)
        return graph_path

    def test_java_maven_project_is_not_invisible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = self._java_project(root)
            result = build_project_atlas(directory=root, graph_path=graph_path)

        self.assertIn("maven", result["project"]["ecosystems"])
        self.assertIn("mvn test", {row["command"] for row in result["tests"]["commands"]})
        self.assertEqual(result["tests"]["files"], 1)
        self.assertEqual(
            [row["target"] for row in result["entry_points"]],
            ["src/main/java/com/example/App.java"],
        )

    def test_dotnet_solution_is_detected_by_suffix_not_exact_filename(self) -> None:
        # .NET has no single fixed manifest name -- the marker is any
        # *.sln/*.csproj -- so exact-filename matching alone cannot see it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Widget.csproj").write_text("<Project/>", encoding="utf-8")
            graph = Graph(
                nodes={
                    "svc": Node("svc", "Service", "class", "src/Service.cs", "L3"),
                    "test": Node("test", "ServiceTests", "class", "src/ServiceTests.cs", "L4"),
                },
                edges=[],
            )
            graph_path = root / ".graphgraph" / "graph.gg"
            graph_path.parent.mkdir()
            save_graph(graph, graph_path)
            result = build_project_atlas(directory=root, graph_path=graph_path)

        self.assertIn("dotnet", result["project"]["ecosystems"])
        self.assertIn("dotnet test", {row["command"] for row in result["tests"]["commands"]})
        self.assertEqual(result["tests"]["files"], 1)


if __name__ == "__main__":
    unittest.main()
