from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph.scanner.frontends import SourceIR, select_extractor
from graphgraph.scanner.frontends.module_calls import whole_module_binding_names
from graphgraph.scanner.frontends.python import (
    _python_class_field_types,
    _python_imported_global_facts,
    _python_imported_global_types,
    _python_local_types,
    _python_module_global_facts,
    _python_module_global_types,
    _python_module_return_facts,
    _python_type_solution,
)
from graphgraph.scanner.frontends.type_facts import (
    Evidence,
    TypeFact,
    TypeState,
    join_type_fact_maps,
)


class AttributeValueTypingTest(unittest.TestCase):
    """Stage 1 of `docs/receiver-type-resolution.md`.

    Local type inference and class field types both already worked; nothing
    joined them, so `app = ctx.app` stayed untyped even when `ctx`'s type and
    `AppContext.app` were both known.
    """

    FLASK_CONTEXT = """
class AppContext:
    def __init__(self, app: Flask):
        self.app: Flask = app
"""

    def test_attribute_assignment_carries_the_field_type(self) -> None:
        body = """
def _render(ctx: AppContext, template, context):
    app = ctx.app
    app.update_template_context(context)
"""
        fields = _python_class_field_types(self.FLASK_CONTEXT)
        types = _python_local_types(body, field_types=fields)
        self.assertEqual(types.get("ctx"), "AppContext")
        self.assertEqual(types.get("app"), "Flask")

    def test_without_field_types_it_degrades_rather_than_guesses(self) -> None:
        body = """
def _render(ctx: AppContext, template, context):
    app = ctx.app
"""
        types = _python_local_types(body)
        self.assertEqual(types.get("ctx"), "AppContext")
        self.assertNotIn("app", types)

    def test_self_field_assignment_resolves_through_the_owner(self) -> None:
        fields = _python_class_field_types(
            """
class Engine:
    def __init__(self):
        self.registry: Registry = Registry()
"""
        )
        body = """
def run(self):
    reg = self.registry
    reg.dispatch()
"""
        types = _python_local_types(body, field_types=fields, owner="Engine")
        self.assertEqual(types.get("reg"), "Registry")

    def test_unknown_receiver_stays_unknown(self) -> None:
        body = """
def handler(thing):
    app = thing.app
"""
        types = _python_local_types(body, field_types={("AppContext", "app"): "Flask"})
        self.assertNotIn("app", types)

    def test_unknown_field_on_a_known_receiver_stays_unknown(self) -> None:
        body = """
def handler(ctx: AppContext):
    other = ctx.not_a_declared_field
"""
        types = _python_local_types(body, field_types={("AppContext", "app"): "Flask"})
        self.assertNotIn("other", types)

    def test_conflicting_writes_still_defeat_inference(self) -> None:
        # The single-type discipline is what keeps precision at 100%; an
        # attribute read must not be allowed to override it.
        body = """
def handler(ctx: AppContext, flag):
    app = ctx.app
    if flag:
        app = Other()
"""
        types = _python_local_types(body, field_types={("AppContext", "app"): "Flask"})
        self.assertNotIn("app", types)

    def test_attribute_chains_resolve_within_the_explicit_depth_bound(self) -> None:
        body = """
def handler(ctx: AppContext):
    cfg = ctx.app.config
"""
        fields = {("AppContext", "app"): "Flask", ("Flask", "config"): "Config"}
        types = _python_local_types(body, field_types=fields, max_attribute_depth=2)
        self.assertEqual(types.get("ctx.app"), "Flask")
        self.assertEqual(types.get("ctx.app.config"), "Config")
        self.assertEqual(types.get("cfg"), "Config")

    def test_attribute_chain_beyond_the_bound_has_an_unresolved_receipt(self) -> None:
        body = """
def handler(ctx: AppContext):
    cfg = ctx.app.config
"""
        fields = {("AppContext", "app"): "Flask", ("Flask", "config"): "Config"}
        solution = _python_type_solution(body, field_types=fields, max_attribute_depth=1)
        self.assertNotIn("cfg", solution.concrete_types)
        self.assertTrue(
            any(
                item.target == "cfg" and item.reason == "depth_limit"
                for item in solution.unresolved
            )
        )

    def test_ambiguous_field_fact_does_not_propagate(self) -> None:
        field_fact = TypeFact.from_evidence(
            "Flask",
            Evidence("field_annotation", "a.py:2"),
        ).join(
            TypeFact.from_evidence(
                "Django",
                Evidence("field_annotation", "b.py:2"),
            )
        )
        body = """
def handler(ctx: AppContext):
    app = ctx.app
"""
        solution = _python_type_solution(
            body,
            field_types={("AppContext", "app"): field_fact},
        )
        self.assertNotIn("app", solution.concrete_types)
        self.assertTrue(
            any(
                item.target == "app" and item.reason == "ambiguous_field"
                for item in solution.unresolved
            )
        )

    def test_alias_obligations_are_discharged_when_evidence_arrives_later(self) -> None:
        body = """
def handler():
    app = context
    context: AppContext = make_context()
"""
        solution = _python_type_solution(body)
        self.assertEqual(solution.concrete_types.get("context"), "AppContext")
        self.assertEqual(solution.concrete_types.get("app"), "AppContext")
        self.assertEqual(
            {item.kind for item in solution.facts["app"].evidence},
            {"annotation", "assignment"},
        )


class TypeFactLatticeTest(unittest.TestCase):
    def test_unknown_is_below_concrete_and_provenance_is_retained(self) -> None:
        unknown = TypeFact()
        direct = TypeFact.from_evidence("Flask", Evidence("annotation", "app"))
        joined = unknown.join(direct)
        self.assertEqual(joined.state, TypeState.CONCRETE)
        self.assertEqual(joined.concrete, "Flask")
        self.assertEqual(joined.evidence, direct.evidence)

    def test_conflicting_concrete_facts_join_to_ambiguous(self) -> None:
        flask = TypeFact.from_evidence("Flask", Evidence("annotation", "app"))
        django = TypeFact.from_evidence("Django", Evidence("assignment", "app"))
        joined = flask.join(django)
        self.assertEqual(joined.state, TypeState.AMBIGUOUS)
        self.assertIsNone(joined.concrete)
        self.assertEqual(joined.types, frozenset({"Django", "Flask"}))

    def test_binding_environments_join_instead_of_overwriting(self) -> None:
        local = {
            "app": TypeFact.from_evidence(
                "Flask",
                Evidence("module_annotation", "local.py:1"),
            )
        }
        imported = {
            "app": TypeFact.from_evidence(
                "Django",
                Evidence("import", "other.py:1"),
            )
        }
        joined = join_type_fact_maps(local, imported)
        self.assertEqual(joined["app"].state, TypeState.AMBIGUOUS)


class ModuleGlobalTypeTest(unittest.TestCase):
    def test_annotated_module_proxy_is_a_typed_fact(self) -> None:
        source = """
if TYPE_CHECKING:
    class FlaskProxy(Flask):
        pass

current_app: FlaskProxy = LocalProxy(_cv_app, "app")
"""
        self.assertEqual(_python_module_global_types(source).get("current_app"), "FlaskProxy")
        fact = _python_module_global_facts(source, "globals.py")["current_app"]
        self.assertEqual(fact.concrete, "FlaskProxy")
        self.assertEqual(fact.evidence[0].source, "globals.py:6")

    def test_imported_global_type_seeds_callable_receiver_resolution(self) -> None:
        body = """
def dispatch():
    current_app.ensure_sync(handler)
"""
        types = _python_local_types(body, initial_types={"current_app": "FlaskProxy"})
        self.assertEqual(types.get("current_app"), "FlaskProxy")

    def test_imported_global_join_requires_matching_module_provenance(self) -> None:
        project = {("globals", "current_app"): "FlaskProxy"}
        self.assertEqual(
            _python_imported_global_types(
                "from .globals import current_app as app\n",
                project,
            ),
            {"app": "FlaskProxy"},
        )
        self.assertEqual(
            _python_imported_global_types(
                "from unrelated import current_app\n",
                project,
            ),
            {},
        )

    def test_ambiguous_imported_global_fact_stays_ambiguous(self) -> None:
        project_fact = TypeFact.from_evidence(
            "FlaskProxy",
            Evidence("module_annotation", "a/globals.py:2"),
        ).join(
            TypeFact.from_evidence(
                "DjangoProxy",
                Evidence("module_annotation", "b/globals.py:2"),
            )
        )
        imported = _python_imported_global_facts(
            "from .globals import current_app\n",
            {("globals", "current_app"): project_fact},
        )
        solution = _python_type_solution(
            "def dispatch():\n    current_app.ensure_sync(handler)\n",
            initial_facts=imported,
        )
        self.assertEqual(solution.facts["current_app"].state, TypeState.AMBIGUOUS)
        self.assertNotIn("current_app", solution.concrete_types)

    def _extract(self, sources: dict[str, str]):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceIR(path, rel, rel.replace("/", "_"), text))
            return select_extractor("tree_sitter").extract_symbols(
                files,
                max_total_symbols=100,
            )

    def test_go_receiver_bound_to_a_constructor_result_resolves(self) -> None:
        """`x := NewThing()` must type its receiver, like Rust and TypeScript.

        Go's grammar names the result field `result`, not `return_type`, so
        every Go function looked unannotated and Go contributed nothing to the
        name -> return type map. `_go_bindings` then had nothing to consult,
        and was the only provider that never consulted it at all. `:=` was
        understood solely in its composite-literal form (`x := Engine{}`).

        Only names with one concrete result repo-wide are used, so an
        ambiguous name still resolves to nothing rather than to a guess.
        """
        result = self._extract(
            {
                "main.go": (
                    "package main\n"
                    "type Engine struct{ name string }\n"
                    "func (e *Engine) Run() int { return 1 }\n"
                    "type Widget struct{ id int }\n"
                    "func (w *Widget) Draw() int { return 3 }\n"
                    "func NewEngine() *Engine { return &Engine{} }\n"
                    "func OpenWidget() (*Widget, error) { return &Widget{}, nil }\n"
                    "func single() int {\n"
                    "\te := NewEngine()\n"
                    "\treturn e.Run()\n"
                    "}\n"
                    "func multi() int {\n"
                    "\tw, err := OpenWidget()\n"
                    "\tif err != nil { return 0 }\n"
                    "\treturn w.Draw()\n"
                    "}\n"
                ),
            }
        )
        calls = {
            (edge.source, edge.target)
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(
            ("main.go__single", "main.go__Engine__Run"),
            calls,
            "single-value `e := NewEngine()` did not type its receiver",
        )
        # Multi-value results are the dominant Go form: the first component is
        # what the variable binds, the trailing `error` carries no methods.
        self.assertIn(
            ("main.go__multi", "main.go__Widget__Draw"),
            calls,
            "`w, err := OpenWidget()` did not type its receiver from the first result",
        )

    def test_go_result_type_reads_only_nominal_types(self) -> None:
        """Slices, maps and builtins own no methods, so they must not bind."""
        from graphgraph.scanner.frontends.go import go_return_type_name

        self.assertEqual(go_return_type_name("*Engine"), "Engine")
        self.assertEqual(go_return_type_name("pkg.Engine"), "Engine")
        self.assertEqual(go_return_type_name("(*Widget, error)"), "Widget")
        self.assertEqual(go_return_type_name("[]*Widget"), "")
        self.assertEqual(go_return_type_name("map[string]Widget"), "")
        self.assertEqual(go_return_type_name("int"), "")
        self.assertEqual(go_return_type_name(""), "")

    def test_go_embedded_struct_promotes_methods(self) -> None:
        from graphgraph.scanner.frontends.go import go_embedded_types, go_struct_field_types

        source = (
            "type Store struct{}\n"
            "type Account struct {\n"
            "\tStore\n"
            "\tName string\n"
            "}\n"
        )
        self.assertEqual(go_embedded_types(source), {"Account": ("Store",)})
        self.assertEqual(go_struct_field_types(source)[("Account", "Store")], "Store")

        result = self._extract(
            {
                "store.go": "package p\ntype Store struct{}\nfunc (s Store) Save() int { return 1 }\n",
                "user.go": "package p\ntype Account struct { Store }\n",
                "app.go": "package p\nfunc Persist(account Account) int { return account.Save() }\n",
            }
        )
        calls = {
            (edge.source.rsplit("__", 1)[-1], edge.target.rsplit("__", 1)[-1])
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("Persist", "Save"), calls)

    def test_two_hop_receiver_expression_resolves_a_call_edge(self) -> None:
        result = self._extract(
            {
                "ctx.py": """
class Flask:
    def ensure_sync(self, func):
        return func

class AppContext:
    def __init__(self, app: Flask):
        self.app = app
""",
                "use.py": """
def wrapper(ctx: AppContext, func):
    return ctx.app.ensure_sync(func)
""",
            }
        )
        labels = {node_id: node.label for node_id, node in result.nodes.items()}
        calls = {
            (labels[edge.source], labels[edge.target])
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("wrapper", "ensure_sync"), calls)

    def test_imported_annotated_proxy_resolves_through_its_base_class(self) -> None:
        result = self._extract(
            {
                "globals.py": """
if TYPE_CHECKING:
    class Flask:
        def ensure_sync(self, func):
            return func

    class FlaskProxy(Flask):
        pass

current_app: FlaskProxy = LocalProxy()
""",
                "views.py": """
from .globals import current_app

def dispatch(handler):
    return current_app.ensure_sync(handler)
""",
            }
        )
        labels = {node_id: node.label for node_id, node in result.nodes.items()}
        calls = {
            (labels[edge.source], labels[edge.target])
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("dispatch", "ensure_sync"), calls)

    def test_package_reexport_preserves_global_proxy_fact(self) -> None:
        result = self._extract(
            {
                "pkg/globals.py": """
if TYPE_CHECKING:
    class App:
        def open_resource(self, name):
            return name

    class AppProxy(App):
        pass

current_app: AppProxy = LocalProxy()
""",
                "pkg/__init__.py": """
from .globals import current_app as current_app
""",
                "tutorial.py": """
from pkg import current_app

def initialize():
    return current_app.open_resource("schema.sql")
""",
            }
        )
        labels = {node_id: node.label for node_id, node in result.nodes.items()}
        calls = {
            (labels[edge.source], labels[edge.target])
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("initialize", "open_resource"), calls)

    def test_annotated_factory_return_types_an_assignment_receiver(self) -> None:
        result = self._extract(
            {
                "service.py": """
class Service:
    def run(self):
        return None

def make_service() -> Service:
    return Service()
""",
                "use.py": """
from .service import make_service

def invoke():
    service = make_service()
    service.run()
""",
            }
        )
        labels = {node_id: node.label for node_id, node in result.nodes.items()}
        calls = {
            (labels[edge.source], labels[edge.target])
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(("invoke", "run"), calls)

    def test_conflicting_factory_returns_do_not_type_a_receiver(self) -> None:
        result = self._extract(
            {
                "a.py": """
class Alpha:
    def run(self):
        return None

def build() -> Alpha:
    return Alpha()
""",
                "b.py": """
class Beta:
    def run(self):
        return None

def build() -> Beta:
    return Beta()
""",
                "use.py": """
def invoke():
    value = build()
    value.run()
""",
            }
        )
        labels = {node_id: node.label for node_id, node in result.nodes.items()}
        calls = {
            (labels[edge.source], labels[edge.target])
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertNotIn(("invoke", "run"), calls)

    def test_module_return_extraction_is_file_bounded_not_callable_bounded(self) -> None:
        functions = "\n".join(
            f"def make_{index}() -> Service:\n    return Service()\n"
            for index in range(25)
        )
        source = f"class Service:\n    pass\n\n{functions}"
        with patch(
            "graphgraph.scanner.frontends.edges._python_module_return_facts",
            wraps=_python_module_return_facts,
        ) as extract_returns:
            self._extract({"factories.py": source})

        # One project-index pass plus one per-source environment pass. The
        # count is independent of the 25 callables in the file.
        self.assertEqual(extract_returns.call_count, 2)


class ProjectFieldTypeTest(unittest.TestCase):
    """Stage 2: a field declared in one file must be visible from another.

    Confined to a single file the join was measurably a near no-op -- one extra
    resolved call across flask, requests, and mem0 -- because the declaring
    class and the using function almost never share a file.
    """

    def _project_map(self, sources: dict[str, str]):
        from graphgraph.scanner.frontends.edges import _project_field_types
        files = []
        for rel, text in sources.items():
            files.append(
                (SourceIR(path=Path(rel), rel=rel, file_node_id=rel, text=text), [], None)
            )
        return _project_field_types(files)

    def _project_facts(self, sources: dict[str, str]):
        from graphgraph.scanner.frontends.edges import _project_field_type_facts
        files = [
            (SourceIR(path=Path(rel), rel=rel, file_node_id=rel, text=text), [], None)
            for rel, text in sources.items()
        ]
        return _project_field_type_facts(files)

    def test_field_declared_in_another_file_is_visible(self) -> None:
        project = self._project_map(
            {
                "ctx.py": "class AppContext:\n    def __init__(self, app: Flask):\n        self.app = app\n",
                "templating.py": "def _render(ctx, template):\n    pass\n",
            }
        )
        self.assertEqual(project.get(("AppContext", "app")), "Flask")

        body = """
def _render(ctx: AppContext, template, context):
    app = ctx.app
    app.update_template_context(context)
"""
        self.assertEqual(_python_local_types(body, field_types=project).get("app"), "Flask")

    def test_unannotated_field_still_types_from_the_constructor_parameter(self) -> None:
        # Real flask writes `self.app = app` with no annotation; the type comes
        # from the annotated `__init__` parameter, not the assignment.
        project = self._project_map(
            {"ctx.py": "class AppContext:\n    def __init__(self, app: Flask):\n        self.app = app\n"}
        )
        self.assertEqual(project.get(("AppContext", "app")), "Flask")

    def test_conflicting_declarations_across_files_are_dropped(self) -> None:
        # Two unrelated classes sharing a name must not arbitrate a type.
        project = self._project_map(
            {
                "a.py": "class Ctx:\n    def __init__(self, app: Flask):\n        self.app = app\n",
                "b.py": "class Ctx:\n    def __init__(self, app: Django):\n        self.app = app\n",
            }
        )
        self.assertNotIn(("Ctx", "app"), project)

    def test_conflicting_project_field_facts_retain_ambiguity_and_provenance(self) -> None:
        facts = self._project_facts(
            {
                "a.py": "class Ctx:\n    def __init__(self, app: Flask):\n        self.app = app\n",
                "b.py": "class Ctx:\n    def __init__(self, app: Django):\n        self.app = app\n",
            }
        )
        fact = facts[("Ctx", "app")]
        self.assertEqual(fact.state, TypeState.AMBIGUOUS)
        self.assertEqual(fact.types, frozenset({"Django", "Flask"}))
        self.assertEqual(
            {item.source for item in fact.evidence},
            {"a.py:Ctx.app", "b.py:Ctx.app"},
        )

    def test_agreeing_declarations_survive(self) -> None:
        project = self._project_map(
            {
                "a.py": "class Ctx:\n    def __init__(self, app: Flask):\n        self.app = app\n",
                "b.py": "class Ctx:\n    def __init__(self, app: Flask):\n        self.app = app\n",
            }
        )
        self.assertEqual(project.get(("Ctx", "app")), "Flask")


class WholeModuleBindingTest(unittest.TestCase):
    """Stage 5: the one precision defect found across six repositories.

    `var send = require('send')` followed by `send(req, path, opts)` bound to
    the local `res.send` method. The discriminator must separate a whole-module
    binding from a member binding -- an earlier attempt matched the
    `require('./utils')` prefix of `require('./utils').normalizeTypes` and
    discarded six correct edges to win back one false positive.
    """

    def test_whole_module_require_is_bound(self) -> None:
        names = whole_module_binding_names(".js", "var send = require('send');")
        self.assertEqual(names, frozenset({"send"}))

    def test_member_require_is_not_bound(self) -> None:
        source = "var normalizeTypes = require('./utils').normalizeTypes;"
        self.assertEqual(whole_module_binding_names(".js", source), frozenset())

    def test_mixed_file_separates_the_two_forms(self) -> None:
        source = (
            "var send = require('send');\n"
            "var setCharset = require('./utils').setCharset;\n"
            "var cookie = require('cookie');\n"
        )
        self.assertEqual(whole_module_binding_names(".js", source), frozenset({"send", "cookie"}))

    def test_esm_default_and_namespace_imports_are_bound(self) -> None:
        source = "import cfg from './config';\nimport * as util from './util';\n"
        self.assertEqual(whole_module_binding_names(".js", source), frozenset({"cfg", "util"}))

    def test_non_js_suffixes_are_unaffected(self) -> None:
        self.assertEqual(
            whole_module_binding_names(".py", "import send\n"), frozenset()
        )


if __name__ == "__main__":
    unittest.main()
