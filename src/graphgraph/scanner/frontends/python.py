"""Python-specific type inference over the stdlib ast module."""

from __future__ import annotations

import ast as py_ast
import re
import textwrap

from .syntax import (
    _PYTHON_BUILTIN_TYPES,
)


def _python_type_name(annotation: py_ast.AST | None) -> str:
    """Return a conservative runtime type name from a Python annotation."""
    if isinstance(annotation, py_ast.Name):
        name = annotation.id
    elif isinstance(annotation, py_ast.Attribute):
        name = annotation.attr
    elif isinstance(annotation, py_ast.Constant) and isinstance(annotation.value, str):
        try:
            parsed = py_ast.parse(annotation.value, mode="eval").body
        except (SyntaxError, ValueError):
            parsed = None
        if parsed is not None and not (
            isinstance(parsed, py_ast.Constant) and parsed.value == annotation.value
        ):
            return _python_type_name(parsed)
        match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", annotation.value)
        name = match.group(1) if match else ""
    elif isinstance(annotation, py_ast.BinOp) and isinstance(annotation.op, py_ast.BitOr):
        left = _python_type_name(annotation.left)
        right = _python_type_name(annotation.right)
        if left in {"", "None"}:
            name = right
        elif right in {"", "None"}:
            name = left
        else:
            return ""
    elif isinstance(annotation, py_ast.Subscript):
        outer = _python_type_name(annotation.value)
        if outer in {"Optional", "ClassVar"}:
            return _python_type_name(annotation.slice)
        if outer == "Annotated":
            first = annotation.slice.elts[0] if isinstance(annotation.slice, py_ast.Tuple) else annotation.slice
            return _python_type_name(first)
        if outer == "Union" and isinstance(annotation.slice, py_ast.Tuple):
            members = [name for item in annotation.slice.elts if (name := _python_type_name(item)) != "None"]
            return members[0] if len(set(members)) == 1 else ""
        name = outer
    else:
        return ""
    return f"builtins.{name}" if name in _PYTHON_BUILTIN_TYPES else name

def _python_value_type(value: py_ast.AST | None) -> str:
    if isinstance(value, py_ast.Call):
        type_name = _python_type_name(value.func)
        # A call is constructor evidence only when the callee is syntactically
        # class-like or a builtin constructor.  Treating `make_graph()` as type
        # "make_graph" would not create a false edge, but it would incorrectly
        # classify the receiver as external instead of honestly unknown.
        if type_name.startswith("builtins.") or type_name[:1].isupper():
            return type_name
        return ""
    literal_types: tuple[tuple[type[py_ast.AST], str], ...] = (
        (py_ast.List, "builtins.list"),
        (py_ast.ListComp, "builtins.list"),
        (py_ast.Dict, "builtins.dict"),
        (py_ast.DictComp, "builtins.dict"),
        (py_ast.Set, "builtins.set"),
        (py_ast.SetComp, "builtins.set"),
        (py_ast.Tuple, "builtins.tuple"),
        (py_ast.GeneratorExp, "builtins.generator"),
    )
    for node_type, type_name in literal_types:
        if isinstance(value, node_type):
            return type_name
    if isinstance(value, py_ast.Constant):
        return f"builtins.{type(value.value).__name__}"
    return ""

def _python_body_nodes(function: py_ast.FunctionDef | py_ast.AsyncFunctionDef) -> list[py_ast.AST]:
    """Walk one function body without borrowing bindings from nested scopes."""
    nodes: list[py_ast.AST] = []
    stack = list(reversed(function.body))
    while stack:
        node = stack.pop()
        nodes.append(node)
        if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef, py_ast.Lambda, py_ast.ClassDef)):
            continue
        stack.extend(reversed(list(py_ast.iter_child_nodes(node))))
    return nodes

def _python_assignment_names(target: py_ast.AST | None) -> set[str]:
    if isinstance(target, py_ast.Name):
        return {target.id}
    if isinstance(target, (py_ast.Tuple, py_ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(_python_assignment_names(item))
        return names
    return set()

def _python_local_types(body: str) -> dict[str, str]:
    """Infer Python receiver types only from explicit, stable local evidence."""
    try:
        module = py_ast.parse(textwrap.dedent(body))
    except (IndentationError, SyntaxError, ValueError):
        return {}
    function = next(
        (node for node in module.body if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef))),
        None,
    )
    if function is None:
        return {}

    annotated: dict[str, str] = {}
    writes: dict[str, list[str]] = {}
    arguments = (
        list(function.args.posonlyargs)
        + list(function.args.args)
        + list(function.args.kwonlyargs)
        + ([function.args.vararg] if function.args.vararg else [])
        + ([function.args.kwarg] if function.args.kwarg else [])
    )
    for argument in arguments:
        if type_name := _python_type_name(argument.annotation):
            annotated[argument.arg] = type_name

    for node in _python_body_nodes(function):
        if isinstance(node, py_ast.AnnAssign):
            if isinstance(node.target, py_ast.Name):
                if type_name := _python_type_name(node.annotation):
                    annotated[node.target.id] = type_name
                writes.setdefault(node.target.id, []).append(_python_value_type(node.value))
        elif isinstance(node, (py_ast.Assign, py_ast.NamedExpr)):
            targets = node.targets if isinstance(node, py_ast.Assign) else [node.target]
            value_type = _python_value_type(node.value)
            for target in targets:
                for name in _python_assignment_names(target):
                    writes.setdefault(name, []).append(value_type)
        elif isinstance(node, py_ast.AugAssign):
            for name in _python_assignment_names(node.target):
                writes.setdefault(name, []).append("")
        elif isinstance(node, (py_ast.For, py_ast.AsyncFor)):
            for name in _python_assignment_names(node.target):
                writes.setdefault(name, []).append("")
        elif isinstance(node, (py_ast.With, py_ast.AsyncWith)):
            for item in node.items:
                for name in _python_assignment_names(item.optional_vars):
                    writes.setdefault(name, []).append("")

    result = dict(annotated)
    for name, assigned_types in writes.items():
        stable_types = set(assigned_types)
        if name not in annotated and len(stable_types) == 1 and "" not in stable_types:
            result[name] = assigned_types[0]
    return result

def _python_parameter_types(
    function: py_ast.FunctionDef | py_ast.AsyncFunctionDef,
) -> dict[str, str]:
    """Map parameter names to their declared annotation, where one is given."""
    args = function.args
    every = [
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *([args.vararg] if args.vararg else []),
        *([args.kwarg] if args.kwarg else []),
    ]
    return {
        arg.arg: type_name
        for arg in every
        if arg.annotation is not None and (type_name := _python_type_name(arg.annotation))
    }


def _python_class_field_types(source: str) -> dict[tuple[str, str], str]:
    """Infer stable ``self.field`` types from annotations or constructor writes."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError):
        return {}
    result: dict[tuple[str, str], str] = {}
    writes: dict[tuple[str, str], list[str]] = {}
    for class_node in (node for node in py_ast.walk(module) if isinstance(node, py_ast.ClassDef)):
        for item in class_node.body:
            if isinstance(item, py_ast.AnnAssign) and isinstance(item.target, py_ast.Name):
                if type_name := _python_type_name(item.annotation):
                    result[(class_node.name, item.target.id)] = type_name
            if not isinstance(item, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)):
                continue
            parameter_types = _python_parameter_types(item)
            for node in _python_body_nodes(item):
                if isinstance(node, py_ast.AnnAssign):
                    targets = [node.target]
                    annotated_type = _python_type_name(node.annotation)
                    value_type = _python_value_type(node.value)
                elif isinstance(node, py_ast.Assign):
                    targets = list(node.targets)
                    annotated_type = ""
                    value_type = _python_value_type(node.value)
                    # `self.app = app` where the signature says `app: Flask`.
                    # The type is declared, not guessed -- it is just declared
                    # in the parameter list rather than at the assignment, and
                    # reading only the right-hand side misses it. This is what
                    # left flask's `self.app.do_teardown_request(...)` with an
                    # untyped receiver and so no calls edge at all.
                    if not value_type and isinstance(node.value, py_ast.Name):
                        value_type = parameter_types.get(node.value.id, "")
                else:
                    continue
                for target in targets:
                    if (
                        isinstance(target, py_ast.Attribute)
                        and isinstance(target.value, py_ast.Name)
                        and target.value.id == "self"
                    ):
                        key = (class_node.name, target.attr)
                        if annotated_type:
                            result[key] = annotated_type
                        writes.setdefault(key, []).append(value_type)
    for key, assigned_types in writes.items():
        stable_types = set(assigned_types)
        if key not in result and len(stable_types) == 1 and "" not in stable_types:
            result[key] = assigned_types[0]
    return result
