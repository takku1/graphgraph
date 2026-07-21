from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphgraph import (
    scan_directory,
)
from graphgraph.scanner.frontends import (
    _imported_symbol_names,
)


class ImportsScannerTest(unittest.TestCase):
    """scanner/imports.py: file-to-file import edges."""

    def test_imported_symbol_name_extraction(self) -> None:
        rust = "use crate::rules::{compile_rules_slice, RuleRecord};\nuse crate::foo::Bar as Baz;\n"
        py = "from server.auth import AuthService, TokenStore as Store\n"
        ts = "import { createApp, Router as R } from './app';\n"
        self.assertEqual(_imported_symbol_names(".rs", rust), {"compile_rules_slice", "RuleRecord", "Bar"})
        self.assertEqual(_imported_symbol_names(".py", py), {"AuthService", "TokenStore"})
        self.assertEqual(_imported_symbol_names(".ts", ts), {"createApp", "Router"})

    def test_scanner_detects_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("from db import connect\nfrom utils import helper\n", encoding="utf-8")
            (root / "db.py").write_text("def connect(): pass\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 3)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.label == "utils.py")
            self.assertIn((app_id, db_id), edge_pairs)
            self.assertIn((app_id, utils_id), edge_pairs)

    def test_scanner_resolves_indexed_java_csharp_and_lean_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "java").mkdir()
            (root / "java" / "Main.java").write_text("import pkg.Target;\nclass Main {}\n", encoding="utf-8")
            (root / "java" / "Target.java").write_text("class Target {}\n", encoding="utf-8")
            (root / "csharp").mkdir()
            (root / "csharp" / "Client.cs").write_text("using Company.Widget;\nclass Client {}\n", encoding="utf-8")
            (root / "csharp" / "Widget.cs").write_text("class Widget {}\n", encoding="utf-8")
            lean = root / "workspace" / "Lib"
            lean.mkdir(parents=True)
            (root / "Main.lean").write_text("import Lib.Util\n", encoding="utf-8")
            (lean / "Util.lean").write_text("def helper := 1\n", encoding="utf-8")

            graph = scan_directory(root)
            edge_paths = {
                (graph.nodes[edge.source].path, graph.nodes[edge.target].path, edge.type)
                for edge in graph.edges
                if edge.source in graph.nodes and edge.target in graph.nodes
            }

            self.assertIn(("java/Main.java", "java/Target.java", "imports"), edge_paths)
            self.assertIn(("csharp/Client.cs", "csharp/Widget.cs", "imports"), edge_paths)
            self.assertIn(("Main.lean", "workspace/Lib/Util.lean", "imports"), edge_paths)

    def test_scanner_detects_python_multiline_parenthesized_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "from db import (\n    connect,\n    disconnect as close\n)\n", encoding="utf-8"
            )
            (root / "db.py").write_text("def connect(): pass\ndef disconnect(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            self.assertIn((app_id, db_id), edge_pairs)

    def test_scanner_detects_python_relative_imports_and_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "pkg"
            sub = pkg / "sub"
            sub.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (sub / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "core.py").write_text("def connect(): pass\n", encoding="utf-8")
            (pkg / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            (sub / "worker.py").write_text(
                "from ..core import connect\nfrom . import local\nimport pkg.utils as utils\n",
                encoding="utf-8",
            )
            (sub / "local.py").write_text("def local(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            edge_pairs = {(e.source, e.target, e.type) for e in graph.edges}
            worker_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/sub/worker.py")
            core_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/core.py")
            local_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/sub/local.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/utils.py")

            self.assertIn((worker_id, core_id, "imports"), edge_pairs)
            self.assertIn((worker_id, local_id, "imports"), edge_pairs)
            self.assertIn((worker_id, utils_id, "imports"), edge_pairs)
            self.assertTrue(any(e.type == "contains" and e.target == worker_id for e in graph.edges))

    def test_scanner_c_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.c").write_text('#include "utils.h"\nint main(){}\n', encoding="utf-8")
            (root / "utils.h").write_text("void helper();\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)
            self.assertEqual(graph.edges[0].type, "imports")

    def test_scanner_go_relative_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text('import "./pkg"\nfunc main(){}\n', encoding="utf-8")
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "pkg.go").write_text("package pkg\n", encoding="utf-8")
            graph = scan_directory(root)
            # main.go and pkg/pkg.go should be nodes
            self.assertGreaterEqual(len(graph.nodes), 2)

    def test_scanner_html_href(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text('<a href="./about.html">About</a>\n', encoding="utf-8")
            (root / "about.html").write_text("<h1>About</h1>\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertTrue(any(e.type == "links" for e in graph.edges))

    def test_imported_symbol_sources(self) -> None:
        from graphgraph.scanner.frontends import _imported_symbol_sources

        # Test python imports
        py_text = "from my_module import foo, bar as b\nfrom other.helper import transform"
        py_sources = _imported_symbol_sources(".py", py_text)
        self.assertEqual(py_sources.get("foo"), "my_module")
        self.assertEqual(py_sources.get("bar"), "my_module")
        self.assertEqual(py_sources.get("transform"), "helper")

        # Test js/ts imports
        js_text = "import { transform, load as l } from './my_helper';\nimport { other } from '../another';"
        js_sources = _imported_symbol_sources(".ts", js_text)
        self.assertEqual(js_sources.get("transform"), "my_helper")
        self.assertEqual(js_sources.get("load"), "my_helper")
        self.assertEqual(js_sources.get("other"), "another")
