"""JavaScript/TypeScript callable idioms the declaration walk misses."""

from __future__ import annotations

from typing import Any, Callable

_FUNCTION_VALUE_TYPES = frozenset(
    {
        "function_expression",
        "arrow_function",
        "function",
        "generator_function",
        "generator_function_declaration",
    }
)


def _text(node: Any) -> str:
    raw = getattr(node, "text", b"")
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _is_function_value(node: Any) -> bool:
    return node is not None and node.type in _FUNCTION_VALUE_TYPES


def _member_leaf_name(left: Any) -> str:
    """Return the property leaf from a callable binding or call expression."""
    if left.type in {
        "identifier",
        "property_identifier",
        "shorthand_property_identifier",
    }:
        return _text(left)
    if left.type in {"member_expression", "subscript_expression"}:
        prop = left.child_by_field_name("property")
        return _text(prop) if prop is not None else ""
    return ""


def _declarator_function(node: Any) -> tuple[str, str] | None:
    if not _is_function_value(node.child_by_field_name("value")):
        return None
    name = node.child_by_field_name("name")
    if name is None or name.type != "identifier":
        return None
    return (_text(name), "function")


def _field_function(node: Any) -> tuple[str, str] | None:
    if not _is_function_value(node.child_by_field_name("value")):
        return None
    name = node.child_by_field_name("name")
    return (_text(name), "method") if name is not None else None


def _assignment_function(node: Any) -> tuple[str, str] | None:
    """Recognize function values assigned to variables or member properties."""
    if not _is_function_value(node.child_by_field_name("right")):
        return None
    left = node.child_by_field_name("left")
    if left is None:
        return None
    if left.type == "identifier":
        return (_text(left), "function")
    if left.type in {"member_expression", "subscript_expression"}:
        name = _member_leaf_name(left)
        obj = left.child_by_field_name("object")
        if not name or name == "exports" or (
            obj is not None and _text(obj) == "module"
        ):
            return None
        return (name, "method")
    return None


_JS_FUNCTION_MATCHERS: dict[
    str, Callable[[Any], tuple[str, str] | None]
] = {
    "variable_declarator": _declarator_function,
    "public_field_definition": _field_function,
    "field_definition": _field_function,
    "assignment_expression": _assignment_function,
}


def js_function_definition(node: Any) -> tuple[str, str] | None:
    """Return ``(name, kind)`` for a function-valued binding, else ``None``."""
    matcher = _JS_FUNCTION_MATCHERS.get(node.type)
    return matcher(node) if matcher is not None else None


def js_definition_facts(node: Any) -> tuple[str, ...]:
    """Return categorical provenance for one recognized JS callable binding."""
    if node.type == "variable_declarator":
        return ("javascript_definition:variable_callable",)
    if node.type in {"public_field_definition", "field_definition"}:
        return ("javascript_definition:class_field",)
    if node.type != "assignment_expression":
        return ()
    left = node.child_by_field_name("left")
    if left is None or left.type not in {
        "member_expression",
        "subscript_expression",
    }:
        return ("javascript_definition:variable_callable",)
    owner = js_definition_owner(node)
    binding = _text(left)
    if ".prototype." in binding:
        return (
            "javascript_definition:prototype_assignment",
            f"javascript_owner:{owner}",
            *(
                ("javascript_this:assigned_owner",)
                if js_definition_binds_this(node)
                else ()
            ),
        )
    return (
        "javascript_definition:property_assignment",
        f"javascript_owner:{owner}",
        *(
            ("javascript_this:assigned_owner",)
            if js_definition_binds_this(node)
            else ()
        ),
    )


def js_definition_owner(node: Any) -> str:
    """Structural owner of a function-valued member assignment.

    ``res.send = function`` and ``Store.prototype.save = function`` define
    methods on concrete object namespaces even in annotation-free JavaScript.
    The owner comes from the assignment target itself; no name-only inference
    is involved.
    """
    if node.type != "assignment_expression":
        return ""
    left = node.child_by_field_name("left")
    if left is None or left.type not in {
        "member_expression",
        "subscript_expression",
    }:
        return ""
    binding = _text(left)
    if ".prototype." in binding:
        return binding.split(".prototype.", 1)[0]
    return binding.rsplit(".", 1)[0] if "." in binding else ""


def js_definition_binds_this(node: Any) -> bool:
    """Whether invocation through the assigned member binds ``this`` to it."""
    if node.type != "assignment_expression":
        return False
    value = node.child_by_field_name("right")
    return value is not None and value.type != "arrow_function"


def js_callback_definition(
    node: Any,
) -> tuple[str, str, tuple[str, ...]] | None:
    """Ground an inline function/arrow argument as a stable callback symbol."""
    if not _is_function_value(node):
        return None
    parent = getattr(node, "parent", None)
    call = getattr(parent, "parent", None)
    if parent is None or parent.type != "arguments" or call is None:
        return None
    if call.type != "call_expression":
        return None
    function = call.child_by_field_name("function")
    if function is None:
        return None
    callee = _member_leaf_name(function)
    if not callee:
        return None
    named = node.child_by_field_name("name")
    line = int(node.start_point[0]) + 1
    column = int(node.start_point[1]) + 1
    name = (
        _text(named)
        if named is not None
        else f"{callee}_callback_L{line}C{column}"
    )
    facts = (
        "javascript_definition:callback",
        f"callback_registered_by:{callee}",
    )
    if callee in {"context", "describe", "it", "specify", "test"}:
        facts += ("role:test",)
    return name, "function", facts
