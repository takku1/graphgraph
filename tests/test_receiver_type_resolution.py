from __future__ import annotations

import unittest
from pathlib import Path

from graphgraph.scanner.frontends.module_calls import whole_module_binding_names
from graphgraph.scanner.frontends.python import (
    _python_class_field_types,
    _python_local_types,
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

    def test_chains_are_not_resolved(self) -> None:
        # Multi-hop needs the deferred-obligation design (stage 4). Guessing
        # here would trade the precision the design is built to protect.
        body = """
def handler(ctx: AppContext):
    cfg = ctx.app.config
"""
        fields = {("AppContext", "app"): "Flask", ("Flask", "config"): "Config"}
        self.assertNotIn("cfg", _python_local_types(body, field_types=fields))


class ProjectFieldTypeTest(unittest.TestCase):
    """Stage 2: a field declared in one file must be visible from another.

    Confined to a single file the join was measurably a near no-op -- one extra
    resolved call across flask, requests, and mem0 -- because the declaring
    class and the using function almost never share a file.
    """

    def _project_map(self, sources: dict[str, str]):
        from graphgraph.scanner.frontends.edges import _project_field_types
        from graphgraph.scanner.frontends.model import SourceFile

        files = []
        for rel, text in sources.items():
            files.append(
                (SourceFile(path=Path(rel), rel=rel, file_node_id=rel, text=text), [], None)
            )
        return _project_field_types(files)

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
