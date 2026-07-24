"""C++ receiver-type inference for member-call resolution.

C++ member calls are detected (the receiver rides the `argument` field of a
`field_expression`), but the edge builder had no local-type inference for C++,
so a receiver like `local` / `ptr` never acquired a type. This recovers the
common declaration shapes -- values, pointers, references, `new` expressions,
and parameters -- so `local.method()`, `ptr->method()`, and `this->method()`
resolve to their owning class. Pointer/reference decoration and `const` are
stripped; templates and namespaces reduce to the bare class name.

Class fields need a second scope-aware pass because an inline method's syntax
range does not include declarations in the surrounding class.  The field pass
only considers semicolon statements at class-body depth zero, so method locals
cannot leak into the enclosing receiver environment.
"""
from __future__ import annotations

import re

_NON_NOMINAL = frozenset({
    "void", "bool", "char", "short", "int", "long", "float", "double",
    "unsigned", "signed", "size_t", "auto", "string", "wstring", "nullptr_t",
    "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t", "uint16_t",
    "uint32_t", "uint64_t", "const", "static", "constexpr", "return",
})

_IDENT = r"[A-Za-z_]\w*"
# A type expression: optional const, namespaced name, optional template args.
_TYPE = r"(?:const\s+)?[A-Za-z_][\w:]*(?:<[^;=(){}\n]*>)?"
# Pointer/reference decoration that may sit between the type and the name.
_DECOR = r"[\s*&]+"


def _nominal(type_expr: str) -> str:
    """Reduce a C++ type expression to a bare class name, or "" if none."""
    candidate = type_expr.strip()
    candidate = re.sub(r"\bconst\b", "", candidate).strip()
    candidate = candidate.split("<", 1)[0]          # drop template args
    candidate = candidate.replace("*", "").replace("&", "").strip()
    candidate = candidate.split("::")[-1].strip()   # drop namespace
    if not candidate or candidate in _NON_NOMINAL:
        return ""
    if not candidate[:1].isupper():                  # primitives/locals are lower
        return ""
    if len(candidate) == 1:                          # a lone `T` is a template param
        return ""
    return candidate


# `Foo x = new Foo(...)` / `Foo* p = new Foo()` / `auto x = new Foo()`.
_NEW_EXPRESSION = re.compile(
    rf"\b(?:auto|{_TYPE}){_DECOR}?({_IDENT})\s*=\s*new\s+([A-Za-z_][\w:]*)"
)
# `Foo x;` / `Foo* p;` / `Foo& r = ...` -- a declared nominal type.
_DECL = re.compile(rf"\b({_TYPE}){_DECOR}({_IDENT})\s*[=;]")
_CLASS = re.compile(rf"\b(?:class|struct)\s+({_IDENT})(?:\s+final)?[^;{{]*{{")
_FIELD = re.compile(
    rf"^(?:(?:static|mutable|constexpr|const|volatile|inline)\s+)*"
    rf"({_TYPE}){_DECOR}({_IDENT})\s*(?:=[^;]*)?;$"
)


def _matching_brace(text: str, opening: int) -> int:
    """Matching class brace while ignoring comments and quoted literals."""

    depth = 0
    i = opening
    quote = ""
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = ""
            i += 1
            continue
        if char in {'"', "'"}:
            quote = char
            i += 1
            continue
        if char == "/" and nxt == "/":
            newline = text.find("\n", i + 2)
            i = len(text) if newline == -1 else newline + 1
            continue
        if char == "/" and nxt == "*":
            close = text.find("*/", i + 2)
            i = len(text) if close == -1 else close + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _top_level_statements(body: str) -> list[str]:
    statements: list[str] = []
    start = 0
    depth = 0
    for i, char in enumerate(body):
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                start = i + 1
        elif char == ";" and depth == 0:
            statements.append(body[start:i + 1].strip())
            start = i + 1
    return statements


def cpp_class_field_types(source: str) -> dict[tuple[str, str], str]:
    """Nominal field types keyed by ``(class, field)``.

    This intentionally handles the common declaration contract, not arbitrary
    C++ declarators. Unknown/ambiguous shapes remain unresolved rather than
    attaching a confident call edge to the wrong owner.
    """

    result: dict[tuple[str, str], str] = {}
    for match in _CLASS.finditer(source):
        owner = match.group(1)
        opening = source.find("{", match.start(), match.end())
        closing = _matching_brace(source, opening)
        if opening == -1 or closing == -1:
            continue
        for raw in _top_level_statements(source[opening + 1:closing]):
            statement = re.sub(
                r"^(?:(?:public|private|protected)\s*:\s*)+",
                "",
                re.sub(r"\s+", " ", raw).strip(),
            )
            if "(" in statement:
                continue
            field = _FIELD.match(statement)
            if field and (nominal := _nominal(field.group(1))):
                result[(owner, field.group(2))] = nominal
    return result


def _param_types(signature: str) -> dict[str, str]:
    """`(Foo x, Bar* p)` parameter types from a method signature."""
    result: dict[str, str] = {}
    open_paren = signature.find("(")
    if open_paren == -1:
        return result
    close = signature.rfind(")")
    params = signature[open_paren + 1 : close if close > open_paren else len(signature)]
    for part in params.split(","):
        piece = part.strip()
        if not piece:
            continue
        # Split off a default value; the name is the last identifier before it.
        piece = piece.split("=", 1)[0].strip()
        match = re.match(rf"^({_TYPE}){_DECOR}({_IDENT})$", piece)
        if match and (nominal := _nominal(match.group(1))):
            result.setdefault(match.group(2), nominal)
    return result


def cpp_local_types(body: str) -> dict[str, str]:
    """Receiver types inferable from one C++ function body."""
    result: dict[str, str] = {}
    signature = body.split("{", 1)[0]
    result.update(_param_types(signature))
    for match in _NEW_EXPRESSION.finditer(body):
        if nominal := _nominal(match.group(2)):
            result.setdefault(match.group(1), nominal)
    for match in _DECL.finditer(body):
        if nominal := _nominal(match.group(1)):
            result.setdefault(match.group(2), nominal)
    return result
