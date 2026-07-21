"""TypeScript/JavaScript receiver typing.

Receiver types were only ever inferred for Rust and Python, so every
TypeScript member call fell through with no type at all -- measured on a
mixed repo, *not one* TypeScript method had a known caller while the Python
half resolved normally. Extraction was never the problem there: classes,
methods and interfaces are all recovered. The call graph among them was
empty purely because nothing read the annotations.

TypeScript states its types in the same places Rust does -- parameters and
declarations -- so this is a lookup rather than an inference. The JavaScript
subset (no annotations) still benefits from `new` expressions, which is the
one place untyped JS names a class outright.
"""

from __future__ import annotations

import re

# `name: Type`, tolerating `?`, access modifiers, and generic/array suffixes.
_PARAM_ANNOTATION = re.compile(
    r"(?:^|[,(])\s*(?:readonly\s+|public\s+|private\s+|protected\s+)?"
    r"([A-Za-z_$][\w$]*)\s*\??\s*:\s*([A-Za-z_$][\w$.]*)"
)
# `const x: Type`, `let x: Type`, `var x: Type`
_DECL_ANNOTATION = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$.]*)"
)
# `const x = new Type(...)` -- the only class name an untyped JS binding gives.
_NEW_EXPRESSION = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?new\s+([A-Z][\w$.]*)"
)
# `x as Type` / `<Type>x` assertions on a declaration.
_AS_ASSERTION = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[^;\n]*?\bas\s+([A-Z][\w$.]*)"
)

# Built-in and structural types that name nothing in the graph. Binding a
# receiver to one of these cannot produce an edge and only adds noise to the
# unresolved telemetry.
_NON_NOMINAL = frozenset({
    "string", "number", "boolean", "bigint", "symbol", "object", "any",
    "unknown", "never", "void", "null", "undefined", "this", "Function",
    "Array", "Promise", "Record", "Map", "Set", "Date", "Error", "RegExp",
})


def _nominal(type_name: str) -> str:
    """Reduce a type expression to a nameable owner, or "" if there is none."""
    # `ns.Type` -> `Type`; generics were already excluded by the patterns.
    candidate = type_name.split(".")[-1].strip()
    if not candidate or candidate in _NON_NOMINAL:
        return ""
    # A lone uppercase letter is a generic parameter (`T`), not a type.
    if len(candidate) == 1 and candidate.isupper():
        return ""
    return candidate


def _ts_local_types(body: str) -> dict[str, str]:
    """Receiver types declared in one TypeScript/JavaScript function body."""
    result: dict[str, str] = {}
    signature = body.split("{", 1)[0]

    for match in _PARAM_ANNOTATION.finditer(signature):
        if nominal := _nominal(match.group(2)):
            result.setdefault(match.group(1), nominal)
    for pattern in (_DECL_ANNOTATION, _NEW_EXPRESSION, _AS_ASSERTION):
        for match in pattern.finditer(body):
            if nominal := _nominal(match.group(2)):
                result.setdefault(match.group(1), nominal)
    return result


def _ts_class_field_types(source: str) -> dict[tuple[str, str], str]:
    """`this.field` types from class property declarations.

    Only annotated or `new`-initialized properties are claimed; an untyped
    assignment says nothing about the field's type.
    """
    result: dict[tuple[str, str], str] = {}
    for class_match in re.finditer(r"\bclass\s+([A-Z][\w$]*)[^{]*\{", source):
        owner = class_match.group(1)
        body = source[class_match.end():]
        # Bounded window: the next class declaration ends this one's scope for
        # the purposes of this shallow scan.
        next_class = re.search(r"\bclass\s+[A-Z][\w$]*", body)
        if next_class:
            body = body[: next_class.start()]
        for field, type_name in re.findall(
            r"(?:readonly\s+|public\s+|private\s+|protected\s+)?"
            r"([A-Za-z_$][\w$]*)\s*\??\s*:\s*([A-Za-z_$][\w$.]*)\s*[;=]",
            body,
        ):
            if nominal := _nominal(type_name):
                result.setdefault((owner, field), nominal)
        for field, type_name in re.findall(
            r"this\.([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?new\s+([A-Z][\w$.]*)", body
        ):
            if nominal := _nominal(type_name):
                result.setdefault((owner, field), nominal)
    return result
