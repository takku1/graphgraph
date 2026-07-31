"""Python-specific type inference over the stdlib ast module."""

from __future__ import annotations

import ast as py_ast
import re
import textwrap
from typing import Mapping

from .syntax import (
    _PYTHON_BUILTIN_TYPES,
)
from .type_facts import (
    Evidence,
    TypeFact,
    TypeObligation,
    TypeSolution,
    TypeState,
    solve_type_obligations,
)

DEFAULT_PYTHON_ATTRIBUTE_DEPTH = 3


def _python_type_name(annotation: py_ast.AST | None) -> str:
    """Return a conservative runtime type name from a Python annotation."""
    if isinstance(annotation, py_ast.Name):
        name = annotation.id
    elif isinstance(annotation, py_ast.Attribute):
        name = annotation.attr
    elif isinstance(annotation, py_ast.Constant) and isinstance(annotation.value, str):
        try:
            parsed = py_ast.parse(annotation.value, mode="eval").body
        except (SyntaxError, ValueError, RecursionError):
            parsed = None
        if parsed is not None and not (isinstance(parsed, py_ast.Constant) and parsed.value == annotation.value):
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


def _python_attribute_type(
    value: py_ast.AST | None,
    known_types: Mapping[str, str],
    field_types: Mapping[tuple[str, str], str],
) -> str:
    """Type of `recv.field` when the receiver's type and that field are known.

    This is the join that `self.`-only resolution was missing. `app = ctx.app`
    carries the type of `AppContext.app` whenever `ctx` is typed and that field
    is declared, but the receiver type and the field-type map lived in separate
    passes and were never consulted together.

    Deliberately one hop and receiver-must-be-a-plain-name: chains like
    `ctx.app.config` need a fixpoint over deferred obligations, which is a
    different design (see `docs/receiver-type-resolution.md`) and must not be
    faked by guessing here.
    """
    if not isinstance(value, py_ast.Attribute) or not isinstance(value.value, py_ast.Name):
        return ""
    receiver_type = known_types.get(value.value.id, "")
    if not receiver_type:
        return ""
    return field_types.get((receiver_type, value.attr), "")


def _python_value_type(
    value: py_ast.AST | None,
    known_types: Mapping[str, str] | None = None,
    field_types: Mapping[tuple[str, str], str] | None = None,
) -> str:
    if known_types is not None and field_types:
        if attribute_type := _python_attribute_type(value, known_types, field_types):
            return attribute_type
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


def _python_function_return_type(body: str) -> str:
    """Infer one stable concrete return type from a Python callable body."""
    try:
        module = py_ast.parse(textwrap.dedent(body))
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return ""
    function = next(
        (node for node in module.body if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef))),
        None,
    )
    if function is None:
        return ""
    if annotated := _python_type_name(function.returns):
        return annotated
    local_types = _python_local_types(body)
    return _python_function_node_return_type(function, local_types)


def _python_function_node_return_type(
    function: py_ast.FunctionDef | py_ast.AsyncFunctionDef,
    local_types: Mapping[str, str],
) -> str:
    """Infer one return type from an already parsed function node."""
    if annotated := _python_type_name(function.returns):
        return annotated
    returns: set[str] = set()
    for node in _python_body_nodes(function):
        if not isinstance(node, py_ast.Return) or node.value is None:
            continue
        if isinstance(node.value, py_ast.Name):
            type_name = local_types.get(node.value.id, "")
        else:
            type_name = _python_value_type(node.value)
        if not type_name:
            return ""
        returns.add(type_name)
    return next(iter(returns)) if len(returns) == 1 else ""


def _python_parameter_names(body: str) -> set[str]:
    """Return parameter bindings for the outer callable in *body*."""
    try:
        module = py_ast.parse(textwrap.dedent(body))
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return set()
    function = next(
        (node for node in module.body if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef))),
        None,
    )
    if function is None:
        return set()
    args = function.args
    return {
        arg.arg
        for arg in (
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            *([args.vararg] if args.vararg else []),
            *([args.kwarg] if args.kwarg else []),
        )
    }


def _python_fixture_return_types(source: str) -> dict[str, str]:
    """Return concrete types for functions explicitly decorated as fixtures."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return {}

    def decorator_name(node: py_ast.AST) -> str:
        if isinstance(node, py_ast.Call):
            return decorator_name(node.func)
        if isinstance(node, py_ast.Attribute):
            return node.attr
        if isinstance(node, py_ast.Name):
            return node.id
        return ""

    result: dict[str, str] = {}
    for function in (
        node
        for node in py_ast.walk(module)
        if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef))
        and any(decorator_name(item) == "fixture" for item in node.decorator_list)
    ):
        snippet = py_ast.get_source_segment(source, function) or ""
        if type_name := _python_function_return_type(snippet):
            result[function.name] = type_name
    return result


def _python_attribute_uses(body: str) -> set[tuple[str, str, str, int]]:
    """Return simple receiver attribute reads/writes from one callable."""
    try:
        module = py_ast.parse(textwrap.dedent(body))
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return set()
    function = next(
        (node for node in module.body if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef))),
        None,
    )
    if function is None:
        return set()
    uses: set[tuple[str, str, str, int]] = set()
    for node in _python_body_nodes(function):
        if not isinstance(node, py_ast.Attribute) or not isinstance(node.value, py_ast.Name):
            continue
        relation = "writes" if isinstance(node.ctx, (py_ast.Store, py_ast.Del)) else "reads"
        uses.add((node.value.id, node.attr, relation, int(getattr(node, "lineno", 0))))
    return uses


def _python_assignment_names(target: py_ast.AST | None) -> set[str]:
    if isinstance(target, py_ast.Name):
        return {target.id}
    if isinstance(target, (py_ast.Tuple, py_ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(_python_assignment_names(item))
        return names
    return set()


def _python_attribute_path(value: py_ast.AST | None) -> tuple[str, tuple[str, ...]] | None:
    fields: list[str] = []
    cursor = value
    while isinstance(cursor, py_ast.Attribute):
        fields.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, py_ast.Name) or not fields:
        return None
    return cursor.id, tuple(reversed(fields))


def _python_type_solution(
    body: str,
    *,
    field_types: Mapping[tuple[str, str], str | TypeFact] | None = None,
    owner: str = "",
    initial_types: Mapping[str, str] | None = None,
    initial_facts: Mapping[str, TypeFact] | None = None,
    call_return_facts: Mapping[str, TypeFact] | None = None,
    max_attribute_depth: int = DEFAULT_PYTHON_ATTRIBUTE_DEPTH,
) -> TypeSolution:
    """Solve local Python type facts with a bounded monotone worklist."""
    try:
        module = py_ast.parse(textwrap.dedent(body))
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return TypeSolution({}, ())
    function = next(
        (node for node in module.body if isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef))),
        None,
    )
    if function is None:
        return TypeSolution({}, ())

    seeds: list[tuple[str, str, Evidence]] = []
    obligations: list[TypeObligation] = []
    fields = dict(field_types or {})

    for name, type_name in sorted((initial_types or {}).items()):
        if type_name:
            seeds.append((name, type_name, Evidence("module_or_import", name)))
    for name, fact in sorted((initial_facts or {}).items()):
        evidence_items = fact.evidence or (Evidence("module_or_import", name),)
        for type_name in sorted(fact.types):
            seeds.extend((name, type_name, evidence) for evidence in evidence_items)
    if owner:
        seeds.extend(
            (
                ("self", owner, Evidence("enclosing_owner", owner)),
                ("cls", owner, Evidence("enclosing_owner", owner)),
            )
        )

    arguments = (
        list(function.args.posonlyargs)
        + list(function.args.args)
        + list(function.args.kwonlyargs)
        + ([function.args.vararg] if function.args.vararg else [])
        + ([function.args.kwarg] if function.args.kwarg else [])
    )
    for argument in arguments:
        if type_name := _python_type_name(argument.annotation):
            seeds.append((argument.arg, type_name, Evidence("annotation", argument.arg)))

    def add_value(target: str, value: py_ast.AST | None, provenance: str) -> None:
        if not target or value is None:
            return
        if isinstance(value, py_ast.Name):
            obligations.append(TypeObligation(target, value.id, (), provenance))
            return
        if path := _python_attribute_path(value):
            obligations.append(TypeObligation(target, path[0], path[1], provenance))
            return
        if type_name := _python_value_type(value):
            seeds.append((target, type_name, Evidence(provenance, target)))
            return
        if (
            isinstance(value, py_ast.Call)
            and isinstance(value.func, py_ast.Name)
            and (return_fact := (call_return_facts or {}).get(value.func.id))
            and (return_type := return_fact.concrete)
        ):
            return_evidence = return_fact.evidence or (
                Evidence("return_type", value.func.id),
            )
            seeds.extend((target, return_type, evidence) for evidence in return_evidence)
            seeds.append((target, return_type, Evidence(provenance, target)))

    for node in _python_body_nodes(function):
        if isinstance(node, py_ast.Attribute) and (path := _python_attribute_path(node)):
            expression = ".".join((path[0], *path[1]))
            obligations.append(TypeObligation(expression, path[0], path[1], "attribute_expression"))
        if isinstance(node, py_ast.AnnAssign) and isinstance(node.target, py_ast.Name):
            if type_name := _python_type_name(node.annotation):
                seeds.append((node.target.id, type_name, Evidence("annotation", node.target.id)))
            add_value(node.target.id, node.value, "annotated_assignment")
        elif isinstance(node, (py_ast.Assign, py_ast.NamedExpr)):
            targets = node.targets if isinstance(node, py_ast.Assign) else [node.target]
            for target in targets:
                for name in _python_assignment_names(target):
                    add_value(name, node.value, "assignment")

    return solve_type_obligations(
        seeds,
        obligations,
        fields,
        max_attribute_depth=max_attribute_depth,
    )


def _python_local_types(
    body: str,
    *,
    field_types: Mapping[tuple[str, str], str | TypeFact] | None = None,
    owner: str = "",
    initial_types: Mapping[str, str] | None = None,
    initial_facts: Mapping[str, TypeFact] | None = None,
    call_return_facts: Mapping[str, TypeFact] | None = None,
    max_attribute_depth: int = DEFAULT_PYTHON_ATTRIBUTE_DEPTH,
) -> dict[str, str]:
    """Project concrete local receiver types from the bounded fact solution.

    Unknown and ambiguous facts are deliberately omitted. Callers that need
    diagnostics can inspect :func:`_python_type_solution`.
    """
    return _python_type_solution(
        body,
        field_types=field_types,
        owner=owner,
        initial_types=initial_types,
        initial_facts=initial_facts,
        call_return_facts=call_return_facts,
        max_attribute_depth=max_attribute_depth,
    ).concrete_types


def _python_module_global_types(source: str) -> dict[str, str]:
    """Return stable, explicitly annotated module-level bindings."""
    return {
        name: concrete
        for name, fact in _python_module_global_facts(source, "<module>").items()
        if (concrete := fact.concrete) is not None
    }


def _python_module_global_facts(
    source: str,
    source_path: str,
) -> dict[str, TypeFact]:
    """Return explicitly annotated module bindings with source provenance."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return {}
    result: dict[str, TypeFact] = {}
    for node in module.body:
        if (
            isinstance(node, py_ast.AnnAssign)
            and isinstance(node.target, py_ast.Name)
            and (type_name := _python_type_name(node.annotation))
        ):
            fact = TypeFact.from_evidence(
                type_name,
                Evidence("module_annotation", f"{source_path}:{node.lineno}"),
            )
            result[node.target.id] = result.get(node.target.id, TypeFact()).join(fact)
    return result


def _python_imported_global_types(
    source: str,
    project_globals: Mapping[tuple[str, str], str],
) -> dict[str, str]:
    """Map local import bindings to unambiguous project-global type facts."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return {}
    result: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, py_ast.ImportFrom) or not node.module:
            continue
        module_stem = node.module.rsplit(".", 1)[-1]
        for alias in node.names:
            if type_name := project_globals.get((module_stem, alias.name), ""):
                result[alias.asname or alias.name] = type_name
    return result


def _python_imported_global_facts(
    source: str,
    project_globals: Mapping[tuple[str, str], TypeFact],
) -> dict[str, TypeFact]:
    """Map local imports to project-global facts without dropping ambiguity."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return {}
    result: dict[str, TypeFact] = {}
    for node in module.body:
        if not isinstance(node, py_ast.ImportFrom) or not node.module:
            continue
        module_stem = node.module.rsplit(".", 1)[-1]
        for alias in node.names:
            fact = project_globals.get((module_stem, alias.name), TypeFact())
            if fact.state is not TypeState.UNKNOWN:
                result[alias.asname or alias.name] = fact
    return result


def _python_module_return_facts(
    source: str,
    source_path: str,
) -> dict[str, TypeFact]:
    """Return source-located facts for module-level callable return types."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return {}
    result: dict[str, TypeFact] = {}
    for node in module.body:
        if not isinstance(node, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)):
            continue
        # Project receiver inference needs annotations and direct concrete
        # return expressions. It deliberately does not launch a second local
        # analysis for every callable: the module AST is already available,
        # and re-parsing every function caused superlinear scan overhead.
        if not (type_name := _python_function_node_return_type(node, {})):
            continue
        fact = TypeFact.from_evidence(
            type_name,
            Evidence("function_return", f"{source_path}:{node.lineno}"),
        )
        result[node.name] = result.get(node.name, TypeFact()).join(fact)
    return result


def _python_imported_return_facts(
    source: str,
    project_returns: Mapping[tuple[str, str], TypeFact],
) -> dict[str, TypeFact]:
    """Map local imports to return facts from the named project module."""
    try:
        module = py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return {}
    result: dict[str, TypeFact] = {}
    for node in module.body:
        if not isinstance(node, py_ast.ImportFrom) or not node.module:
            continue
        module_stem = node.module.rsplit(".", 1)[-1]
        for alias in node.names:
            fact = project_returns.get((module_stem, alias.name), TypeFact())
            if fact.state is not TypeState.UNKNOWN:
                result[alias.asname or alias.name] = fact
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
    except (IndentationError, SyntaxError, ValueError, RecursionError):
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
