"""C# receiver-type inference for member-call resolution.

C# member calls resolved 0 / 6,454 (graybox cycle 8) for a single reason: the
edge builder had per-language local-variable type inference for TS, Rust, and
Python and fell through to an empty map for everything else, so a C# receiver
never acquired a type and every `x.Method()` classified as unknown/external.
This recovers the common, low-ambiguity cases -- `new` expressions, declared
locals, and parameters -- the same shapes the TS extractor already claims.
"""
from __future__ import annotations

import re

# Primitives, aliases, and keyword-like types that name no graph symbol.
_NON_NOMINAL = frozenset({
    "var", "void", "object", "dynamic", "string", "String", "bool", "Boolean",
    "byte", "sbyte", "char", "short", "ushort", "int", "Int32", "uint", "long",
    "Int64", "ulong", "float", "Single", "double", "Double", "decimal",
    "nint", "nuint", "Object",
})

_IDENT = r"[A-Za-z_]\w*"
# A nominal type reference: optional namespace, optional generic args, optional
# array/nullable markers. Kept coarse; `_nominal` does the final reduction.
_TYPE = r"[A-Za-z_][\w.]*(?:<[^;=(){}\n]*>)?(?:\[\])?\??"


def _nominal(type_expr: str) -> str:
    """Reduce a type expression to a bare owner name, or "" if it names none."""
    candidate = type_expr.strip().rstrip("?")
    candidate = candidate.split("<", 1)[0]        # drop generic args
    candidate = candidate.replace("[]", "")        # drop array marker
    candidate = candidate.split(".")[-1].strip()   # drop namespace
    if not candidate or candidate in _NON_NOMINAL:
        return ""
    if not candidate[:1].isupper():                # locals/primitives are lower
        return ""
    if len(candidate) == 1:                        # a lone `T` is a generic param
        return ""
    return candidate


# `var x = new Foo(...)` / `Foo x = new Foo(...)` -- the `new` names the type.
_NEW_EXPRESSION = re.compile(
    rf"\b(?:var|{_TYPE})\s+({_IDENT})\s*=\s*new\s+([A-Za-z_][\w.]*)"
)
# `Foo x = ...;` or `Foo x;` -- a declared nominal type (not `var`).
_DECL_ANNOTATION = re.compile(rf"\b([A-Z][\w.<>\[\], ]*?)\s+({_IDENT})\s*[=;]")


def _param_types(signature: str) -> dict[str, str]:
    """`(Foo x, Bar y)` parameter types from a method signature."""
    result: dict[str, str] = {}
    open_paren = signature.find("(")
    if open_paren == -1:
        return result
    params = signature[open_paren + 1 : signature.rfind(")") if ")" in signature else len(signature)]
    for part in params.split(","):
        tokens = part.strip().split()
        # Strip C# parameter modifiers so `ref Foo x` still types `x`.
        while tokens and tokens[0] in {"ref", "out", "in", "params", "this", "readonly"}:
            tokens = tokens[1:]
        if len(tokens) >= 2:
            if nominal := _nominal(tokens[-2]):
                result.setdefault(tokens[-1].strip("[]"), nominal)
    return result


# Access/storage modifiers that mark a class-level field or property. A method
# body local almost never carries one, so requiring at least one modifier keeps
# the coarse (brace-unaware) field scan from mistaking a local for a field.
_FIELD_MODIFIER = (
    r"(?:public|private|protected|internal|static|readonly|const|volatile|"
    r"transient|final|sealed|virtual|override|required|init|new|extern|unsafe)"
)
# `[modifiers]+ Type name [=|;]` -- a field declaration.
_FIELD_DECL = re.compile(
    rf"(?:{_FIELD_MODIFIER}\s+)+({_TYPE})\s+({_IDENT})\s*[=;]"
)
# `[modifiers]+ Type Name { get` -- a C# auto-property.
_PROPERTY_DECL = re.compile(
    rf"(?:{_FIELD_MODIFIER}\s+)+({_TYPE})\s+({_IDENT})\s*\{{\s*get"
)
_TYPE_DECL = re.compile(r"\b(?:class|struct|record|interface)\s+([A-Z]\w*)")


def csharp_class_field_types(source: str) -> dict[tuple[str, str], str]:
    """`(owner, field) -> type` for C#/Java class fields and auto-properties.

    Field types live at the class level, so a `_repo.Method()` receiver -- the
    dominant real member-call shape -- is invisible to the per-method-body local
    inference. This recovers the declared type of nominal fields/properties.
    The scan is brace-unaware (bounded to the window before the next type
    declaration), so it leans on the modifier requirement to avoid typing method
    locals as fields; a genuine local of the same name still wins downstream,
    because the edge builder merges these under ``setdefault``.
    """
    result: dict[tuple[str, str], str] = {}
    for type_match in _TYPE_DECL.finditer(source):
        owner = type_match.group(1)
        body = source[type_match.end():]
        next_type = _TYPE_DECL.search(body)
        if next_type:
            body = body[: next_type.start()]
        for pattern in (_FIELD_DECL, _PROPERTY_DECL):
            for type_expr, name in pattern.findall(body):
                if nominal := _nominal(type_expr):
                    result.setdefault((owner, name), nominal)
    return result


def csharp_local_types(body: str) -> dict[str, str]:
    """Receiver types inferable from one C# method body."""
    result: dict[str, str] = {}
    signature = body.split("{", 1)[0]
    result.update(_param_types(signature))
    for match in _NEW_EXPRESSION.finditer(body):
        if nominal := _nominal(match.group(2)):
            result.setdefault(match.group(1), nominal)
    for match in _DECL_ANNOTATION.finditer(body):
        if nominal := _nominal(match.group(1)):
            result.setdefault(match.group(2), nominal)
    return result
