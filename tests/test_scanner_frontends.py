from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import (
    scan_directory,
)
from graphgraph.scanner.ast import extract_symbols
from graphgraph.scanner.frontends import (
    RegexExtractor,
    SourceFile,
    TreeSitterExtractor,
    available_frontends,
    parser_for_suffix,
    select_extractor,
    tree_sitter_available,
)


class FrontendsScannerTest(unittest.TestCase):
    """scanner/frontends/: grammars, parsers, and language extraction."""

    def test_pathologically_nested_python_source_does_not_crash_type_inference(self) -> None:
        # Adversarial: ast.parse raises RecursionError (a RuntimeError, not a
        # SyntaxError) on deeply nested expressions -- e.g. a generated or
        # minified file with one long chained expression (`1+1+...` at ~10k
        # terms builds a left-recursive BinOp tree deeper than the recursion
        # limit). The python type-inference helpers only caught
        # IndentationError/SyntaxError/ValueError, so ONE such file aborted
        # the entire repository scan with a raw traceback and no graph
        # written. Unparseable-for-any-reason source must degrade to "no
        # inference", exactly like a syntax error does.
        from graphgraph.scanner.frontends.python import (
            _python_class_field_types,
            _python_local_types,
        )

        chained = "def gen():\n    x = " + "+".join(["1"] * 20000)
        self.assertEqual(_python_local_types(chained), {})
        self.assertEqual(_python_class_field_types(chained), {})

    def test_javascript_assignment_and_prototype_callables_are_definitions(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var res = {};\n"
            "res.send = function send(body) { return body; };\n"
            "function View() {}\n"
            "View.prototype.render = function render(options, callback) {\n"
            "  callback(null, options);\n"
            "};\n"
            "const normalize = (value) => value;\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "response.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "response.js", "response_js", source)],
                max_total_symbols=100,
            )

        by_label = {node.label: node for node in result.nodes.values()}
        self.assertIn("send", by_label)
        self.assertIn("render", by_label)
        self.assertIn("normalize", by_label)
        self.assertIn(
            "javascript_definition:property_assignment",
            by_label["send"].facts,
        )
        self.assertIn(
            "javascript_definition:prototype_assignment",
            by_label["render"].facts,
        )
        self.assertIn(
            "javascript_definition:variable_callable",
            by_label["normalize"].facts,
        )

    def test_javascript_anonymous_test_callback_becomes_a_grounded_node(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = "it('sends a response', function(done) {\n  done();\n});\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "response.test.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "response.test.js", "response_test_js", source)],
                max_total_symbols=100,
            )

        callbacks = [node for node in result.nodes.values() if "javascript_definition:callback" in node.facts]
        self.assertEqual(len(callbacks), 1)
        self.assertTrue(callbacks[0].label.startswith("it_callback_L1C"))
        self.assertIn("callback_registered_by:it", callbacks[0].facts)
        self.assertIn("role:test", callbacks[0].facts)

    def test_member_call_telemetry_is_partitioned_by_language(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "store.py": (
                "class Store:\n"
                "    def persist(self, value):\n"
                "        return value\n"
                "def save(store: Store):\n"
                "    return store.persist(1)\n"
            ),
            "box.js": (
                "class Box { push(value) { return value; } }\n"
                "function append() {\n"
                "  const box = new Box();\n"
                "  return box.push(1);\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for rel, text in sources.items():
                path = Path(tmp) / rel
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

        by_language = {
            language: {
                "resolved": resolved,
                "ambiguous": ambiguous,
                "unknown_receiver": unknown_receiver,
                "external_resolved": external_resolved,
                "unmatched": unmatched,
            }
            for (
                language,
                resolved,
                ambiguous,
                unknown_receiver,
                external_resolved,
                unmatched,
            ) in result.member_calls_by_language
        }
        self.assertGreaterEqual(by_language["python"]["resolved"], 1)
        self.assertGreaterEqual(by_language["javascript"]["resolved"], 1)
        self.assertEqual(
            sum(item["resolved"] for item in by_language.values()),
            result.resolved_member_calls,
        )

    def test_frontend_capabilities(self) -> None:
        caps = available_frontends()
        names = {cap.name for cap in caps}
        self.assertIn("regex", names)
        self.assertIn("tree_sitter", names)
        self.assertTrue(next(cap for cap in caps if cap.name == "regex").available)

    def test_csharp_member_calls_resolve_from_local_and_param_types(self) -> None:
        # Regression for the C# 0/6,454 finding (cycle 8): the edge builder had
        # no local-type inference for .cs, so every member call went unresolved.
        # New-expression locals, typed parameters, and this.Method() (C#'s
        # member_access object lives on the `expression` field) must all resolve
        # to the correct owner.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "namespace App {\n"
            "  public class Store {\n"
            "    public int Persist(int item) { return item; }\n"
            "    public int Load() { return 0; }\n"
            "  }\n"
            "  public class Service {\n"
            "    public int Run(Store injected) {\n"
            "      Store local = new Store();\n"
            "      local.Persist(1);\n"
            "      injected.Load();\n"
            "      return this.Helper();\n"
            "    }\n"
            "    public int Helper() { return 42; }\n"
            "  }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Store.cs"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "Store.cs", "Store_cs", source)],
                max_total_symbols=100,
            )

        self.assertGreaterEqual(result.resolved_member_calls, 3)
        resolved = {
            (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
        }
        self.assertIn(("Run", "Persist"), resolved)  # new-expression local
        self.assertIn(("Run", "Load"), resolved)  # typed parameter
        self.assertIn(("Run", "Helper"), resolved)  # this.Method()

    def test_module_qualified_calls_resolve_via_imports(self) -> None:
        # F3 (graybox 2026-07-22): `module.func()` where `module` is imported
        # and `func` is defined in that module went entirely unresolved, even
        # though the import + contains edges were already in the graph. Plain
        # and aliased imports must both resolve; a class-instance call in the
        # same file must still resolve via the receiver-type path, untouched.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "io_utils.py": "def load_metadata(p):\n    return {}\n",
            "store.py": "class Store:\n    def persist(self, x):\n        return x\n",
            "app.py": (
                "import io_utils\n"
                "from store import Store\n"
                "def run(path):\n"
                "    meta = io_utils.load_metadata(path)\n"
                "    s = Store()\n"
                "    s.persist(meta)\n"
                "    return meta\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for rel, text in sources.items():
                path = Path(tmp) / rel
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        by_provenance = {
            (result.nodes[e.source].label, result.nodes[e.target].label): e.provenance
            for e in result.edges
            if e.type == "calls"
        }
        # Module-qualified call resolved through the import join.
        self.assertEqual(by_provenance.get(("run", "load_metadata")), "tree_sitter_module_qualified")
        # Class-instance call still resolves via the receiver-type path.
        self.assertEqual(by_provenance.get(("run", "persist")), "tree_sitter_type_resolved")

    def test_python_package_reexports_and_nested_modules_resolve_calls(self) -> None:
        """Resolve Flask-shaped package APIs without leaf-name guessing."""
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "flask/helpers.py": "def make_response(value=None):\n    return value\n",
            "flask/__init__.py": (
                "from . import helpers as helpers\nfrom .helpers import make_response as make_response\n"
            ),
            "tests/test_basic.py": (
                "import flask.views\n"
                "def test_public_api():\n"
                "    flask.make_response('public')\n"
                "def test_nested_api():\n"
                "    flask.helpers.make_response('nested')\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for rel, text in sources.items():
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

        targets = {
            result.nodes[edge.source].label: result.nodes[edge.target].path
            for edge in result.edges
            if edge.type == "calls"
            and edge.source in result.nodes
            and edge.target in result.nodes
            and result.nodes[edge.source].label in {"test_public_api", "test_nested_api"}
            and result.nodes[edge.target].label == "make_response"
        }
        self.assertEqual(
            targets,
            {
                "test_public_api": "flask/helpers.py",
                "test_nested_api": "flask/helpers.py",
            },
        )

    def test_python_test_attribute_reads_and_writes_are_structural_evidence(self) -> None:
        """A field wrapper is affected-test evidence, but is not a call."""
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/flask/app.py": ("class Flask:\n    def wsgi_app(self, environ, start_response):\n        return []\n"),
            # Same-name non-fixture functions must not poison pytest's fixture
            # binding. Flask has exactly this shape in src/flask/cli.py.
            "src/flask/cli.py": "def app() -> Iterable:\n    return ()\n",
            "tests/conftest.py": (
                "import pytest\n"
                "from flask import Flask\n"
                "@pytest.fixture\n"
                "def app():\n"
                "    app = Flask('test')\n"
                "    return app\n"
            ),
            "tests/test_basic.py": (
                "def test_session_using_application_root(app):\n"
                "    app.wsgi_app = PrefixPathMiddleware(app.wsgi_app, '/bar')\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for rel, text in sources.items():
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

        evidence = {
            edge.type
            for edge in result.edges
            if edge.source in result.nodes
            and edge.target in result.nodes
            and result.nodes[edge.source].label == "test_session_using_application_root"
            and result.nodes[edge.target].label == "wsgi_app"
        }
        self.assertEqual(evidence, {"reads", "writes"})

    def test_module_qualified_resolution_is_unit_testable(self) -> None:
        from graphgraph.scanner.frontends.module_calls import (
            module_alias_targets,
            resolve_module_qualified_call,
        )

        aliases = module_alias_targets(
            ".py",
            "import model_io\nimport pkg.tools\nfrom pkg import model_io as mio\nimport os.path as osp\n",
        )
        self.assertEqual(aliases.get("model_io"), "model_io")
        # Python binds both the top-level package name and makes the imported
        # dotted module addressable through that package.
        self.assertEqual(aliases.get("pkg"), "pkg")
        self.assertEqual(aliases.get("pkg.tools"), "pkg.tools")
        self.assertEqual(aliases.get("mio"), "pkg.model_io")
        self.assertEqual(aliases.get("osp"), "os.path")

        from graphgraph.graph.core import Node
        from graphgraph.scanner.frontends.syntax import _lang_family

        lang = _lang_family("x.py")
        nodes = {
            "pkg_model_io_py__load_metadata": Node(
                "pkg_model_io_py__load_metadata", "load_metadata", "function", "pkg/model_io.py"
            ),
            "other_model_io_py__load_metadata": Node(
                "other_model_io_py__load_metadata", "load_metadata", "function", "other/model_io.py"
            ),
        }
        name_to_symbols = {"load_metadata": list(nodes)}
        # A full `pkg.model_io` path disambiguates between two same-stem files.
        self.assertEqual(
            resolve_module_qualified_call(
                "mio", "load_metadata", {"mio": "pkg.model_io"}, name_to_symbols, nodes, "caller", lang
            ),
            "pkg_model_io_py__load_metadata",
        )
        # A leaf-only `model_io` against two same-stem files is ambiguous -> None.
        self.assertIsNone(
            resolve_module_qualified_call(
                "model_io", "load_metadata", {"model_io": "model_io"}, name_to_symbols, nodes, "caller", lang
            )
        )
        # An unimported receiver is never a module call.
        self.assertIsNone(
            resolve_module_qualified_call("self", "load_metadata", {}, name_to_symbols, nodes, "caller", lang)
        )

    def test_js_module_alias_targets_from_require_and_import(self) -> None:
        from graphgraph.scanner.frontends.module_calls import module_alias_targets

        aliases = module_alias_targets(
            ".js",
            "const store = require('./store');\n"
            "const fmt = require('../lib/format.js');\n"
            "import * as util from './util';\n"
            "import cfg from './config/index';\n"
            "import { named } from './named';\n",  # named binding is not a namespace
        )
        self.assertEqual(aliases.get("store"), "store")
        self.assertEqual(aliases.get("fmt"), "lib.format")
        self.assertEqual(aliases.get("util"), "util")
        self.assertEqual(aliases.get("cfg"), "config")  # trailing index dropped
        self.assertNotIn("named", aliases)  # destructured export, not a module

    def test_js_named_local_from_factory_return_type_resolves(self) -> None:
        # `const s = createStore()` where `createStore` returns `new Store()`:
        # the local's type is the factory's inferred return type, so `s.save()`
        # must resolve to `Store.save`. This is the dominant unresolved JS
        # receiver shape (`named_local`) for the factory pattern.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "class Store {\n"
            "  save(x) { return x; }\n"
            "}\n"
            "function createStore() { return new Store(); }\n"
            "function run() {\n"
            "  const s = createStore();\n"
            "  return s.save(1);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "app.js", "app_js", source)], max_total_symbols=100
            )
        resolved = {
            (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
        }
        self.assertIn(("run", "save"), resolved)

    def test_js_property_assignment_owner_resolves_this_calls(self) -> None:
        # Annotation-free prototype objects still carry exact structural
        # ownership: both methods are assigned to `res`, and `this` inside
        # `res.send` therefore denotes the same owner.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var res = {}\n"
            "res.send = function send(value) { return this.json(value) }\n"
            "res.json = function json(value) { return value }\n"
            "res.render = function render(value) { var self = this; return self.json(value) }\n"
            "res.unproven = function unproven(self, value) { return self.json(value) }\n"
            "res.arrow = (value) => this.json(value)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "response.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "response.js", "response_js", source)],
                max_total_symbols=100,
            )

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("send", "json"), calls)
        self.assertIn(("render", "json"), calls)
        self.assertNotIn(("unproven", "json"), calls)
        self.assertNotIn(("arrow", "json"), calls)
        send = next(node for node in result.nodes.values() if node.label == "send")
        self.assertIn("javascript_owner:res", send.facts)
        self.assertIn("__res__send", send.id)

    def test_js_structural_owner_does_not_cross_module_by_spelling(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "first.js": "var res = {}\nres.send = function send(value) { return this.json(value) }\n",
            "second.js": "var res = {}\nres.json = function json(value) { return value }\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, source in sources.items():
                path = Path(tmp) / name
                path.write_text(source, encoding="utf-8")
                files.append(SourceFile(path, name, name.replace(".", "_"), source))
            result = select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertNotIn(("send", "json"), calls)
        self.assertEqual(result.unmatched_member_calls, 1)

    def test_js_known_property_copy_types_function_object_receiver(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "lib/application.js": (
                "var app = exports = module.exports = {}\n"
                "app.init = function init() { return this.handle() }\n"
                "app.handle = function handle() { return 1 }\n"
            ),
            "lib/express.js": (
                "var mixin = require('merge-descriptors')\n"
                "var proto = require('./application')\n"
                "function createApplication() {\n"
                "  var app = function(req, res) { return app.handle(req, res) }\n"
                "  mixin(app, proto, false)\n"
                "  app.init()\n"
                "  return app\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, name, name.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(
                files, max_total_symbols=100
            )

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("createApplication", "init"), calls)
        handle_edges = [
            edge
            for edge in result.edges
            if edge.type == "calls" and result.nodes[edge.target].label == "handle"
        ]
        self.assertTrue(handle_edges)
        create_id = next(node.id for node in result.nodes.values() if node.label == "createApplication")
        self.assertTrue(any(result.nodes[edge.source].parent == create_id for edge in handle_edges))

    def test_js_commonjs_default_export_propagates_structural_return_type(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "lib/application.js": (
                "var app = module.exports = {}\n"
                "app.handle = function handle() {}\n"
            ),
            "lib/express.js": (
                "var mixin = require('merge-descriptors')\n"
                "var proto = require('./application')\n"
                "function createApplication() {\n"
                "  var app = function() {}\n"
                "  mixin(app, proto)\n"
                "  return app\n"
                "}\n"
                "module.exports = createApplication\n"
            ),
            "index.js": "module.exports = require('./lib/express')\n",
            "test/app.js": (
                "var express = require('../')\n"
                "function run() { var app = express(); return app.handle() }\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, name, name.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label, edge.evidence)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertTrue(
            any(source == "run" and target == "handle" and "receiver app:lib/application.js::app" in evidence
                for source, target, evidence in calls)
        )

    def test_js_structural_handler_protocol_types_request_response_parameters(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "lib/application.js": (
                "var app = module.exports = {}\n"
                "app.use = function use() {}\n"
                "app.handle = function handle() {}\n"
                "app.route = function route() {}\n"
                "app.get = function get() {}\n"
            ),
            "lib/request.js": (
                "var req = module.exports = {}\n"
                "req.get = function get() {}\n"
                "req.header = function header() {}\n"
                "req.accepts = function accepts() {}\n"
                "req.is = function is() {}\n"
                "req.range = function range() {}\n"
            ),
            "lib/response.js": (
                "var res = module.exports = {}\n"
                "res.send = function send() {}\n"
                "res.json = function json() {}\n"
                "res.status = function status() {}\n"
            ),
            "lib/express.js": (
                "var mixin = require('merge-descriptors')\n"
                "var proto = require('./application')\n"
                "function createApplication() {\n"
                "  var app = function() {}\n"
                "  mixin(app, proto)\n"
                "  return app\n"
                "}\n"
                "module.exports = createApplication\n"
            ),
            "index.js": "module.exports = require('./lib/express')\n",
            "test/app.js": (
                "var express = require('../')\n"
                "function scenario() {\n"
                "  var app = express()\n"
                "  app.get('/', function(req, res) { return res.send(req.get('x')) })\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, name, name.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=200)

        call_targets = {
            result.nodes[edge.target].label
            for edge in result.edges
            if edge.type == "calls" and result.nodes[edge.source].label.startswith("get_callback_")
        }
        self.assertEqual(call_targets, {"get", "send"})

    def test_js_incomplete_handler_shape_does_not_type_callback_parameters(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var app = {}\n"
            "app.use = function use() {}\n"
            "app.handle = function handle() {}\n"
            "app.route = function route() {}\n"
            "var req = {}\n"
            "req.get = function get() {}\n"
            "var res = {}\n"
            "res.send = function send() {}\n"
            "function scenario() { app.use(function(req, res) { return res.send(req.get('x')) }) }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "local.js", "local_js", source)],
                max_total_symbols=100,
            )

        self.assertGreaterEqual(result.unknown_receiver_member_calls, 2)

    def test_js_unknown_mixin_does_not_type_function_object_receiver(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "application.js": "var app = {}\napp.handle = function handle() {}\n",
            "express.js": (
                "var proto = require('./application')\n"
                "function mixin(a, b) { return a }\n"
                "function createApplication() {\n"
                "  var app = function() {}\n"
                "  mixin(app, proto)\n"
                "  app.handle()\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                path = Path(tmp) / name
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, name, name.replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(
                files, max_total_symbols=100
            )

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertNotIn(("createApplication", "handle"), calls)

    def test_js_getter_and_external_api_summary_connect_router_handle(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var Router = require('router')\n"
            "var app = {}\n"
            "app.init = function init() {\n"
            "  Object.defineProperty(this, 'router', {\n"
            "    get: function () { return new Router({}) }\n"
            "  })\n"
            "}\n"
            "app.handle = function handle(req, res) {\n"
            "  return this.router.handle(req, res)\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "application.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "application.js", "application_js", source)],
                max_total_symbols=100,
            )

        external = [node for node in result.nodes.values() if node.kind == "external"]
        self.assertEqual([node.summary for node in external], ["router:Router::handle"])
        edges = [
            edge
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "handle"
            and result.nodes[edge.target].kind == "external"
        ]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].provenance, "external_api_summary")

    def test_js_unknown_external_package_does_not_gain_router_summary(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var Router = require('unrelated-router')\n"
            "var app = {}\n"
            "Object.defineProperty(app, 'router', { get: function () { return new Router({}) } })\n"
            "app.handle = function handle() { return this.router.handle() }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "application.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "application.js", "application_js", source)],
                max_total_symbols=100,
            )

        self.assertFalse(any(node.kind == "external" for node in result.nodes.values()))

    def test_js_import_proven_external_namespace_and_call_result_are_attributed(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "const assert = require('node:assert')\n"
            "const request = require('supertest')\n"
            "var app = {}\n"
            "app.get = function get() {}\n"
            "app.set = function set() {}\n"
            "function run(app) {\n"
            "  const test = request(app)\n"
            "  assert.equal(1, 1)\n"
            "  test.set('x', 'y')\n"
            "  return request(app).get('/')\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "app.js", "app_js", source)],
                max_total_symbols=100,
            )

        external_edges = [
            edge
            for edge in result.edges
            if edge.type == "calls" and result.nodes[edge.target].kind == "external"
        ]
        self.assertEqual({result.nodes[edge.target].label for edge in external_edges}, {"equal", "get", "set"})
        self.assertTrue(all(edge.provenance == "tree_sitter_external_receiver" for edge in external_edges))
        self.assertTrue(all("imported package" in edge.evidence for edge in external_edges))
        self.assertEqual(result.unknown_receiver_member_calls, 0)

    def test_js_local_factory_does_not_gain_external_call_result_evidence(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var app = {}\n"
            "app.get = function get() {}\n"
            "function request() { return {} }\n"
            "function run(app) { return request(app).get('/') }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "app.js", "app_js", source)],
                max_total_symbols=100,
            )

        self.assertFalse(any(node.kind == "external" for node in result.nodes.values()))
        self.assertEqual(result.unknown_receiver_member_calls, 1)

    def test_js_nested_callback_calls_are_attributed_once_to_innermost_callable(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "var api = {}\n"
            "api.send = function send() {}\n"
            "function wrap(callback) { return callback }\n"
            "function outer() {\n"
            "  return wrap(function inner(req) { return req.send() })\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "nested.js", "nested_js", source)],
                max_total_symbols=100,
            )

        self.assertEqual(result.unknown_receiver_member_calls, 1)

    def test_js_prototype_assignment_owner_resolves_this_calls(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "function Store() {}\n"
            "Store.prototype.save = function save(value) { return this.load(value) }\n"
            "Store.prototype.load = function load(value) { return value }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.js"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "store.js", "store_js", source)],
                max_total_symbols=100,
            )

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("save", "load"), calls)

    def test_js_module_qualified_calls_resolve_via_require(self) -> None:
        # A CommonJS/ESM module receiver (`store.persist()` where `store` is a
        # required/imported module) must resolve like Python's `module.func()`.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "store.js": "function persist(x){return x;}\nmodule.exports = { persist };\n",
            "app.js": ("const store = require('./store');\nfunction run(){ return store.persist(1); }\n"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                path = Path(tmp) / name
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, name, name.replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)
        by_provenance = {
            (result.nodes[e.source].label, result.nodes[e.target].label): e.provenance
            for e in result.edges
            if e.type == "calls"
        }
        self.assertEqual(by_provenance.get(("run", "persist")), "tree_sitter_module_qualified")

    def test_java_member_calls_resolve(self) -> None:
        # Java was worse than C#'s 0/6,454: its `method_invocation` carries the
        # receiver as a sibling `object` field, so calls read as bare
        # identifiers and were never even detected as member calls (0 sites).
        # Detecting the direct object field + reusing the C#/Java local-type
        # inference must resolve locals, parameters, and this.method().
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "class Store {\n"
            "    int persist(int item) { return item; }\n"
            "    int load() { return 0; }\n"
            "}\n"
            "class Service {\n"
            "    int run(Store injected) {\n"
            "        Store local = new Store();\n"
            "        local.persist(1);\n"
            "        injected.load();\n"
            "        return this.helper();\n"
            "    }\n"
            "    int helper() { return 42; }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Service.java"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "Service.java", "Service_java", source)],
                max_total_symbols=100,
            )

        self.assertGreaterEqual(result.resolved_member_calls, 3)
        resolved = {
            (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
        }
        self.assertIn(("run", "persist"), resolved)
        self.assertIn(("run", "load"), resolved)
        self.assertIn(("run", "helper"), resolved)

    def test_csharp_field_receiver_calls_resolve(self) -> None:
        # T13: field receivers (`_repo.Save()`) are the dominant real-world
        # C#/Java member-call shape and were unresolved -- a field's type lives
        # at class level, invisible to the method-body local inference. The
        # field declaration names the type; a bare field receiver and the
        # explicit `this._repo` form must both resolve to it.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "namespace App {\n"
            "  public class Repo {\n"
            "    public int Save(int x) { return x; }\n"
            "  }\n"
            "  public class Service {\n"
            "    private readonly Repo _repo;\n"
            "    public Service(Repo repo) { _repo = repo; }\n"
            "    public int Run() {\n"
            "      _repo.Save(1);\n"
            "      return this._repo.Save(2);\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Service.cs"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "Service.cs", "Service_cs", source)],
                max_total_symbols=100,
            )
        resolved = {
            (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
        }
        self.assertIn(("Run", "Save"), resolved)

    def test_csharp_inherited_property_receiver_resolves_across_files(self) -> None:
        # Q02-D held-out UniGetUI slice: PackageManager declares
        # `IManagerLogger TaskLogger`, while derived manager classes call
        # `TaskLogger.CreateNew()` from other files. The property is inherited,
        # so looking only at fields declared on the callable's immediate owner
        # leaves every such call untyped. An unrelated same-named property and
        # method are the precision guard against name-only resolution.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "Logging.cs": (
                "public interface IManagerLogger {\n"
                "  int CreateNew();\n"
                "}\n"
                "public class WrongLogger {\n"
                "  public int CreateNew() { return 9; }\n"
                "}\n"
                "public class Other {\n"
                "  public WrongLogger TaskLogger { get; }\n"
                "}\n"
            ),
            "PackageManager.cs": (
                "public abstract class PackageManager {\n"
                "  public IManagerLogger TaskLogger { get; }\n"
                "}\n"
            ),
            "Snap.cs": (
                "public class Snap : PackageManager {\n"
                "  public int Refresh() { return TaskLogger.CreateNew(); }\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, source in sources.items():
                path = root / rel
                path.write_text(source, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace(".", "_"), source))
            result = select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

        targets = {
            result.nodes[result.nodes[edge.target].parent].label
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "Refresh"
            and result.nodes[edge.target].label == "CreateNew"
        }
        self.assertEqual({"IManagerLogger"}, targets)
        implements = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "implements"
        }
        self.assertIn(("Snap", "PackageManager"), implements)

    def test_same_named_csharp_type_elsewhere_does_not_hide_local_field(self) -> None:
        # Type names are not globally unique inside one language. Project-wide
        # facts for two `Handler._repo` declarations must become ambiguous,
        # while the declaration in the caller's own file remains exact.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "Good.cs": (
                "namespace GoodSpace;\n"
                "public class GoodRepo { public void Save() {} }\n"
                "public class Handler {\n"
                "  private GoodRepo _repo;\n"
                "  public void Run() { _repo.Save(); }\n"
                "}\n"
            ),
            "Wrong.cs": (
                "namespace WrongSpace;\n"
                "public class WrongRepo { public void Save() {} }\n"
                "public class Handler { private WrongRepo _repo; }\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, source in sources.items():
                path = root / rel
                path.write_text(source, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace(".", "_"), source))
            result = select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

        targets = {
            result.nodes[result.nodes[edge.target].parent].label
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "Run"
            and result.nodes[edge.target].label == "Save"
        }
        self.assertEqual({"GoodRepo"}, targets)

    def test_java_field_receiver_calls_resolve(self) -> None:
        # T13: the Java analogue -- `repo.save()` on a declared field, plus the
        # explicit `this.repo` form.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "class Repo {\n"
            "    int save(int x) { return x; }\n"
            "}\n"
            "class Service {\n"
            "    private final Repo repo;\n"
            "    Service(Repo repo) { this.repo = repo; }\n"
            "    int run() {\n"
            "        repo.save(1);\n"
            "        return this.repo.save(2);\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Service.java"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "Service.java", "Service_java", source)],
                max_total_symbols=100,
            )
        resolved = {
            (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
        }
        self.assertIn(("run", "save"), resolved)

    def test_cpp_inline_method_field_receiver_calls_resolve(self) -> None:
        # T13: C++ class/struct specifiers establish lexical ownership, and a
        # class-scope field declaration types the bare `repo_` receiver.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source = (
            "class Repo {\n"
            "public:\n"
            "  int save(int x) { return x; }\n"
            "};\n"
            "class Service {\n"
            "  Repo repo_;\n"
            "public:\n"
            "  int run() { return repo_.save(1); }\n"
            "};\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "service.cpp"
            path.write_text(source, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "service.cpp", "service_cpp", source)],
                max_total_symbols=100,
            )
        callables = [n for n in result.nodes.values() if n.label in {"save", "run"}]
        self.assertTrue(callables, "expected the inline callables to be extracted")
        self.assertTrue(all(n.kind == "method" for n in callables))
        self.assertEqual(
            {n.label for n in result.nodes.values() if n.kind in {"class", "struct"}},
            {"Repo", "Service"},
        )
        resolved = {
            (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
        }
        self.assertIn(("run", "save"), resolved)

    def test_cpp_class_field_types_unit(self) -> None:
        from graphgraph.scanner.frontends.cpp import cpp_class_field_types

        types = cpp_class_field_types(
            "class Service {\n  Repo repo_;\n  Store* store;\n  int count;\n  void run() { Local local; }\n};"
        )
        self.assertEqual(types.get(("Service", "repo_")), "Repo")
        self.assertEqual(types.get(("Service", "store")), "Store")
        self.assertNotIn(("Service", "count"), types)
        self.assertNotIn(("Service", "local"), types)

    def test_csharp_class_field_types_unit(self) -> None:
        from graphgraph.scanner.frontends.csharp import csharp_class_field_types

        types = csharp_class_field_types(
            "public class Service {\n"
            "  private readonly Repo _repo;\n"
            "  public Cache Cache { get; set; }\n"
            "  private int _count;\n"
            "  public void Run() { Local l = new Local(); }\n"
            "}"
        )
        self.assertEqual(types.get(("Service", "_repo")), "Repo")  # field
        self.assertEqual(types.get(("Service", "Cache")), "Cache")  # auto-property
        self.assertNotIn(("Service", "_count"), types)  # primitive field
        # A method-body local has no access modifier, so the field scan -- which
        # requires one -- must not mistake it for a class field.
        self.assertNotIn(("Service", "l"), types)

    def test_csharp_local_type_inference_unit(self) -> None:
        from graphgraph.scanner.frontends.csharp import csharp_local_types

        types = csharp_local_types(
            "public int Run(Store injected, int count) {\n"
            "  Store local = new Store();\n"
            "  Widget w = Build();\n"
            "  var ignored = 3;\n"
            "}"
        )
        self.assertEqual(types.get("injected"), "Store")  # parameter
        self.assertEqual(types.get("local"), "Store")  # new-expression
        self.assertEqual(types.get("w"), "Widget")  # declared type
        self.assertNotIn("count", types)  # primitive param
        self.assertNotIn("ignored", types)  # untyped var

    def test_cpg_is_advertised_as_planned_not_usable(self) -> None:
        # cpg has no extractor and select_extractor would fall back to regex.
        # It must not report as available/selectable, and requesting it must
        # fail loudly rather than silently degrade a type-evidence request.
        from graphgraph.scanner.frontends import select_extractor

        cpg = next(cap for cap in available_frontends() if cap.name == "cpg")
        self.assertFalse(cpg.available)
        self.assertFalse(cpg.selectable)
        self.assertIn("PLANNED", cpg.description)
        with self.assertRaises(RuntimeError):
            select_extractor("cpg")

    def test_frontend_capabilities_report_per_language_readiness(self) -> None:
        with patch(
            "graphgraph.scanner.frontends.languages._language_available",
            side_effect=lambda name: name == "python",
        ):
            tree_sitter = next(capability for capability in available_frontends() if capability.name == "tree_sitter")

        self.assertEqual(tree_sitter.ready_languages, ("python",))
        self.assertIn("typescript", tree_sitter.unavailable_languages)
        self.assertTrue(tree_sitter.available)

    def test_language_readiness_requires_a_constructible_parser(self) -> None:
        with patch(
            "graphgraph.scanner.frontends.languages._parser_for_language",
            return_value=None,
        ):
            self.assertFalse(tree_sitter_available())

    def test_transient_grammar_failure_is_retried_instead_of_cached(self) -> None:
        # grammar loading (and its find_spec/import_module lookups) lives in the
        # languages layer, so patch there rather than on the package facade.
        from graphgraph.scanner.frontends import languages as frontends

        class RecoveringPack:
            calls = 0

            @classmethod
            def get_language(cls, _name):
                cls.calls += 1
                if cls.calls == 1:
                    raise PermissionError("temporary read-only cache")
                return object()

        language_name = "retry_language"
        try:
            with (
                patch.object(frontends, "find_spec", return_value=object()),
                patch.object(frontends, "import_module", return_value=RecoveringPack),
            ):
                first = frontends._language_for_name(language_name)
                second = frontends._language_for_name(language_name)

            self.assertIsNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(RecoveringPack.calls, 2)
        finally:
            frontends._LANGUAGE_CACHE.pop(language_name, None)
            frontends._LANGUAGE_LOAD_ERRORS.pop(language_name, None)

    def test_regex_extractor_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("def helper(): pass\n", encoding="utf-8")
            result = RegexExtractor().extract_symbols(
                [SourceFile(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))],
                max_total_symbols=10,
            )
            self.assertEqual(result.frontend, "regex")
            self.assertTrue(any(node.label == "helper" for node in result.nodes.values()))

    def test_select_extractor_regex_forced(self) -> None:
        self.assertIsInstance(select_extractor("regex"), RegexExtractor)

    def test_select_extractor_tree_sitter_requires_dependency(self) -> None:
        if not tree_sitter_available():
            with self.assertRaises(RuntimeError):
                select_extractor("tree_sitter")

    def test_auto_tree_sitter_falls_back_per_file_and_records_reason(self) -> None:
        class TimedOutParser:
            timeout_micros = 0

            def parse(self, _text):
                return None

            def reset(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "slow.rs"
            text = "pub struct Recovered;\n"
            source_path.write_text(text, encoding="utf-8")
            source = SourceFile(source_path, "slow.rs", "slow_rs", text)
            extractor = TreeSitterExtractor(fallback_on_error=True, parse_timeout_micros=1234)

            with patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=TimedOutParser()):
                result = extractor.extract_symbols([source], max_total_symbols=20)

            self.assertEqual(result.frontend, "tree_sitter+regex")
            self.assertEqual(result.fallback_files, ("slow.rs",))
            self.assertEqual(result.failed_files, ("slow.rs:TimeoutError",))
            self.assertEqual(result.timeout_files, ("slow.rs",))
            self.assertEqual(result.unsupported_files, ())
            self.assertEqual(result.parse_error_files, ())
            self.assertTrue(any(node.label == "Recovered" for node in result.nodes.values()))

    def test_explicit_tree_sitter_surfaces_file_failure(self) -> None:
        class BrokenParser:
            timeout_micros = 0

            def parse(self, _text):
                raise ValueError("bad parser state")

            def reset(self):
                return None

        source = SourceFile(Path("broken.rs"), "broken.rs", "broken_rs", "pub struct Broken;\n")
        with patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=BrokenParser()):
            with self.assertRaisesRegex(RuntimeError, "broken.rs"):
                TreeSitterExtractor().extract_symbols([source], max_total_symbols=20)

    def test_explicit_tree_sitter_fails_when_supported_grammar_is_unavailable(self) -> None:
        source = SourceFile(Path("sample.ts"), "sample.ts", "sample_ts", "export function run() {}\n")
        with (
            patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=None),
            patch(
                "graphgraph.scanner.frontends.extractors.parser_unavailable_reason",
                return_value="OSError: grammar cache is read-only",
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"sample\.ts.*typescript.*grammar cache is read-only",
            ):
                TreeSitterExtractor().extract_symbols([source], max_total_symbols=20)

    def test_auto_tree_sitter_records_grammar_failure_before_regex_fallback(self) -> None:
        source = SourceFile(Path("sample.go"), "sample.go", "sample_go", "func Run() {}\n")
        with (
            patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=None),
            patch(
                "graphgraph.scanner.frontends.extractors.parser_unavailable_reason",
                return_value="PermissionError: grammar cache is read-only",
            ),
        ):
            result = TreeSitterExtractor(fallback_on_error=True).extract_symbols(
                [source],
                max_total_symbols=20,
            )

        self.assertEqual(result.frontend, "tree_sitter+regex")
        self.assertEqual(result.unsupported_files, ("sample.go",))
        self.assertEqual(
            result.grammar_errors,
            ("sample.go:PermissionError: grammar cache is read-only",),
        )
        self.assertTrue(any(node.label == "Run" for node in result.nodes.values()))

    def test_tree_sitter_reports_unsupported_fallback_separately_from_parse_failures(self) -> None:
        source = SourceFile(Path("notes.md"), "notes.md", "notes_md", "# Notes\n")
        result = TreeSitterExtractor(fallback_on_error=True).extract_symbols(
            [source],
            max_total_symbols=20,
        )

        self.assertEqual(result.fallback_files, ("notes.md",))
        self.assertEqual(result.unsupported_files, ("notes.md",))
        self.assertEqual(result.timeout_files, ())
        self.assertEqual(result.parse_error_files, ())
        self.assertEqual(result.failed_files, ())

    def test_tree_sitter_extractor_captures_rust_trait_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = (
                "pub trait ExprVisitor {\n"
                "    fn visit_expr(&mut self, expr: &Expr);\n"
                "    fn visit_condition(&mut self, c: &Condition) -> bool;\n"
                "}\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "lib.rs", "lib_rs", text)],
                max_total_symbols=20,
            )
            labels = {node.label for node in result.nodes.values()}
            self.assertIn("ExprVisitor", labels)
            self.assertIn("visit_expr", labels)
            self.assertIn("visit_condition", labels)
            trait_id = next(nid for nid, node in result.nodes.items() if node.label == "ExprVisitor")
            method_ids = {nid for nid, node in result.nodes.items() if node.label in {"visit_expr", "visit_condition"}}
            nested = {(edge.source, edge.target, edge.type) for edge in result.edges}
            self.assertTrue(all((trait_id, method_id, "contains") in nested for method_id in method_ids))

    def test_regex_extractor_links_locus_style_cross_crate_rust_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trait_path = root / "locus-core" / "src" / "pipeline.rs"
            impl_path = root / "locus-pipeline" / "src" / "lib.rs"
            trait_path.parent.mkdir(parents=True)
            impl_path.parent.mkdir(parents=True)
            trait_text = "pub trait DiscoveryPipeline { fn search_candidates(&self); }\n"
            impl_text = (
                "pub struct LocusEngine;\nimpl DiscoveryPipeline for LocusEngine { fn search_candidates(&self) {} }\n"
            )
            trait_path.write_text(trait_text, encoding="utf-8")
            impl_path.write_text(impl_text, encoding="utf-8")
            files = [
                SourceFile(trait_path, "locus-core/src/pipeline.rs", "trait_file", trait_text),
                SourceFile(impl_path, "locus-pipeline/src/lib.rs", "impl_file", impl_text),
            ]

            result = RegexExtractor().extract_symbols(files, max_total_symbols=100)
            nodes = result.nodes
            contracts = {
                (nodes[edge.source].label, nodes[edge.target].label)
                for edge in result.edges
                if edge.type == "implements" and edge.source in nodes and edge.target in nodes
            }
            self.assertIn(("LocusEngine", "DiscoveryPipeline"), contracts)

    def test_tree_sitter_extractor_captures_rust_fields_and_returns(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = (
                "pub struct Point { pub x: f64, y: f64 }\n"
                "pub struct EgraphStageTimingsMs { pub extraction: f64 }\n"
                "pub fn make() -> Point { Point { x: 0.0, y: 0.0 } }\n"
                "pub fn optimize_timed() -> (Point, f32, EgraphStageTimingsMs) { todo!() }\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "lib.rs", "lib_rs", text)],
                max_total_symbols=20,
            )
            labels = {node.label for node in result.nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("x", labels)
            self.assertIn("y", labels)
            point_id = next(nid for nid, node in result.nodes.items() if node.label == "Point")
            make_id = next(nid for nid, node in result.nodes.items() if node.label == "make")
            timed_id = next(nid for nid, node in result.nodes.items() if node.label == "optimize_timed")
            timings_id = next(nid for nid, node in result.nodes.items() if node.label == "EgraphStageTimingsMs")
            self.assertTrue(any(edge.type == "field_of" and edge.target == point_id for edge in result.edges))
            self.assertTrue(
                any(
                    edge.type == "returns" and edge.source == make_id and edge.target == point_id
                    for edge in result.edges
                )
            )
            self.assertTrue(
                any(
                    edge.type == "returns" and edge.source == timed_id and edge.target == timings_id
                    for edge in result.edges
                )
            )

    def test_tree_sitter_extractor_captures_csharp_class_and_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "RecipeResolver.cs"
            text = (
                "namespace Game.Resolvers {\n"
                "  public class RecipeResolver : IRecipeCanon {\n"
                "    public RecipeResolver() {}\n"
                "    public Recipe Resolve(string id) { return null; }\n"
                "  }\n"
                "  public struct RecipeRecord { public int Id; }\n"
                "  public enum RecipeKind { Weapon, Armor }\n"
                "  public interface IRecipeCanon { }\n"
                "}\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "RecipeResolver.cs", "RecipeResolver_cs", text)],
                max_total_symbols=50,
            )
            by_label = {node.label: node for node in result.nodes.values()}
            self.assertIn("RecipeResolver", by_label)
            self.assertTrue(
                any(node.label == "RecipeResolver" and node.kind == "class" for node in result.nodes.values())
            )
            self.assertEqual(by_label["Resolve"].kind, "method")
            self.assertEqual(by_label["RecipeRecord"].kind, "struct")
            self.assertEqual(by_label["RecipeKind"].kind, "enum")
            self.assertEqual(by_label["IRecipeCanon"].kind, "interface")
            # Method should be nested under the class via a contains edge.
            class_id = next(nid for nid, n in result.nodes.items() if n.label == "RecipeResolver" and n.kind == "class")
            resolve_id = next(nid for nid, n in result.nodes.items() if n.label == "Resolve")
            nested = {(edge.source, edge.target, edge.type) for edge in result.edges}
            self.assertIn((class_id, resolve_id, "contains"), nested)

    def test_tree_sitter_resolves_cross_file_calls_csharp_and_java(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "csharp": {
                "RecipeResolver.cs": "namespace G { public class RecipeResolver {\n  public int Resolve(string id) { return Compute(id); }\n} }\n",
                "CombatResolver.cs": "namespace G { public class CombatResolver {\n  public int Compute(string id) { return 7; }\n} }\n",
                "expect": ("Resolve", "Compute"),
            },
            "java": {
                "A.java": "class A { int run(){ return help(); } }\n",
                "B.java": "class B { int help(){ return 1; } }\n",
                "expect": ("run", "help"),
            },
        }
        for _lang, spec in cases.items():
            expect = spec.pop("expect")
            with tempfile.TemporaryDirectory() as tmp:
                srcs = []
                for name, text in spec.items():
                    f = Path(tmp) / name
                    f.write_text(text, encoding="utf-8")
                    srcs.append(SourceFile(f, name, name.replace(".", "_"), text))
                result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
                calls = {
                    (result.nodes[e.source].label, result.nodes[e.target].label)
                    for e in result.edges
                    if e.type == "calls"
                }
                self.assertIn(expect, calls, f"missing cross-file call edge {expect}; got {calls}")

    def test_tree_sitter_does_not_link_calls_across_languages(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via a real-world scan where a Rust function's call
        # to a std-library-style helper resolved to an unrelated C function of
        # the same name in vendored test fixtures purely because it was the
        # only "count" definition in the whole repo -- producing a nonsensical
        # Rust-calls-C edge (`_add_tree_sitter_calls` in frontends.py).
        rs_text = "pub fn examine() -> i32 { count() }\n"
        c_text = "int count(void) { return 1; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            rs = Path(tmp) / "shape.rs"
            rs.write_text(rs_text, encoding="utf-8")
            c = Path(tmp) / "vendor" / "common.h"
            c.parent.mkdir(parents=True, exist_ok=True)
            c.write_text(c_text, encoding="utf-8")
            srcs = [
                SourceFile(rs, "shape.rs", "shape_rs", rs_text),
                SourceFile(c, "vendor/common.h", "vendor_common_h", c_text),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(("examine", "count"), calls, f"found Rust->C cross-language call edge: {calls}")

    def test_tree_sitter_resolves_same_named_direct_calls_per_language(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "python/flow.py": (
                "def leaf(): return 1\n"
                "def middle(): return leaf()\n"
                "def root(): return middle()\n"
            ),
            "python/test_flow.py": (
                "from flow import root\n"
                "def test_root(): assert root() == 1\n"
            ),
            "javascript/flow.js": (
                "function leaf() { return 1; }\n"
                "function middle() { return leaf(); }\n"
                "function root() { return middle(); }\n"
            ),
            "javascript/flow.test.js": (
                "const { root } = require('./flow');\n"
                "function testRoot() { return root() === 1; }\n"
            ),
            "rust/flow.rs": (
                "fn leaf() -> i32 { 1 }\n"
                "fn middle() -> i32 { leaf() }\n"
                "fn root() -> i32 { middle() }\n"
                "#[cfg(test)] mod tests {\n"
                "  use super::*;\n"
                "  #[test] fn test_root() { assert_eq!(root(), 1); }\n"
                "}\n"
            ),
            "go/flow.go": (
                "package flow\n"
                "func Leaf() int { return 1 }\n"
                "func Middle() int { return Leaf() }\n"
                "func Root() int { return Middle() }\n"
            ),
            "go/flow_test.go": (
                "package flow\n"
                "import \"testing\"\n"
                "func TestRoot(t *testing.T) {\n"
                "  if Root() != 1 { t.Fatal(\"unexpected result\") }\n"
                "}\n"
            ),
            "csharp/Flow.cs": (
                "class Flow {\n"
                "  public static int Leaf() => 1;\n"
                "  public static int Middle() => Leaf();\n"
                "  public static int Root() => Middle();\n"
                "}\n"
                "class FlowTests {\n"
                "  public int TestRoot() => Flow.Root();\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            sources = []
            for rel, source_text in cases.items():
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source_text, encoding="utf-8")
                sources.append(
                    SourceFile(
                        path,
                        rel,
                        rel.replace("/", "_").replace(".", "_"),
                        source_text,
                    )
                )
            result = select_extractor("tree_sitter").extract_symbols(
                sources,
                max_total_symbols=100,
            )

        calls_by_language: dict[str, set[tuple[str, str]]] = {}
        for edge in result.edges:
            if edge.type != "calls":
                continue
            source = result.nodes.get(edge.source)
            target = result.nodes.get(edge.target)
            if source is None or target is None:
                continue
            language = source.path.split("/", 1)[0]
            if target.path.startswith(f"{language}/"):
                calls_by_language.setdefault(language, set()).add(
                    (
                        source.label.casefold().replace("_", ""),
                        target.label.casefold().replace("_", ""),
                    )
                )

        for language in ("python", "javascript", "rust", "go", "csharp"):
            self.assertIn(("middle", "leaf"), calls_by_language.get(language, set()))
            self.assertIn(("root", "middle"), calls_by_language.get(language, set()))
            self.assertIn(("testroot", "root"), calls_by_language.get(language, set()))

    def test_tree_sitter_resolves_calls_through_python_package_reexports(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/pkg/renderers.py": "def render_packet():\n    return 'ok'\n",
            "src/pkg/__init__.py": "from .renderers import render_packet\n",
            "src/consumer.py": "from pkg import render_packet\n\ndef run():\n    return render_packet()\n",
            "bench/fixture.py": "def render_packet():\n    return 'fixture'\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, source_text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source_text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), source_text))

            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)
            calls = [
                edge
                for edge in result.edges
                if edge.type == "calls"
                and result.nodes[edge.source].label == "run"
                and result.nodes[edge.target].label == "render_packet"
            ]
            self.assertEqual(len(calls), 1)
            self.assertEqual(result.nodes[calls[0].target].path, "src/pkg/renderers.py")

    def test_tree_sitter_resolves_python_self_method_calls_by_class_owner(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source_text = (
            "class Worker:\n"
            "    def run(self):\n"
            "        return self.process()\n\n"
            "    def process(self):\n"
            "        return 1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worker.py"
            path.write_text(source_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "worker.py", "worker_py", source_text)],
                max_total_symbols=100,
            )

        methods = {node.label: node for node in result.nodes.values() if node.kind == "method"}
        self.assertEqual(set(methods), {"run", "process"})
        self.assertEqual(result.nodes[methods["run"].parent].label, "Worker")
        calls = [
            edge
            for edge in result.edges
            if edge.type == "calls" and edge.source == methods["run"].id and edge.target == methods["process"].id
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].provenance, "tree_sitter_type_resolved")
        self.assertEqual(result.resolved_member_calls, 1)

    def test_tree_sitter_does_not_link_qualified_method_calls_to_free_functions(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via a real-world scan where `order.splice(...)`
        # (a receiver.method(...) call -- here Vec::splice, a stdlib method)
        # resolved to an unrelated private free function `fn splice(...)`
        # elsewhere in the same crate, purely because "splice" was the only
        # definition with that name in the repo. Resolving a qualified call
        # needs the receiver's type, which this heuristic extractor doesn't
        # have -- same bug class as the cross-language case above, but
        # same-language/same-crate, so the language-family guard alone
        # doesn't catch it (`_add_tree_sitter_calls` in frontends.py).
        rs_text_a = (
            "fn validate_schedule(order: &mut Vec<i32>) {\n"
            "    let pos = 0;\n"
            "    order.splice(pos..=pos, [1, 2, 3]);\n"
            "}\n"
        )
        rs_text_b = "fn splice(x: i32) -> i32 {\n    x + 1\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "schedule_legality.rs"
            a.write_text(rs_text_a, encoding="utf-8")
            b = Path(tmp) / "evolution.rs"
            b.write_text(rs_text_b, encoding="utf-8")
            srcs = [
                SourceFile(a, "schedule_legality.rs", "schedule_legality_rs", rs_text_a),
                SourceFile(b, "evolution.rs", "evolution_rs", rs_text_b),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(
                ("validate_schedule", "splice"),
                calls,
                f"found qualified-call-to-unrelated-free-function edge: {calls}",
            )

        # But a bare (unqualified) call to a globally-unique free function
        # must still resolve -- the fix must not break the common case.
        rs_text_c = "fn caller() -> i32 {\n    helper()\n}\n"
        rs_text_d = "fn helper() -> i32 {\n    1\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "c.rs"
            c.write_text(rs_text_c, encoding="utf-8")
            d = Path(tmp) / "d.rs"
            d.write_text(rs_text_d, encoding="utf-8")
            srcs = [
                SourceFile(c, "c.rs", "c_rs", rs_text_c),
                SourceFile(d, "d.rs", "d_rs", rs_text_d),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertIn(("caller", "helper"), calls, f"bare unqualified call should still resolve: {calls}")

    def test_tree_sitter_resolves_rust_receiver_method_from_parameter_type(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/lib.rs": (
                "pub struct LocusEngine;\n"
                "impl LocusEngine {\n"
                "    pub fn validate_candidates_detailed(&self, candidates: Vec<i32>) -> Vec<i32> { candidates }\n"
                "}\n"
            ),
            "src/yield_benchmark.rs": (
                "use crate::LocusEngine;\n"
                "pub fn run_formula_yield_benchmark(engine: &LocusEngine, candidates: Vec<i32>) {\n"
                "    let _outcomes = engine.validate_candidates_detailed(candidates);\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        matching = [
            edge
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "run_formula_yield_benchmark"
            and result.nodes[edge.target].label == "validate_candidates_detailed"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].provenance, "tree_sitter_type_resolved")
        self.assertEqual(result.resolved_member_calls, 1)
        method = result.nodes[matching[0].target]
        self.assertTrue(method.parent)
        self.assertEqual(result.nodes[method.parent].label, "LocusEngine")

    def test_tree_sitter_keeps_same_named_rust_methods_in_one_file_distinct(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct YieldBaseline;\n"
            "impl YieldBaseline {\n"
            "    pub fn evaluate(&self, report: &u32) -> bool { *report > 0 }\n"
            "}\n"
            "pub struct SourceYieldBaseline;\n"
            "impl SourceYieldBaseline {\n"
            "    pub fn evaluate(&self, report: &u64) -> bool { *report > 0 }\n"
            "}\n"
            "pub fn check(a: &YieldBaseline, b: &SourceYieldBaseline) {\n"
            "    let _ = a.evaluate(&1);\n"
            "    let _ = b.evaluate(&1);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yield_benchmark.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "src/yield_benchmark.rs", "src_yield_benchmark_rs", text)],
                max_total_symbols=100,
            )

        methods = [node for node in result.nodes.values() if node.kind == "method" and node.label == "evaluate"]
        self.assertEqual(len(methods), 2)
        self.assertEqual(len({node.id for node in methods}), 2)
        self.assertEqual({node.line for node in methods}, {3, 7})
        self.assertEqual(
            {result.nodes[node.parent].label for node in methods},
            {"YieldBaseline", "SourceYieldBaseline"},
        )
        self.assertTrue(any("SourceYieldBaseline::evaluate" in node.summary for node in methods))
        call_targets = {
            edge.target for edge in result.edges if edge.type == "calls" and result.nodes[edge.source].label == "check"
        }
        self.assertEqual(call_targets, {node.id for node in methods})

    def test_tree_sitter_resolves_qualified_rust_unit_struct_receivers(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/identity.rs": (
                "pub struct IdentityDiscoveryAdvisor;\n"
                "impl IdentityDiscoveryAdvisor { pub fn examine(&self, objects: &[i32]) {} }\n"
            ),
            "src/simpler.rs": (
                "pub struct SimplerFormAdvisor;\n"
                "impl SimplerFormAdvisor { pub fn examine(&self, objects: &[i32]) {} }\n"
            ),
            "src/runner.rs": (
                "pub fn run(objects: &[i32]) {\n"
                "    crate::advisors::IdentityDiscoveryAdvisor.examine(objects);\n"
                "    crate::advisors::SimplerFormAdvisor.examine(objects);\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        calls = [edge for edge in result.edges if edge.type == "calls" and result.nodes[edge.source].label == "run"]
        owners = {
            result.nodes[result.nodes[edge.target].parent].label for edge in calls if result.nodes[edge.target].parent
        }
        self.assertEqual(owners, {"IdentityDiscoveryAdvisor", "SimplerFormAdvisor"})
        self.assertTrue(all(edge.provenance == "tree_sitter_type_resolved" for edge in calls))
        self.assertEqual(result.resolved_member_calls, 2)

    def test_tree_sitter_keeps_untyped_rust_member_calls_out_of_topology(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/a.rs": "pub struct A; impl A { pub fn validate(&self) {} }\n",
            "src/b.rs": "pub struct B; impl B { pub fn validate(&self) {} }\n",
            "src/run.rs": "pub fn run(engine: impl Sized) { engine.validate(); }\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        candidates = [
            edge
            for edge in result.edges
            if edge.source in result.nodes
            and result.nodes[edge.source].label == "run"
            and edge.type == "calls_candidate"
        ]
        self.assertEqual(candidates, [])
        self.assertEqual(result.ambiguous_member_calls, 0)
        self.assertEqual(result.unknown_receiver_member_calls, 1)
        run_id = next(node.id for node in result.nodes.values() if node.label == "run")
        self.assertFalse(any(edge.type == "calls" and edge.source == run_id for edge in result.edges))

    def test_tree_sitter_resolves_python_member_calls_from_explicit_type_evidence(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Graph:\n"
            "    def outgoing(self):\n"
            "        return []\n"
            "\n"
            "class Runtime:\n"
            "    def __init__(self):\n"
            "        self.graph = Graph()\n"
            "\n"
            "    def compile(self):\n"
            "        return self.graph.outgoing()\n"
            "\n"
            'def from_annotation(graph: "Graph | None"):\n'
            "    return graph.outgoing()\n"
            "\n"
            "def from_constructor():\n"
            "    graph = Graph()\n"
            "    return graph.outgoing()\n"
            "\n"
            "def from_class_receiver():\n"
            "    return Graph.outgoing(Graph())\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "runtime.py", "runtime_py", text)],
                max_total_symbols=100,
            )

        outgoing = next(node for node in result.nodes.values() if node.label == "outgoing")
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == outgoing.id
        }
        self.assertEqual(callers, {"compile", "from_annotation", "from_constructor", "from_class_receiver"})
        self.assertEqual(result.resolved_member_calls, 4)
        self.assertTrue(
            all(
                edge.provenance == "tree_sitter_type_resolved"
                for edge in result.edges
                if edge.type == "calls" and edge.target == outgoing.id
            )
        )

    def test_tree_sitter_separates_builtin_unknown_and_factory_python_receivers(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Bucket:\n"
            "    def append(self, value):\n"
            "        pass\n"
            "\n"
            "def builtin_receiver():\n"
            "    values = []\n"
            "    values.append(1)\n"
            "\n"
            "def unknown_receiver(values):\n"
            "    values.append(1)\n"
            "\n"
            "def make_bucket():\n"
            "    return Bucket()\n"
            "\n"
            "def factory_receiver():\n"
            "    bucket = make_bucket()\n"
            "    bucket.append(1)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bucket.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "bucket.py", "bucket_py", text)],
                max_total_symbols=100,
            )

        self.assertFalse(any(edge.type == "calls_candidate" for edge in result.edges))
        labels = {node_id: node.label for node_id, node in result.nodes.items()}
        append_callers = {
            labels[edge.source]
            for edge in result.edges
            if edge.type == "calls" and labels.get(edge.target) == "append"
        }
        self.assertEqual(append_callers, {"factory_receiver"})
        self.assertEqual(result.resolved_member_calls, 1)
        self.assertEqual(result.unknown_receiver_member_calls, 1)
        self.assertEqual(result.unresolved_member_calls, 1)
        self.assertEqual(result.external_resolved_member_calls, 1)
        self.assertEqual(result.unmatched_member_calls, 0)

    def test_tree_sitter_resolves_rust_self_field_receiver_type(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct Store;\n"
            "impl Store { pub fn commit(&self) {} }\n"
            "pub struct Engine { store: Store }\n"
            "impl Engine { pub fn run(&self) { self.store.commit(); } }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "engine.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "engine.rs", "engine_rs", text)],
                max_total_symbols=100,
            )

        call = next(
            edge
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "run"
            and result.nodes[edge.target].label == "commit"
        )
        self.assertEqual(call.provenance, "tree_sitter_type_resolved")
        self.assertIn("self.store:Store", call.evidence)
        self.assertEqual(result.resolved_member_calls, 1)

    def test_tree_sitter_links_typed_rust_test_field_assertion_as_direct_evidence(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct YieldStageTimingsMs {\n"
            "    pub candidate_generation: f64,\n"
            "    pub extraction_only: Option<f64>,\n"
            "}\n"
            "pub struct YieldBenchmarkReport { pub timings_ms: YieldStageTimingsMs }\n"
            "pub fn run_formula_yield_benchmark() -> YieldBenchmarkReport { todo!() }\n"
            "#[test]\n"
            "fn validates_report() {\n"
            "    let report = run_formula_yield_benchmark();\n"
            "    assert!(report.timings_ms.candidate_generation > 0.0);\n"
            "    assert!(report.timings_ms.extraction_only.is_some());\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tests" / "schema.rs"
            path.parent.mkdir()
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "tests/schema.rs", "tests_schema_rs", text)],
                max_total_symbols=100,
            )

        references = [
            edge
            for edge in result.edges
            if edge.type == "references" and result.nodes[edge.source].label == "validates_report"
        ]
        test_node = next(node for node in result.nodes.values() if node.label == "validates_report")
        self.assertEqual(test_node.facts, ("role:test", "rust_attribute:test"))
        self.assertEqual(
            {result.nodes[edge.target].label for edge in references},
            {"timings_ms", "candidate_generation", "extraction_only"},
        )
        self.assertTrue(all(edge.provenance == "tree_sitter_type_resolved_field_assertion" for edge in references))
        self.assertTrue(all(edge.confidence == 0.94 for edge in references))

    def test_tree_sitter_projects_rust_operators_into_semantic_ir_facts(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "use std::collections::BTreeSet;\n"
            "pub fn plan_writes(paths: &[String]) -> Vec<String> {\n"
            "    let mut seen = BTreeSet::new();\n"
            "    paths.iter().filter(|path| seen.insert((*path).clone())).cloned().collect()\n"
            "}\n"
            "pub fn pinned_count(actual: usize, expected: usize) -> bool {\n"
            "    actual != expected\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "planner.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "src/planner.rs", "src_planner_rs", text)],
                max_total_symbols=100,
            )

        plan = next(node for node in result.nodes.values() if node.label == "plan_writes")
        pinned = next(node for node in result.nodes.values() if node.label == "pinned_count")
        self.assertIn("collection_contract:unique", plan.facts)
        self.assertIn("semantic_operation:deduplication", plan.facts)
        self.assertIn("semantic_operator:equality", pinned.facts)

    def test_tree_sitter_links_function_passed_as_callback_argument(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via real usage on a large C codebase. A function
        # invoked exclusively via function-pointer/callback registration
        # (SetMainCallback2(CB2_InitBattle), never called directly as
        # CB2_InitBattle(...)) had zero caller edges -- static call-graph
        # detection only recognizes name(...) call sites, so a name that's
        # merely *passed* as a bare argument was invisible, making an
        # actively-used function read as isolated/dead. Verified via a
        # direct tree-sitter parse (not assumed) that C's call_expression
        # exposes its argument list via child_by_field_name("arguments").
        c_text = "void CB2_InitBattle(void) {}\nvoid MainLoop(void) {\n    SetMainCallback2(CB2_InitBattle);\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "battle_main.c"
            f.write_text(c_text, encoding="utf-8")
            src = SourceFile(f, "battle_main.c", "battle_main_c", c_text)
            result = select_extractor("tree_sitter").extract_symbols([src], max_total_symbols=100)
            refs = {
                (result.nodes[e.source].label, result.nodes[e.target].label)
                for e in result.edges
                if e.type == "references"
            }
            self.assertIn(
                ("MainLoop", "CB2_InitBattle"),
                refs,
                f"callback-registration argument should produce a references edge: {refs}",
            )
            # Must not be misclassified as an actual "calls" edge -- passing
            # a name as an argument doesn't prove it's ever invoked.
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(("MainLoop", "CB2_InitBattle"), calls)

    def test_tree_sitter_extracts_c_pointer_return_function_definition(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        c_text = (
            "struct redisCommand *lookupCommand(void **argv, int argc) { return 0; }\n"
            "int processCommand(void *client) { return lookupCommand(0, 0) != 0; }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "server.c"
            path.write_text(c_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "server.c", "server_c", c_text)],
                max_total_symbols=100,
            )

        labels = {node.label for node in result.nodes.values() if node.kind == "function"}
        self.assertIn("lookupCommand", labels)
        self.assertIn("processCommand", labels)

    def test_tree_sitter_links_python_keyword_argument_callback(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Same bug class as the C callback-registration case above, but for
        # Python's extremely common `func=callback` idiom (argparse's
        # `set_defaults(func=cmd_scan)`, Click, dataclasses, ...). Verified
        # directly that tree-sitter wraps this in a keyword_argument node
        # (name="func", value="cmd_scan"), not a bare identifier -- a naive
        # `arg.type in _NAME_NODE_TYPES` check misses it entirely unless the
        # keyword_argument's `value` field is explicitly unwrapped.
        py_text = (
            "def cmd_scan(args):\n"
            "    pass\n"
            "\n"
            "def build_parser():\n"
            "    scan = sub.add_parser('scan')\n"
            "    scan.set_defaults(func=cmd_scan)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "parser.py"
            f.write_text(py_text, encoding="utf-8")
            src = SourceFile(f, "parser.py", "parser_py", py_text)
            result = select_extractor("tree_sitter").extract_symbols([src], max_total_symbols=100)
            refs = {
                (result.nodes[e.source].label, result.nodes[e.target].label)
                for e in result.edges
                if e.type == "references"
            }
            self.assertIn(
                ("build_parser", "cmd_scan"),
                refs,
                f"func=callback keyword argument should produce a references edge: {refs}",
            )

    def test_tree_sitter_resolves_path_qualified_associated_function_calls(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via real-world usage -- a struct's own
        # associated function, called as `QuadPoly::from_uni(...)`, never
        # showed a `calls` edge pointing at it, making an actively-used
        # struct falsely read as isolated/dead by negative_query/
        # reverse_lookup. Unlike `receiver.method(...)` (needs the
        # receiver's type), `Type::function(...)` names its target
        # explicitly and lexically -- it should resolve like a bare call,
        # not be treated as unresolvable-qualified.
        rs_text = (
            "struct QuadPoly { a: i32 }\n"
            "impl QuadPoly {\n"
            "    fn from_uni(x: i32) -> QuadPoly { QuadPoly { a: x } }\n"
            "}\n"
            "fn integrate_rational_rothstein_trager() {\n"
            "    let q = QuadPoly::from_uni(5);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "integrate.rs"
            f.write_text(rs_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "integrate.rs", "integrate_rs", rs_text)],
                max_total_symbols=100,
            )
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertIn(
                ("integrate_rational_rothstein_trager", "from_uni"),
                calls,
                f"Type::function(...) associated call should resolve: {calls}",
            )

    def test_tree_sitter_recovers_rust_calls_nested_in_macro_token_trees(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        rust = (
            "fn finite_vc_dimension() -> Result<(), ()> { Ok(()) }\n"
            "fn shatters() -> Result<bool, ()> { Ok(true) }\n"
            "#[cfg(test)] mod tests {\n"
            "    use super::*;\n"
            "    #[test]\n"
            "    fn malformed_contract() {\n"
            "        assert!(matches!(finite_vc_dimension(), Ok(())));\n"
            "    }\n"
            "    #[test]\n"
            "    fn subset_contract() {\n"
            "        assert!(shatters().unwrap());\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learning_theory.rs"
            path.write_text(rust, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "src/learning_theory.rs", "learning_theory_rs", rust)],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                edge.provenance,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(
            (
                "malformed_contract",
                "finite_vc_dimension",
                "tree_sitter_macro_token_tree",
            ),
            calls,
        )
        self.assertIn(
            ("subset_contract", "shatters", "tree_sitter_macro_token_tree"),
            calls,
        )
        self.assertFalse(any(target == "unwrap" for _source, target, _provenance in calls))

    def test_tree_sitter_extractor_captures_additional_languages(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "svc.rb": ("class RecipeResolver\n  def resolve(id)\n    1\n  end\nend\n", "RecipeResolver", "resolve"),
            "svc.php": (
                "<?php\nclass RecipeResolver { public function resolve($id){return 1;} }\n",
                "RecipeResolver",
                "resolve",
            ),
            "Svc.kt": (
                "class RecipeResolver { fun resolve(id: String): Int { return 1 } }\n",
                "RecipeResolver",
                "resolve",
            ),
            "Svc.scala": ("class RecipeResolver { def resolve(id: String): Int = 1 }\n", "RecipeResolver", "resolve"),
            "Svc.swift": (
                "class RecipeResolver { func resolve(_ id: String) -> Int { return 1 } }\n",
                "RecipeResolver",
                "resolve",
            ),
        }
        tested = 0
        for fname, (text, type_name, member) in cases.items():
            if parser_for_suffix(Path(fname).suffix) is None:
                continue
            tested += 1
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / fname
                f.write_text(text, encoding="utf-8")
                result = select_extractor("tree_sitter").extract_symbols(
                    [SourceFile(f, fname, fname.replace(".", "_"), text)],
                    max_total_symbols=50,
                )
                labels = {node.label for node in result.nodes.values()}
                self.assertIn(type_name, labels, f"{fname}: missing type node")
                self.assertIn(member, labels, f"{fname}: missing member node")
        if tested == 0:
            self.skipTest("no additional-language Tree-sitter grammar is installed")

    def test_tree_sitter_swift_extracts_every_call_in_compound_expression(self) -> None:
        if parser_for_suffix(".swift") is None:
            self.skipTest("Swift Tree-sitter grammar is not installed")
        # Swift's grammar represents `Middle() + Assist()` as an outer call
        # whose callee expression contains the already-complete `Middle()` and
        # whose trailing call suffix belongs to `Assist`. Treating the whole
        # additive expression as a member-style callee kept only the first
        # call and silently dropped the cross-file second call.
        core_text = (
            "func Middle() -> Int { return 1 }\n"
            "func Root() -> Int { return Middle() + Assist() }\n"
        )
        helper_text = (
            "func Assist() -> Int { return 2 }\n"
            "func Middle() -> Int { return 3 }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = root / "Core.swift"
            helper = root / "Helper.swift"
            core.write_text(core_text, encoding="utf-8")
            helper.write_text(helper_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [
                    SourceFile(core, "Core.swift", "Core_swift", core_text),
                    SourceFile(helper, "Helper.swift", "Helper_swift", helper_text),
                ],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                result.nodes[edge.target].path,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("Root", "Middle", "Core.swift"), calls)
        self.assertIn(("Root", "Assist", "Helper.swift"), calls)
        self.assertNotIn(("Root", "Middle", "Helper.swift"), calls)

    def test_tree_sitter_php_extracts_same_and_cross_file_calls(self) -> None:
        if parser_for_suffix(".php") is None:
            self.skipTest("PHP Tree-sitter grammar is not installed")
        # PHP's grammar calls a bare callee node `name`. Definitions were
        # already extracted, but the shared call normalizer did not recognize
        # that node kind, so every PHP call site disappeared before resolution.
        core_text = (
            "<?php\n"
            "function Middle() { return 1; }\n"
            "function Root() { return Middle() + Assist(); }\n"
        )
        helper_text = (
            "<?php\n"
            "function Assist() { return 2; }\n"
            "function Middle() { return 3; }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = root / "core.php"
            helper = root / "helper.php"
            core.write_text(core_text, encoding="utf-8")
            helper.write_text(helper_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [
                    SourceFile(core, "core.php", "core_php", core_text),
                    SourceFile(helper, "helper.php", "helper_php", helper_text),
                ],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                result.nodes[edge.target].path,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("Root", "Middle", "core.php"), calls)
        self.assertIn(("Root", "Assist", "helper.php"), calls)
        self.assertNotIn(("Root", "Middle", "helper.php"), calls)

    def test_tree_sitter_ruby_binds_top_level_def_as_a_free_callable(self) -> None:
        if parser_for_suffix(".rb") is None:
            self.skipTest("Ruby Tree-sitter grammar is not installed")
        # A Ruby top-level `def` parses as a `method`, not a `function`, and the
        # file-local binding layer admitted only functions. An ownerless method
        # is a free function under another name, so the same-file `Middle` was
        # left to repository-wide resolution, where the decoy of the same name
        # in helper.rb made it ambiguous and dropped it entirely. The decoy is
        # what makes this test load-bearing: without it, `Middle` is globally
        # unique and resolves without ever consulting the file-local scope.
        core_text = "def Middle\n  1\nend\n\ndef Root\n  Middle() + Assist()\nend\n"
        helper_text = "def Assist\n  2\nend\n\ndef Middle\n  3\nend\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = root / "core.rb"
            helper = root / "helper.rb"
            core.write_text(core_text, encoding="utf-8")
            helper.write_text(helper_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [
                    SourceFile(core, "core.rb", "core_rb", core_text),
                    SourceFile(helper, "helper.rb", "helper_rb", helper_text),
                ],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                result.nodes[edge.target].path,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("Root", "Middle", "core.rb"), calls)
        self.assertIn(("Root", "Assist", "helper.rb"), calls)
        self.assertNotIn(("Root", "Middle", "helper.rb"), calls)

    def test_tree_sitter_scala_resolves_unqualified_call_to_object_sibling(self) -> None:
        if parser_for_suffix(".scala") is None:
            self.skipTest("Scala Tree-sitter grammar is not installed")
        # `object Core { def Middle() }` gives the method an owner, so the file
        # scope does not bind it; the enclosing type does. Scala joins C#, Java,
        # C++ and Ruby as a language where an unqualified call reaches a sibling
        # member. As with the Ruby case above, the same-named decoy in
        # Helper.scala is essential: it denies the repository-wide fallback, so
        # only the enclosing-object scope can resolve the call.
        core_text = "object Core {\n  def Middle(): Int = 1\n  def Root(): Int = Middle() + Assist()\n}\n"
        helper_text = "object Helper {\n  def Assist(): Int = 2\n  def Middle(): Int = 3\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = root / "Core.scala"
            helper = root / "Helper.scala"
            core.write_text(core_text, encoding="utf-8")
            helper.write_text(helper_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [
                    SourceFile(core, "Core.scala", "Core_scala", core_text),
                    SourceFile(helper, "Helper.scala", "Helper_scala", helper_text),
                ],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                result.nodes[edge.target].path,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("Root", "Middle", "Core.scala"), calls)
        self.assertIn(("Root", "Assist", "Helper.scala"), calls)
        self.assertNotIn(("Root", "Middle", "Helper.scala"), calls)

    def test_tree_sitter_javascript_binds_a_module_object_receiver(self) -> None:
        if parser_for_suffix(".js") is None:
            self.skipTest("JavaScript Tree-sitter grammar is not installed")
        # `var app = {}; app.set = function(){}` is the object-literal idiom JS
        # uses instead of classes. `this.set()` inside those already resolved,
        # but a same-file call written through the object's own name did not:
        # nothing bound `app` to its own (file-qualified) owner type.
        #
        # The shadowing case is the precision half: `function mount(app)` takes
        # a *different* object, so binding the module-level one there would
        # fabricate an edge.
        core_text = (
            "var app = {};\n"
            "app.set = function set(k) { return k; };\n"
            "app.boot = function boot() { return app.set('x'); };\n"
            "app.mount = function mount(app) { return app.set('y'); };\n"
        )
        other_text = "var app = {};\napp.set = function set(k) { return 2; };\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = root / "core.js"
            other = root / "other.js"
            core.write_text(core_text, encoding="utf-8")
            other.write_text(other_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [
                    SourceFile(core, "core.js", "core_js", core_text),
                    SourceFile(other, "other.js", "other_js", other_text),
                ],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                result.nodes[edge.target].path,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("boot", "set", "core.js"), calls)
        # The shadowing parameter must not bind to the module object...
        self.assertNotIn(("mount", "set", "core.js"), calls)
        # ...and a same-named object in another file is a different object.
        self.assertNotIn(("boot", "set", "other.js"), calls)

    def test_tree_sitter_javascript_binds_a_namespace_qualified_constructor(self) -> None:
        if parser_for_suffix(".js") is None:
            self.skipTest("JavaScript Tree-sitter grammar is not installed")
        # `var m = require('./dep'); new m.Engine()` is how CommonJS names an
        # imported class, and it states the receiver's type as explicitly as
        # `new Engine()` does. The pattern required the whole path to start
        # uppercase, so the namespaced form bound nothing.
        #
        # `new makeThing()` is the precision half: a lowercase callee is a
        # factory, not a type, so it must still bind nothing.
        main_text = (
            "var m = require('./dep');\n"
            "function run() { var e = new m.Engine(); return e.start(); }\n"
            "function nope() { var f = new makeThing(); return f.start(); }\n"
        )
        dep_text = (
            "class Engine { start() { return 1; } }\n"
            "function makeThing() { return 1; }\n"
            "module.exports = { Engine: Engine, makeThing: makeThing };\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main.js"
            dep = root / "dep.js"
            main.write_text(main_text, encoding="utf-8")
            dep.write_text(dep_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [
                    SourceFile(main, "main.js", "main_js", main_text),
                    SourceFile(dep, "dep.js", "dep_js", dep_text),
                ],
                max_total_symbols=100,
            )

        calls = {
            (result.nodes[edge.source].label, result.nodes[edge.target].label)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("run", "start"), calls)
        self.assertNotIn(("nope", "start"), calls)

    def test_member_call_resolution_rate_counts_unmatched_as_a_miss(self) -> None:
        if parser_for_suffix(".js") is None:
            self.skipTest("JavaScript Tree-sitter grammar is not installed")
        # The rate is meant to be a CI gate, so it has to be hard to move
        # without resolving anything. `f.beta()` has a known receiver type
        # (`Foo`) and `beta` does exist internally -- on `Bar` -- so the call is
        # a real miss recorded as `unmatched`, not as `unknown_receiver`.
        #
        # Defining the rate as resolved/(resolved+unknown_receiver) would read
        # 0/0 here and score a scan that resolved nothing as unpenalised. Worse,
        # merely typing a receiver moves calls from `unknown_receiver` into
        # `unmatched`, so that definition rewards changes which produce no edge.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.js").write_text(
                "class Foo { alpha() { return 1; } }\n"
                "class Bar { beta() { return 2; } }\n"
                "function run() { var f = new Foo(); return f.beta(); }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, max_nodes=1000, depth="symbols")

        meta = graph.metadata or {}
        self.assertEqual(meta["member_calls_resolved"], "0")
        self.assertEqual(meta["member_calls_unknown_receiver"], "0")
        self.assertEqual(meta["member_calls_unmatched"], "1")
        # The miss is in the denominator, so the rate reports the failure.
        self.assertEqual(meta["member_calls_internal_total"], "1")
        self.assertEqual(meta["member_call_resolution_rate"], "0.0000")

    def test_member_call_resolution_rate_excludes_external_callees(self) -> None:
        if parser_for_suffix(".js") is None:
            self.skipTest("JavaScript Tree-sitter grammar is not installed")
        # The mirror property: a call whose method name no internal symbol owns
        # is correctly declined, not a miss. Counting it would drag the gate
        # down for behaving correctly, and would make the number track how much
        # third-party API a repository touches rather than how well it resolves.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.js").write_text(
                "class Foo { alpha() { return 1; } beta() { return this.alpha(); } }\n"
                "function run() { var f = new Foo(); return f.nowhereDefined(); }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, max_nodes=1000, depth="symbols")

        meta = graph.metadata or {}
        # One internal call that resolved, one callee that lives outside the graph.
        self.assertEqual(meta["member_calls_resolved"], "1")
        self.assertEqual(meta["member_calls_external_resolved"], "1")
        # The external callee is not in the denominator, so a correctly declined
        # link cannot drag the gate below a perfect score.
        self.assertEqual(meta["member_calls_internal_total"], "1")
        self.assertEqual(meta["member_call_resolution_rate"], "1.0000")
        self.assertEqual(
            int(meta["member_calls_internal_total"]),
            sum(
                int(meta[key])
                for key in (
                    "member_calls_resolved",
                    "member_calls_ambiguous",
                    "member_calls_unknown_receiver",
                    "member_calls_unmatched",
                )
            ),
        )

    def test_regex_extractor_reports_symbol_truncation(self) -> None:
        # Same silent-truncation bug class, at the symbol-extraction layer:
        # TreeSitterExtractor/RegexExtractor both used to `break` out the
        # instant max_total_symbols was hit with no signal to the caller,
        # so every file processed afterward got zero symbols.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for i in range(3):
                path = root / f"mod_{i}.py"
                path.write_text("\n".join(f"def fn_{i}_{j}(): pass" for j in range(10)) + "\n", encoding="utf-8")
                files.append(SourceFile(path, f"mod_{i}.py", f"mod_{i}_py", path.read_text(encoding="utf-8")))

            result = RegexExtractor().extract_symbols(files, max_total_symbols=5)
            self.assertTrue(result.truncated)
            self.assertLessEqual(len(result.nodes), 5)

            result_full = RegexExtractor().extract_symbols(files, max_total_symbols=1000)
            self.assertFalse(result_full.truncated)
            self.assertEqual(len(result_full.nodes), 30)

    def test_scan_directory_surfaces_symbol_truncation_in_metadata(self) -> None:
        # Integration-level confirmation through the real scan_directory
        # path. The derived symbol cap has a max(500, ...) floor, so this
        # needs enough real defs to exceed 500 even at a small max_nodes.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(20):
                (root / f"mod_{i}.py").write_text(
                    "\n".join(f"def fn_{i}_{j}(): pass" for j in range(30)) + "\n", encoding="utf-8"
                )
            graph = scan_directory(root, max_nodes=20, depth="symbols", frontend="regex")
            self.assertEqual(graph.metadata.get("symbols_truncated"), "true")
            self.assertIn("symbols_cap", graph.metadata)

    def test_scanner_rust_mod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rs").write_text("mod utils;\nfn main(){}\n", encoding="utf-8")
            (root / "utils.rs").write_text("pub fn helper(){}\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)

    def test_scanner_depth_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "class Server:\n    def handle(self):\n        pass\n\ndef run():\n    pass\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            self.assertEqual(graph.metadata["scan_depth"], "symbols")
            self.assertIn(graph.metadata["frontend"], {"regex", "tree_sitter"})
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)
            contains_edges = [e for e in graph.edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains_edges), 2)

    def test_scanner_depth_symbols_kotlin_scala_swift_via_scan_directory(self) -> None:
        # Regression: .kt/.scala/.swift are advertised in the README as
        # supported symbol-scan languages, and TreeSitterExtractor fully
        # supports them (test_tree_sitter_extractor_captures_additional_languages
        # proves the extractor itself works). These extensions were once absent
        # from the scanner's source-file gate, so they were silently skipped
        # before select_extractor() could see them -- a gap invisible to
        # extractor-level unit tests.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Realistic multi-line formatting (the regex fallback is
            # line-anchored, unlike TreeSitterExtractor's AST-based parsing;
            # this matches how real Kotlin/Scala/Swift source is formatted).
            (root / "Svc.kt").write_text(
                "class RecipeResolver {\n    fun resolve(id: String): Int {\n        return 1\n    }\n}\n",
                encoding="utf-8",
            )
            (root / "Svc.scala").write_text(
                "class RecipeResolver {\n  def resolve(id: String): Int = 1\n}\n",
                encoding="utf-8",
            )
            (root / "Svc.swift").write_text(
                "class RecipeResolver {\n    func resolve(_ id: String) -> Int {\n        return 1\n    }\n}\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            labels = {n.label for n in graph.nodes.values()}
            self.assertIn("RecipeResolver", labels, "Kotlin/Scala/Swift class should be extracted, not just file-level")
            self.assertIn("resolve", labels)

    def test_scanner_depth_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib.rs").write_text(
                "pub struct Config { pub name: String }\npub fn load() -> Config { todo!() }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("struct", kinds)
            self.assertIn("function", kinds)

    def test_scanner_depth_symbols_cross_file_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_text(
                "def handle_request(config):\n    return config\n",
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                "from server import handle_request\nhandle_request(None)\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            ref_edges = [e for e in graph.edges if e.type == "references"]
            self.assertGreaterEqual(len(ref_edges), 1)

    def test_scanner_depth_symbols_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.js").write_text(
                "class Router {}\nexport function createApp() { return new Router(); }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)

    def test_extract_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("class Foo:\n    def bar(self): baz()\n\ndef baz(): pass\n", encoding="utf-8")
            tuples = [(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))]
            nodes, edges, _truncated = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Foo", labels)
            self.assertIn("baz", labels)
            contains = [e for e in edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains), 2)
            calls = [e for e in edges if e.type == "calls"]
            self.assertGreaterEqual(len(calls), 1)

    def test_extract_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            f.write_text(
                "pub trait Metric {}\n"
                "pub struct Point { x: i32 }\n"
                "impl Metric for Point {}\n"
                "pub fn norm() -> f64 { 0.0 }\n"
                "pub fn distance(a: Point) -> f64 { norm() }\n",
                encoding="utf-8",
            )
            tuples = [(f, "lib.rs", "lib_rs", f.read_text(encoding="utf-8"))]
            nodes, edges, _truncated = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("distance", labels)
            self.assertTrue(any(e.type == "calls" for e in edges))
            self.assertTrue(any(e.type == "implements" for e in edges))

    def test_regex_extractor_handles_ruby_and_php_without_tree_sitter(self) -> None:
        # Regression: .rb/.php are declared in PARSEABLE_SUFFIXES/SOURCE_SUFFIXES
        # (files.py) as supported source languages, but the regex-fallback
        # _EXTRACTORS dict (used whenever tree-sitter isn't installed) had no
        # entries for them, so Ruby/PHP files silently degraded to file-level
        # nodes with zero symbol-level extraction -- a coverage gap for a
        # declared-supported language, not just a missing nice-to-have.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rb = root / "service.rb"
            rb.write_text(
                "module Billing\n"
                "  class Invoice\n"
                "    def total\n"
                "      compute_total\n"
                "    end\n"
                "\n"
                "    def self.build\n"
                "      new\n"
                "    end\n"
                "  end\n"
                "end\n",
                encoding="utf-8",
            )
            php = root / "controller.php"
            php.write_text(
                "<?php\n"
                "class InvoiceController {\n"
                "    public function show($id) {\n"
                "        return find_invoice($id);\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )
            files = [
                SourceFile(rb, "service.rb", "service_rb", rb.read_text(encoding="utf-8")),
                SourceFile(php, "controller.php", "controller_php", php.read_text(encoding="utf-8")),
            ]
            result = RegexExtractor().extract_symbols(files, max_total_symbols=100)
            labels_by_kind = {n.label: n.kind for n in result.nodes.values()}
            self.assertEqual(labels_by_kind.get("Invoice"), "class")
            self.assertEqual(labels_by_kind.get("Billing"), "module")
            self.assertEqual(labels_by_kind.get("total"), "function")
            self.assertEqual(labels_by_kind.get("InvoiceController"), "class")
            self.assertEqual(labels_by_kind.get("show"), "function")

    def test_extract_symbols_does_not_link_calls_across_languages(self) -> None:
        # Regression: a Rust call site invoking a std-library-style method
        # (e.g. `.as_deref()`) must not resolve to an unrelated Python function
        # of the same name elsewhere in the repo -- found via a real cross-repo
        # scan where `crates/.../algorithm_shape.rs::examine` calls into
        # `Option::as_deref()` and a vendored numpy test fixture happened to
        # define an unrelated `def as_deref(expr):` at module scope, producing
        # a nonsensical Rust-calls-Python edge purely from name collision.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rs = root / "shape.rs"
            rs.write_text(
                "pub fn examine(x: Option<String>) -> Option<&str> { x.as_deref() }\n",
                encoding="utf-8",
            )
            py = root / "vendor" / "symbolic.py"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("def as_deref(expr):\n    return expr\n", encoding="utf-8")
            tuples = [
                (rs, "shape.rs", "shape_rs", rs.read_text(encoding="utf-8")),
                (py, "vendor/symbolic.py", "vendor_symbolic_py", py.read_text(encoding="utf-8")),
            ]
            nodes, edges, _truncated = extract_symbols(tuples)
            self.assertIn("examine", {n.label for n in nodes.values()})
            self.assertIn("as_deref", {n.label for n in nodes.values()})
            cross_lang = [
                e for e in edges if e.type in ("calls", "references") and e.target == "vendor_symbolic_py__as_deref"
            ]
            self.assertEqual([], cross_lang, f"found Rust<->Python cross-language edges: {cross_lang}")

    def test_regex_extractor_does_not_resolve_arrow_qualified_calls_as_bare(self) -> None:
        # Regression: the RegexExtractor's callsite pattern only excluded a
        # preceding "." (receiver.method()) from bare-call resolution, not a
        # preceding "->" (receiver->method()). C/C++ pointer-member calls like
        # `ops->process(5)` are just as receiver-type-dependent as `.`-calls,
        # but fell through the "." -only negative lookbehind and got treated
        # like a bare call to any unrelated free function named "process"
        # elsewhere in the repo -- the same false-positive-resolution bug
        # class as the receiver.method() fix, just for the arrow operator.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foo_c = root / "foo.c"
            foo_c.write_text(
                "struct Ops { int (*process)(int); };\nint foo(struct Ops *ops) {\n    return ops->process(5);\n}\n",
                encoding="utf-8",
            )
            reader_c = root / "reader.c"
            reader_c.write_text("int process(int fd) {\n    return fd + 1;\n}\n", encoding="utf-8")
            files = [
                SourceFile(foo_c, "foo.c", "foo_c", foo_c.read_text(encoding="utf-8")),
                SourceFile(reader_c, "reader.c", "reader_c", reader_c.read_text(encoding="utf-8")),
            ]
            result = RegexExtractor().extract_symbols(files, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(
                ("foo", "process"),
                calls,
                f"found arrow-qualified-call-to-unrelated-free-function edge: {calls}",
            )

    def test_regex_js_extractor_does_not_misclassify_plain_constants_as_functions(self) -> None:
        # Regression: _JS_ARROW matched *any* `const/let/var x = ...` with an
        # optional trailing "(" (zero-width), so plain data constants like
        # `const apiUrl = "...";` or `const config = {...};` were recorded as
        # "function" symbols regardless of their actual value. Real arrow
        # functions and function expressions must still be detected.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "config.js"
            f.write_text(
                'export const apiUrl = "https://example.com";\n'
                "export const config = { retries: 3 };\n"
                "export const helper = (x) => x + 1;\n"
                "const process = function(x) { return x; };\n",
                encoding="utf-8",
            )
            tuples = [(f, "config.js", "config_js", f.read_text(encoding="utf-8"))]
            nodes, _edges, _truncated = extract_symbols(tuples)
            labels_by_kind: dict[str, str] = {n.label: n.kind for n in nodes.values()}
            self.assertNotIn("apiUrl", labels_by_kind, "plain string constant misclassified as a symbol")
            self.assertNotIn("config", labels_by_kind, "plain object constant misclassified as a symbol")
            self.assertEqual(labels_by_kind.get("helper"), "function", "arrow function should still be detected")
            self.assertEqual(labels_by_kind.get("process"), "function", "function expression should still be detected")

    def test_tree_sitter_resolves_rust_module_qualified_call_among_duplicate_names(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "crates/locus-frontends/src/formula.rs": "pub fn parse(input: &str) -> i32 { 1 }\n",
            "crates/other/src/parser.rs": "pub fn parse(input: &str) -> i32 { 2 }\n",
            "crates/locus-pipeline/src/lib.rs": (
                "pub fn parse_to_ir(input: &str) -> i32 {\n    locus_frontends::formula::parse(input)\n}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_"), text))

            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        parse_to_ir = next(node.id for node in result.nodes.values() if node.label == "parse_to_ir")
        formula_parse = next(
            node.id
            for node in result.nodes.values()
            if node.label == "parse" and node.path.endswith("locus-frontends/src/formula.rs")
        )
        self.assertTrue(
            any(
                edge.source == parse_to_ir and edge.target == formula_parse and edge.type == "calls"
                for edge in result.edges
            )
        )

    def test_tree_sitter_links_rust_test_expr_type_use_to_enum(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "crates/locus-engine/src/expression.rs": ("pub enum Expr { Constant(i32), Add(Box<Expr>, Box<Expr>) }\n"),
            "crates/locus-engine/tests/expression_test.rs": (
                "#[test]\n"
                "fn simplifies_expr() {\n"
                "    let expr = Expr::Constant(1);\n"
                "    assert!(matches!(expr, Expr::Constant(1)));\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_"), text))

            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        test_id = next(node.id for node in result.nodes.values() if node.label == "simplifies_expr")
        expr_id = next(node.id for node in result.nodes.values() if node.label == "Expr")
        self.assertTrue(
            any(
                edge.source == test_id and edge.target == expr_id and edge.type == "references" for edge in result.edges
            )
        )

    def test_tree_sitter_types_closure_and_loop_receivers_from_element_types(self) -> None:
        # Receiver typing previously stopped at the container: `Vec<Expr>`
        # yielded "Vec", so a closure or loop variable bound to one of its
        # elements had no type and its method calls fell out of topology --
        # the dominant unresolved shape in an idiomatic Rust workspace.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/expr.rs": "pub struct Expr; impl Expr { pub fn count_ops(&self) -> usize { 0 } }\n",
            "src/run.rs": (
                "use crate::expr::Expr;\n"
                "pub fn total(items: Vec<Expr>) -> usize {\n"
                "    let mut n = 0;\n"
                "    for item in items.iter() { n += item.count_ops(); }\n"
                "    n\n"
                "}\n"
                "pub fn mapped(rows: &[Expr]) -> Vec<usize> {\n"
                "    rows.iter().map(|r| r.count_ops()).collect()\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        target = next(node.id for node in result.nodes.values() if node.label == "count_ops" and node.kind == "method")
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == target and edge.source in result.nodes
        }
        # Both the for-loop binding and the closure parameter must resolve.
        self.assertIn("total", callers)
        self.assertIn("mapped", callers)

    def test_rust_element_type_refuses_generic_and_non_type_parameters(self) -> None:
        # The inference must stay conservative: a generic parameter is not a
        # concrete receiver, and claiming one would attach calls to a type
        # that does not exist.
        from graphgraph.scanner.frontends.rust import _rust_element_type

        self.assertEqual(_rust_element_type("Vec<Expr>"), "Expr")
        self.assertEqual(_rust_element_type("&[Finding]"), "Finding")
        self.assertEqual(_rust_element_type("HashMap<String, Advisor>"), "Advisor")
        self.assertEqual(_rust_element_type("Vec<Arc<Expr>>"), "Expr")
        for rejected in ("T", "Vec<T>", "HashMap<K, V>", "(A, B)", "u32", "Vec<(A, B)>"):
            self.assertEqual(_rust_element_type(rejected), "", rejected)

    def test_tree_sitter_types_inline_call_receivers_from_return_types(self) -> None:
        # `expr_or_empty(ir).count_ops()` -- the receiver is whatever the inner
        # call returns. Receivers that were not bare identifiers were blanked
        # outright, so a method reached only through a call result had no
        # caller edge and read as dead.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/expr.rs": "pub struct Expr; impl Expr { pub fn count_ops(&self) -> usize { 0 } }\n",
            "src/build.rs": (
                "use crate::expr::Expr;\n"
                "fn expr_or_empty(flag: bool) -> Expr { Expr }\n"
                "pub fn op_count(flag: bool) -> usize {\n"
                "    expr_or_empty(flag).count_ops()\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        target = next(node.id for node in result.nodes.values() if node.label == "count_ops" and node.kind == "method")
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == target and edge.source in result.nodes
        }
        self.assertIn("op_count", callers)

    def test_ambiguous_return_type_is_not_receiver_evidence(self) -> None:
        # Two functions of the same name returning different types cannot type
        # a receiver; guessing one would attach the call to the wrong owner.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/types.rs": (
                "pub struct Alpha; impl Alpha { pub fn run(&self) {} }\n"
                "pub struct Beta; impl Beta { pub fn run(&self) {} }\n"
            ),
            "src/a.rs": "use crate::types::Alpha;\nfn make(v: bool) -> Alpha { Alpha }\n",
            "src/b.rs": "use crate::types::Beta;\nfn make(v: bool) -> Beta { Beta }\n",
            "src/use.rs": "pub fn go(v: bool) { make(v).run(); }\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        run_targets = {
            edge.target
            for edge in result.edges
            if edge.type == "calls"
            and edge.source == go_id
            and result.nodes.get(edge.target)
            and result.nodes[edge.target].label == "run"
        }
        self.assertEqual(run_targets, set(), "ambiguous return type must not produce a calls edge")

    def test_declared_type_wins_over_inferred_return_type(self) -> None:
        # Return-type inference must not overwrite a declared annotation or
        # parameter type. It did, and the damage was invisible in the
        # resolved/unknown ratio -- displaced sites leave that denominator
        # entirely -- while costing real calls edges.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/types.rs": (
                "pub struct Declared; impl Declared { pub fn act(&self) {} }\n"
                "pub struct Returned; impl Returned { pub fn act(&self) {} }\n"
            ),
            "src/make.rs": "use crate::types::Returned;\nfn build(v: bool) -> Returned { Returned }\n",
            "src/use.rs": (
                "use crate::types::Declared;\n"
                "pub fn go(v: bool) {\n"
                "    let build: Declared = Declared;\n"
                "    build.act();\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        owners = {
            result.nodes[edge.target].id.split("__")[-2]
            for edge in result.edges
            if edge.type == "calls"
            and edge.source == go_id
            and result.nodes.get(edge.target)
            and result.nodes[edge.target].label == "act"
        }
        self.assertEqual(owners, {"Declared"}, f"declared type must win, got {owners}")

    def test_external_and_unmatched_are_separated_not_merged(self) -> None:
        # The combined external_or_unmatched bucket merged two opposite
        # outcomes: correctly declining to link a call the graph does not own
        # (success) and failing to link one it does (failure). On z3 that
        # bucket held 94.3% of all call sites, so the tool's largest health
        # counter could not distinguish working from broken. These two calls
        # sit in the same function and must land in different buckets.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            # Owner defines `persist`; nothing internal defines `dumps`.
            "src/store.py": ("class Store:\n    def persist(self, item):\n        return item\n"),
            # `other` is typed to Store, but `missing` is defined on no
            # internal symbol at all -> external. `helper` IS defined
            # internally (on Store, as persist's sibling) but not on the
            # receiver's type -> a real miss.
            "src/run.py": (
                "import json\n"
                "from store import Store\n"
                "class Other:\n"
                "    def helper(self):\n"
                "        return 1\n"
                "def run(payload):\n"
                "    other: Store = Store()\n"
                "    other.helper()\n"
                "    return json.dumps(payload)\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        # The invariant that makes the split safe to publish: the two halves
        # must exactly partition the legacy total, so existing consumers
        # reading `unresolved` see no drift.
        self.assertEqual(
            result.external_resolved_member_calls + result.unmatched_member_calls,
            result.unresolved_member_calls,
        )
        # And the split must actually discriminate -- a partition that dumps
        # everything into one side would satisfy the sum above while being
        # exactly as undiagnostic as the merged counter it replaced.
        self.assertGreater(
            result.external_resolved_member_calls,
            0,
            "a call to a name no internal symbol defines must count as external",
        )
        self.assertGreater(
            result.unmatched_member_calls,
            0,
            "a typed receiver whose method exists internally but not on that type is a real miss, not an external call",
        )

    def test_unknown_receiver_histogram_partitions_the_total(self) -> None:
        # A single opaque unknown_receiver total says a resolver pass is
        # needed without saying which one. Inferring the shapes from source
        # patterns produced wrong priorities repeatedly -- `self.method()` was
        # ranked the top gap while already resolving 183 of 218 sites.
        from graphgraph.scanner.frontends.model import classify_unknown_receiver

        self.assertEqual(classify_unknown_receiver(""), "complex_expression")
        self.assertEqual(classify_unknown_receiver("cfg.limits()"), "method_chain")
        self.assertEqual(classify_unknown_receiver("build()"), "call_result")
        self.assertEqual(classify_unknown_receiver("cfg.inner"), "field_chain")
        self.assertEqual(classify_unknown_receiver("a"), "short_local")
        self.assertEqual(classify_unknown_receiver("configuration"), "named_local")

    def test_histogram_counts_sum_to_the_unknown_receiver_total(self) -> None:
        # The breakdown is only trustworthy if it partitions the total; a
        # bucket that double-counts or drops sites would misdirect exactly
        # the decision it exists to inform.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/lib.rs": (
                "pub struct T; impl T { pub fn go(&self) {} }\n"
                "pub fn a(items: Vec<u8>) { for x in items.iter() { x.go(); } }\n"
                "pub fn b(v: bool) { make(v).go(); helper.go(); }\n"
                "pub fn c() { let q = 1; q.go(); }\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        histogram = dict(result.unknown_receiver_classes)
        self.assertEqual(
            sum(histogram.values()),
            result.unknown_receiver_member_calls,
            f"histogram {histogram} must partition the total",
        )

    def test_cross_language_self_and_non_self_receiver_precision_oracle(self) -> None:
        fixtures = {
            ".py": (
                "class Other:\n"
                "    def Handle(self): return 1\n"
                "class Service:\n"
                "    def Handle(self): return 2\n"
                "    def Run(self): return self.Handle()\n"
                "    def RunOther(self, other: Other): return other.Handle()\n",
                ("Run", "Handle"),
                ("RunOther", "Handle"),
                True,
            ),
            ".rs": (
                "struct Other;\n"
                "impl Other { fn handle(&self) -> i32 { 1 } }\n"
                "struct Service;\n"
                "impl Service {\n"
                "  fn handle(&self) -> i32 { 2 }\n"
                "  fn run(&self) -> i32 { self.handle() }\n"
                "  fn run_other(&self, other: &Other) -> i32 { other.handle() }\n"
                "}\n",
                ("run", "handle"),
                ("run_other", "handle"),
                True,
            ),
            ".cs": (
                "class Other { public int Handle() { return 1; } }\n"
                "class Service {\n"
                "  public int Handle() { return 2; }\n"
                "  public int Run() { return this.Handle(); }\n"
                "  public int RunOther(Other other) { return other.Handle(); }\n"
                "}\n",
                ("Run", "Handle"),
                ("RunOther", "Handle"),
                True,
            ),
            ".js": (
                "class Other { Handle() { return 1; } }\n"
                "class Service {\n"
                "  Handle() { return 2; }\n"
                "  Run() { return this.Handle(); }\n"
                "  RunOther(other) { return other.Handle(); }\n"
                "}\n",
                ("Run", "Handle"),
                ("RunOther", "Handle"),
                False,
            ),
        }
        for suffix, (text, self_call, other_call, typed_other) in fixtures.items():
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"fixture{suffix}"
                path.write_text(text, encoding="utf-8")
                result = select_extractor("tree_sitter").extract_symbols(
                    [SourceFile(path, path.name, f"fixture_{suffix[1:]}", text)],
                    max_total_symbols=100,
                )
                labels = {node_id: node.label for node_id, node in result.nodes.items()}
                owners = {
                    node_id: labels.get(node.parent, "")
                    for node_id, node in result.nodes.items()
                }
                calls = {
                    (labels[edge.source], owners[edge.target], labels[edge.target])
                    for edge in result.edges
                    if edge.type == "calls"
                    and edge.source in labels
                    and edge.target in labels
                }

                self.assertIn((self_call[0], "Service", self_call[1]), calls)
                self.assertNotIn((other_call[0], "Service", other_call[1]), calls)
                if typed_other:
                    self.assertIn((other_call[0], "Other", other_call[1]), calls)
                else:
                    self.assertNotIn((other_call[0], "Other", other_call[1]), calls)
                    self.assertGreaterEqual(result.unknown_receiver_member_calls, 1)

    def test_inherited_method_resolves_through_the_base_chain(self) -> None:
        # Resolution required the method to be owned by the receiver's exact
        # class, so every inherited call failed with both ends already in the
        # graph: `app.route()` on a Flask missed because `route` is defined on
        # a base. On flask this bucket was 69 sites -- and it was invisible to
        # the unknown_receiver histogram, because a known type with no owner
        # match falls through to `unresolved` instead.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Scaffold:\n"
            "    def route(self):\n"
            "        return 1\n\n"
            "class App(Scaffold):\n"
            "    pass\n\n"
            "class Flask(App):\n"
            "    pass\n\n"
            "def go(app: Flask):\n"
            "    return app.route()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "a.py", "a_py", text)], max_total_symbols=50
            )

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        targets = {
            result.nodes[edge.target].label
            for edge in result.edges
            if edge.type == "calls" and edge.source == go_id and edge.target in result.nodes
        }
        self.assertIn("route", targets)
        self.assertTrue(
            any(edge.type == "implements" for edge in result.edges),
            "class inheritance must be recorded as edges, not only used internally",
        )

    def test_override_wins_over_the_base_definition(self) -> None:
        # The chain is walked nearest-first; a subclass that overrides must
        # attribute the call to its own definition, not the inherited one.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Base:\n"
            "    def run(self):\n"
            "        return 1\n\n"
            "class Child(Base):\n"
            "    def run(self):\n"
            "        return 2\n\n"
            "def go(c: Child):\n"
            "    return c.run()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "b.py", "b_py", text)], max_total_symbols=50
            )

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        owners = {
            result.nodes[edge.target].id.split("__")[-2]
            for edge in result.edges
            if edge.type == "calls"
            and edge.source == go_id
            and result.nodes.get(edge.target)
            and result.nodes[edge.target].label == "run"
        }
        self.assertEqual(owners, {"Child"}, f"override must win, got {owners}")

    def test_cyclic_base_classes_do_not_hang_extraction(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = "class A(B):\n    pass\n\nclass B(A):\n    def go(self):\n        return 1\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "c.py", "c_py", text)], max_total_symbols=50
            )
        self.assertTrue(result.nodes)

    def test_typescript_member_calls_resolve_from_annotations(self) -> None:
        # Receiver typing existed only for Rust and Python, so TypeScript fell
        # through with no types at all: on a mixed repo, not one TS method had
        # a known caller while the Python half resolved normally. Extraction
        # was never the problem -- classes, methods and interfaces were all
        # recovered; nothing read the annotations sitting next to them.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "export class Store {\n"
            "  save(x: string): void {}\n"
            "}\n"
            "export function run(s: Store): void { s.save('a'); }\n"
            "export class Wrapper {\n"
            "  private store: Store;\n"
            "  go(): void { this.store.save('b'); }\n"
            "}\n"
            "export function viaNew(): void { const st = new Store(); st.save('c'); }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.ts"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "a.ts", "a_ts", text)], max_total_symbols=60
            )

        target = next(node.id for node in result.nodes.values() if node.label == "save" and node.kind == "method")
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == target and edge.source in result.nodes
        }
        # Parameter annotation, `this.field`, and `new` binding respectively.
        self.assertEqual(callers, {"run", "go", "viaNew"}, f"got {callers}")

    def test_typescript_builtin_types_are_not_claimed_as_receivers(self) -> None:
        # `s: string` names nothing in the graph. Binding it would attach calls
        # to whatever repo class happened to share a method name.
        from graphgraph.scanner.frontends.typescript import _ts_local_types

        types = _ts_local_types("function f(s: string, n: number, o: MyThing) {")
        self.assertEqual(types, {"o": "MyThing"})

    def test_typescript_generic_parameter_is_not_a_type(self) -> None:
        from graphgraph.scanner.frontends.typescript import _ts_local_types

        self.assertEqual(_ts_local_types("function f<T>(item: T) {"), {})

    def test_return_types_come_from_the_annotation_not_the_docstring(self) -> None:
        # The caller truncates a definition at its opening brace, which bounds
        # the return annotation for brace languages and does nothing for
        # Python -- so a DOTALL match after `->` swallowed the whole function
        # and every capitalized docstring word became a candidate return type.
        # On flask that produced a `returns` edge from library code to a test
        # fixture class named X, and made incremental and full scans disagree.
        from graphgraph.scanner.frontends.syntax import _return_type_names

        python_with_docstring = (
            "def after_this_request(\n"
            "    f: ft.AfterRequestCallable[t.Any],\n"
            ") -> ft.AfterRequestCallable[t.Any]:\n"
            '    """Decorate a function. Therefore X, Foo, Hello World."""\n'
            "    return f\n"
        )
        self.assertEqual(
            _return_type_names(python_with_docstring),
            ("AfterRequestCallable", "Any"),
        )

    def test_subscripted_and_rust_return_types_still_resolve(self) -> None:
        # The trim must stop at the signature's own terminator, not at the
        # first colon inside a subscript.
        from graphgraph.scanner.frontends.syntax import _return_type_names

        self.assertEqual(
            _return_type_names("def f(a) -> Dict[str, MyType]:\n    pass\n"),
            ("Dict", "MyType"),
        )
        self.assertEqual(
            _return_type_names("fn parse(a: u32) -> Result<Expr> {\n    todo!()\n}"),
            ("Expr",),
        )

    def test_commented_and_stringified_declarations_do_not_type_receivers(self) -> None:
        # The pattern-matching extractors read raw source, so commented-out
        # code and code inside string literals were parsed as real
        # declarations: `// let fake: Wrong = x` typed a local named `fake`,
        # which then attached its calls to whatever class `Wrong` named. The
        # parse tree already marks these regions; blanking them first costs
        # nothing and removes a whole class of false evidence.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct Wrong; impl Wrong { pub fn hit(&self) {} }\n"
            "pub struct Report; impl Report { pub fn hit(&self) {} }\n"
            "pub fn run(real: Report) {\n"
            "    // let fake: Wrong = make();\n"
            '    let s = "let other: Wrong = y";\n'
            "    real.hit();\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "a.rs", "a_rs", text)], max_total_symbols=40
            )

        owners = {
            result.nodes[edge.target].id.split("__")[-2]
            for edge in result.edges
            if edge.type == "calls" and result.nodes.get(edge.target) and result.nodes[edge.target].label == "hit"
        }
        self.assertEqual(owners, {"Report"}, f"comment/string leaked a type: {owners}")

    def test_literal_blanking_is_not_applied_to_python(self) -> None:
        # Python's extractor uses a real AST parse, which already ignores
        # comments and string contents. Blanking literals leaves whitespace
        # its parser then rejects, so the two must not be combined.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Engine:\n"
            "    def start(self):\n"
            "        return 1\n\n"
            "def go(e: Engine):\n"
            '    label = "some string with (unbalanced"\n'
            "    return e.start()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "p.py", "p_py", text)], max_total_symbols=40
            )

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        targets = {
            result.nodes[edge.target].label
            for edge in result.edges
            if edge.type == "calls" and edge.source == go_id and edge.target in result.nodes
        }
        self.assertIn("start", targets)


class PythonConstructorParameterTypesTest(unittest.TestCase):
    """`self.x = x` takes its type from the parameter annotation."""

    def test_bare_name_assignment_adopts_the_parameter_annotation(self) -> None:
        # The type is declared, just in the signature rather than at the
        # assignment. Reading only the right-hand side saw a bare Name and
        # gave up, which left flask's `self.app.do_teardown_request(...)`
        # with an untyped receiver and so no calls edge at all.
        from graphgraph.scanner.frontends.python import _python_class_field_types

        types = _python_class_field_types(
            "class AppContext:\n"
            "    def __init__(self, app: Flask, name) -> None:\n"
            "        self.app = app\n"
            "        self.name = name\n"
        )
        self.assertEqual(types.get(("AppContext", "app")), "Flask")
        # No annotation, no guess.
        self.assertNotIn(("AppContext", "name"), types)

    def test_explicit_annotation_still_wins_over_the_parameter(self) -> None:
        from graphgraph.scanner.frontends.python import _python_class_field_types

        types = _python_class_field_types(
            "class C:\n    def __init__(self, dep: Base) -> None:\n        self.dep: Derived = dep\n"
        )
        self.assertEqual(types.get(("C", "dep")), "Derived")

    def test_conflicting_writes_are_still_refused(self) -> None:
        # Two constructors assigning different parameter types is not evidence
        # of either; the existing stability rule must keep applying.
        from graphgraph.scanner.frontends.python import _python_class_field_types

        types = _python_class_field_types(
            "class C:\n"
            "    def __init__(self, dep: Alpha) -> None:\n"
            "        self.dep = dep\n"
            "    def reset(self, dep: Beta) -> None:\n"
            "        self.dep = dep\n"
        )
        self.assertNotIn(("C", "dep"), types)
