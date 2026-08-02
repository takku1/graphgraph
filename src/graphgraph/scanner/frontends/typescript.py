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
# `new Engine()` and `new mod.Engine()` alike. The constructor may be reached
# through a namespace -- `var m = require('./dep'); new m.Engine()` is how
# CommonJS names an imported class -- and `_nominal` already reduces `ns.Type`
# to `Type`. Requiring the *whole* path to start uppercase missed that form
# entirely, though it states the receiver's type just as explicitly as the bare
# one. The final segment must still look like a type, so `new makeThing()`
# stays out.
_NEW_EXPRESSION = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?new\s+((?:[A-Za-z_$][\w$]*\.)*[A-Z][\w$]*)"
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


_JS_RETURN_NEW = re.compile(r"\breturn\s+new\s+([A-Z][\w$]*)")
_JS_RETURN_LOCAL = re.compile(r"\breturn\s+([A-Za-z_$][\w$]*)\s*(?:[;}]|$)", re.MULTILINE)
# `const x = factory()` / `let y = await make()` -- a local bound to a call.
_JS_LOCAL_CALL = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:(?:module\.)?exports\s*=\s*)?(?:await\s+)?([A-Za-z_$][\w$]*)\s*\("
)
_THIS_ALIAS = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*this\b"
)
_OBJECT_ASSIGN = re.compile(
    r"\bObject\.assign\s*\(\s*([A-Za-z_$][\w$]*)\s*,\s*([A-Za-z_$][\w$]*)"
)
_DEFINE_PROPERTY = re.compile(
    r"\bObject\.defineProperty\s*\(\s*([A-Za-z_$][\w$]*)\s*,\s*"
    r"['\"]([A-Za-z_$][\w$]*)['\"]\s*,\s*\{(?P<body>.*?)\}\s*\)",
    re.DOTALL,
)


def _ts_return_type_from_body(
    body: str,
    local_types: dict[str, str] | None = None,
) -> str | None:
    """Infer a function's return type from ``return new X()`` (the factory shape).

    JS has no return annotations, so a body returning exactly one concrete class
    is the only receiver evidence a factory offers. Several distinct classes are
    ambiguous and yield nothing -- the single-concrete-type rule the Rust
    return-type join already uses.
    """
    types = set(_JS_RETURN_NEW.findall(body))
    if local_types:
        types.update(
            local_types[name]
            for name in _JS_RETURN_LOCAL.findall(body)
            if name in local_types
        )
    if len(types) == 1:
        candidate = next(iter(types))
        if "::" in candidate:
            return candidate
        return candidate if _nominal(candidate) else None
    return None


def _ts_local_call_return_types(body: str, return_types: dict[str, str]) -> dict[str, str]:
    """Bind ``const x = factory()`` locals to the factory's known return type.

    Recovers the dominant unresolved JS receiver shape (``named_local``): a local
    assigned from a call whose return type the repo-wide join has inferred.
    """
    inferred: dict[str, str] = {}
    for match in _JS_LOCAL_CALL.finditer(body):
        return_type = return_types.get(match.group(2), "")
        if return_type:
            inferred.setdefault(match.group(1), return_type)
    return inferred


def _ts_this_aliases(body: str) -> frozenset[str]:
    """Bindings proven to alias the current structural/class instance."""
    return frozenset(_THIS_ALIAS.findall(body))


def _ts_property_copy_types(
    body: str,
    source_types: dict[str, str],
    helper_aliases: frozenset[str],
) -> dict[str, str]:
    """Type property-copy targets from proven sources and helper semantics."""
    pairs = list(_OBJECT_ASSIGN.findall(body))
    for helper in helper_aliases:
        pattern = re.compile(
            rf"\b{re.escape(helper)}\s*\(\s*([A-Za-z_$][\w$]*)\s*,\s*([A-Za-z_$][\w$]*)"
        )
        pairs.extend(pattern.findall(body))
    inferred: dict[str, str] = {}
    for target, source in pairs:
        if source_type := source_types.get(source, ""):
            prior = inferred.get(target)
            if prior is None:
                inferred[target] = source_type
            elif prior != source_type:
                # Conflicting copy sources are ambiguous receiver evidence.
                inferred.pop(target, None)
    return inferred


_JS_PARAM_LIST = re.compile(r"\(([^)]*)\)")


def _ts_parameter_names(body: str) -> set[str]:
    """Bare parameter names of the outermost callable in *body*.

    `_ts_local_types` only sees *annotated* parameters, so in plain JavaScript a
    parameter is invisible. That matters when a name is also a module-level
    object: `app.mount = function mount(app) { app.send() }` shadows the object,
    and binding the outer one there would fabricate an edge to a method the
    argument may not have.
    """
    signature = body.split("{", 1)[0]
    match = _JS_PARAM_LIST.search(signature)
    if not match:
        return set()
    names: set[str] = set()
    for part in match.group(1).split(","):
        token = part.strip().split(":", 1)[0].split("=", 1)[0].strip().lstrip(". ")
        if token.isidentifier():
            names.add(token)
    return names


def _ts_ordered_parameter_names(body: str) -> tuple[str, ...]:
    """Ordered bare parameters for protocol-aware callback binding."""
    signature = body.split("{", 1)[0]
    match = _JS_PARAM_LIST.search(signature)
    if not match:
        return ()
    names: list[str] = []
    for part in match.group(1).split(","):
        token = part.strip().split(":", 1)[0].split("=", 1)[0].strip().lstrip(". ")
        if token.isidentifier():
            names.append(token)
    return tuple(names)


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
    for match in _DEFINE_PROPERTY.finditer(source):
        types = {
            nominal
            for raw in re.findall(r"\bnew\s+([A-Z][\w$.]*)", match.group("body"))
            if (nominal := _nominal(raw))
        }
        if len(types) == 1:
            result[(match.group(1), match.group(2))] = next(iter(types))
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
