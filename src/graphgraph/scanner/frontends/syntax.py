"""Generic tree-sitter traversal: definition collection, call sites, and symbol resolution."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ...graph.core import Edge, Node
from ..ast import _lang_family
from .javascript import (
    js_callback_definition,
    js_definition_facts,
    js_definition_owner,
    js_function_definition,
)
from .model import (
    SourceFile,
    _CallSite,
    _TsDef,
)

# Functions in JS/TS are usually assigned, not declared; see javascript.py.
_JS_DEFINITION_SUFFIXES = frozenset(
    {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
    }
)


def _definition_summary(text: str, line: int) -> str:
    lines = text.splitlines()
    excerpt = lines[line - 1].strip() if 0 < line <= len(lines) else ""
    excerpt = re.sub(r"\s+", " ", excerpt)[:160]
    return f"L{line} {excerpt}".rstrip()


def _definition_impl_qualifier(definition: _TsDef) -> str:
    if definition.kind != "method" or not definition.owner:
        return ""
    trait_name, type_name = definition.extra if len(definition.extra) == 2 else ("", definition.owner)
    return f"{trait_name}_for_{type_name}" if trait_name else type_name


def _definition_qualified_name(definition: _TsDef) -> str:
    qualifier = _definition_impl_qualifier(definition)
    return f"{qualifier}::{definition.name}" if qualifier else ""


def _definition_node_id(source: SourceFile, definition: _TsDef) -> str:
    qualifier = _definition_impl_qualifier(definition)
    if qualifier:
        return f"{source.file_node_id}__{qualifier}__{definition.name}"
    return f"{source.file_node_id}__{definition.name}"


_DEF_TYPES = {
    "class_definition": "class",
    # C++ (tree-sitter-cpp). Inline function_definition nodes nested inside
    # these types are converted to owned methods by
    # _attach_lexical_method_owners below.
    "class_specifier": "class",
    "struct_specifier": "struct",
    "function_definition": "function",
    "function_item": "function",
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "function_signature_item": "method",
    "function_declaration": "function",
    "method_declaration": "method",
    "method_definition": "method",
    "class_declaration": "class",
    "class": "class",
    "type_declaration": "type",
    "interface_declaration": "interface",
    # C# (tree-sitter c_sharp)
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "constructor_declaration": "method",
    "record_declaration": "class",
    "record_struct_declaration": "struct",
    # Ruby
    "method": "method",
    "singleton_method": "method",
    "module": "class",
    # PHP / Scala traits
    "trait_declaration": "trait",
    "trait_definition": "trait",
    # Kotlin / Scala objects and Scala class/def (function_definition/class_definition
    # already mapped above)
    "object_declaration": "class",
    "object_definition": "class",
    # Swift protocols
    "protocol_declaration": "interface",
}

_NAME_NODE_TYPES = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "shorthand_property_identifier",
    "simple_identifier",  # Kotlin function/property names
    "name",  # PHP bare function/method names
    "constant",  # Ruby class/module names
}

DEFINITION_NODE_TYPES = MappingProxyType(_DEF_TYPES)

NAME_NODE_TYPES = frozenset(_NAME_NODE_TYPES)

_LANGUAGE_CACHE: dict[str, Any] = {}

_LANGUAGE_LOAD_ERRORS: dict[str, str] = {}

_PARSER_CACHE: dict[str, Any] = {}

_PARSER_LOAD_ERRORS: dict[str, str] = {}


def _go_receiver_owner(node: Any, text: bytes) -> str:
    """Owner type of a Go method: ``func (e *Engine[T]) Run()`` -> ``Engine``.

    Pointer receivers and type parameters are stripped because the owner is a
    nominal key matched against a receiver's inferred type, and `Engine`,
    `*Engine` and `Engine[T]` all name the same type for that purpose.
    """
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return ""
    for child in getattr(receiver, "named_children", ()):
        type_node = child.child_by_field_name("type") if hasattr(child, "child_by_field_name") else None
        if type_node is None:
            continue
        name = _node_text(type_node, text).strip().lstrip("*").strip()
        name = name.split("[", 1)[0].strip()
        if name:
            return name
    return ""


def _collect_defs(source: SourceFile, root: Any, text: bytes) -> list[_TsDef]:
    defs: list[_TsDef] = []
    # Hoisted out of the walk below: `Path.suffix` re-parses the path string on
    # every access, and the JS check ran for every node that is not a definition
    # -- which in a C or Rust file is nearly all of them. It cost 775,388 calls
    # on a 132-file C corpus, about 10% of that scan, to re-derive one constant.
    is_js_like = source.path.suffix.lower() in _JS_DEFINITION_SUFFIXES
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(reversed(list(getattr(node, "named_children", ()))))
        if node.type == "impl_item":
            impl = _rust_impl_def(node, text)
            if impl:
                defs.append(impl)
            continue
        kind = _DEF_TYPES.get(node.type)
        if not kind:
            # JS/TS functions are usually assigned, not declared -- recover the
            # `res.send = function` / `const f = () => ...` idioms the
            # declaration walk cannot see (javascript.py).
            if is_js_like:
                assigned = js_function_definition(node)
                callback = js_callback_definition(node)
                if assigned is not None or callback is not None:
                    if assigned is not None:
                        name, kind = assigned
                        js_facts = js_definition_facts(node)
                    else:
                        assert callback is not None
                        name, kind, js_facts = callback
                    base_facts, literal_free = _definition_facts_and_text(source, node, text)
                    defs.append(
                        _TsDef(
                            name=name,
                            kind=kind,
                            start=int(node.start_byte),
                            end=int(node.end_byte),
                            line=int(node.start_point[0]) + 1,
                            facts=(*base_facts, *js_facts),
                            extra=(),
                            owner=js_definition_owner(node),
                            return_type=_declared_return_type(node, text),
                            node=node,
                            literal_free_text=literal_free,
                        )
                    )
            continue
        name_node = _name_node(node)
        if name_node is None:
            continue
        name = _node_text(name_node, text)
        if not name:
            continue
        # Go attaches methods to a receiver rather than nesting them inside the
        # type, so the lexical owner pass below cannot see them and every Go
        # method was recorded ownerless. An ownerless method cannot be matched
        # against a typed receiver, which made `e.Run()` unresolvable even with
        # the receiver's type in hand.
        owner = (
            _go_receiver_owner(node, text)
            if node.type == "method_declaration" and source.path.suffix.lower() == ".go"
            else ""
        )
        node_facts, literal_free = _definition_facts_and_text(source, node, text)
        defs.append(
            _TsDef(
                name=name,
                kind=kind,
                start=int(node.start_byte),
                end=int(node.end_byte),
                line=int(node.start_point[0]) + 1,
                facts=node_facts,
                extra=_base_class_names(node, text),
                owner=owner,
                return_type=_declared_return_type(node, text),
                node=node,
                literal_free_text=literal_free,
            )
        )
    if source.path.suffix.lower() != ".rs":
        return _attach_lexical_method_owners(defs)
    impls = [d for d in defs if d.kind == "impl_block" and len(d.extra) == 2]
    if not impls:
        return defs
    owned: list[_TsDef] = []
    for definition in defs:
        if definition.kind not in {"function", "method"}:
            owned.append(definition)
            continue
        parents = [impl for impl in impls if impl.start < definition.start and definition.end < impl.end]
        if not parents:
            owned.append(definition)
            continue
        parent = min(parents, key=lambda item: item.end - item.start)
        owned.append(replace(definition, kind="method", owner=parent.extra[1], extra=parent.extra))
    return owned


def _base_class_names(node: Any, text: bytes) -> tuple[str, ...]:
    """Base classes named in a class declaration, when the grammar exposes them.

    A method called on a typed receiver resolves only if the method is owned by
    that exact type, so every inherited call fails without this: `app.route()`
    on a `Flask` misses because `route` lives on an ancestor. The base names sit
    in the CST the parser already built, so recovering them is a read, not an
    inference.
    """
    if _DEF_TYPES.get(node.type) != "class":
        return ()
    names: list[str] = []
    for field in ("superclasses", "superclass", "bases"):
        try:
            container = node.child_by_field_name(field)
        except Exception:
            container = None
        if container is None:
            continue
        for child in getattr(container, "named_children", ()):
            base = _node_text(child, text).strip()
            # Keep plain names; generics and keyword args (metaclass=...) are
            # not a nameable owner here.
            if base and _identifier(base) and base not in names:
                names.append(base)
        break
    return tuple(names)


def _declared_return_type(node: Any, text: bytes) -> str:
    """The return annotation, read from the parser's own field.

    Every grammar here exposes `return_type` directly, so scanning source
    text for it re-derives what the parse already computed -- and the
    heuristics that scanning needs (truncate at `{`, match after `->`) are
    what let a Python docstring leak into the result. Reading the field is
    exact, needs no per-language special-casing, and picks up TypeScript's
    `: T` form which an arrow-based regex never matched at all.
    """
    try:
        annotation = node.child_by_field_name("return_type")
    except Exception:
        return ""
    if annotation is None:
        return ""
    # TypeScript's type_annotation node includes its leading colon.
    return _node_text(annotation, text).strip().lstrip(":").strip()


# A grammar has a few dozen node types, but a walk visits millions of nodes, so
# the classification below was recomputed constantly: casefolding plus four
# substring scans, 2.2M times on a 132-file C corpus. Keyed by the type string,
# which is drawn from a fixed per-grammar vocabulary, so this stays tiny.
_NON_CODE_NODE_TYPES: dict[str, bool] = {}


def _is_non_code_node_type(child_type: str) -> bool:
    """True when a node's text is a comment or literal rather than code."""
    classified = _NON_CODE_NODE_TYPES.get(child_type)
    if classified is None:
        folded = child_type.casefold()
        classified = (
            "comment" in folded
            or "string" in folded
            or "regex" in folded
            or folded in {"char_literal", "character_literal", "heredoc_body"}
        )
        _NON_CODE_NODE_TYPES[child_type] = classified
    return classified


def _syntax_text_without_literals(node: Any, text: bytes) -> str:
    """Return a node's source with non-executable literal regions blanked."""
    start = int(node.start_byte)
    segment = bytearray(text[start : int(node.end_byte)])
    stack = list(getattr(node, "children", ()))
    while stack:
        child = stack.pop()
        if _is_non_code_node_type(str(getattr(child, "type", ""))):
            left = max(0, int(child.start_byte) - start)
            right = min(len(segment), int(child.end_byte) - start)
            segment[left:right] = b" " * max(0, right - left)
            continue
        stack.extend(getattr(child, "children", ()))
    return bytes(segment).decode("utf-8", errors="replace")


def _definition_facts(source: SourceFile, node: Any, text: bytes) -> tuple[str, ...]:
    """Project language attributes into small, queryable normalized-IR facts."""
    return _definition_facts_and_text(source, node, text)[0]


def _definition_facts_and_text(source: SourceFile, node: Any, text: bytes) -> tuple[tuple[str, ...], str]:
    """Facts plus the literal-blanked source they were derived from.

    Resolution needs that same blanked text, so returning it here means the
    descendant walk happens once per definition rather than twice.
    """
    if _DEF_TYPES.get(node.type) not in {"function", "method"}:
        return (), ""
    snippet = _syntax_text_without_literals(node, text)
    suffix = source.path.suffix.lower()
    facts: list[str] = []

    # This is an operator-level IR fact, not an inferred business claim.
    # Besides the language operators, accept only assertion APIs whose names
    # explicitly encode equality/inequality. This keeps the projection
    # portable without treating nearby words such as "same" as proof.
    equality_primitive = re.compile(
        r"(?:"
        r"==|!="
        r"|\bassert_(?:eq|ne)!\s*\("
        r"|\bassert(?:Equal|NotEqual|Equals|NotEquals)\s*\("
        r"|\bassert_(?:equal|not_equal)\s*\("
        r"|\bXCTAssert(?:Equal|NotEqual)\s*\("
        r"|\bassert\.(?:equal|notEqual|strictEqual|notStrictEqual)\s*\("
        r")"
    )
    if equality_primitive.search(snippet):
        facts.append("semantic_operator:equality")

    if suffix != ".rs":
        return tuple(facts), snippet

    prefix = _node_text_range(
        text,
        max(0, int(node.start_byte) - 256),
        int(node.start_byte),
    )
    test_attribute = r"#\s*\[\s*(?:tokio::)?test(?:\s*\([^]]*\))?\s*\]"
    if re.search(test_attribute, snippet) or re.search(test_attribute + r"\s*$", prefix):
        facts.extend(("role:test", "rust_attribute:test"))
    # Keep this implementation-level contract Rust-specific until another
    # frontend has an equally narrow collection primitive.
    if re.search(r"\b(?:BTreeSet|HashSet)\s*::\s*(?:new|default)\s*\(", snippet) and re.search(
        r"\.insert\s*\(", snippet
    ):
        facts.extend(("collection_contract:unique", "semantic_operation:deduplication"))
    return tuple(dict.fromkeys(facts)), snippet


def _attach_lexical_method_owners(defs: list[_TsDef]) -> list[_TsDef]:
    """Mark callables directly nested in a type as owned methods."""
    owner_kinds = {"class", "trait", "struct", "enum", "interface", "type"}
    owned: list[_TsDef] = []
    for definition in defs:
        if definition.kind not in {"function", "method"}:
            owned.append(definition)
            continue
        enclosing = [
            parent
            for parent in defs
            if parent is not definition and parent.start < definition.start and definition.end <= parent.end
        ]
        parent = min(enclosing, key=lambda item: item.end - item.start, default=None)
        if parent is None or parent.kind not in owner_kinds:
            owned.append(definition)
            continue
        owned.append(
            replace(
                definition,
                kind="method",
                owner=parent.name,
                extra=("", parent.name),
            )
        )
    return owned


_NESTED_NAME_PARENT_TYPES = {
    "type_declaration",
    "lexical_declaration",
    # C/C++ function_definition nests its identifier under a function_declarator
    # (e.g. `int count(void) {...}` -> function_definition > function_declarator >
    # identifier) rather than exposing a direct "name" field like Python/Rust/Java
    # do. Without this, C/C++ function extraction silently finds zero symbols.
    "function_definition",
    "declaration",
}


def _name_node(node: Any) -> Any | None:
    try:
        named = node.child_by_field_name("name")
        if named is not None:
            return named
    except Exception:
        pass
    for child in getattr(node, "named_children", ()):
        if child.type in _NAME_NODE_TYPES:
            return child
        nested = _name_node(child)
        if nested is not None and node.type in _NESTED_NAME_PARENT_TYPES:
            return nested
    return None


def _node_text(node: Any, text: bytes) -> str:
    return text[int(node.start_byte) : int(node.end_byte)].decode("utf-8", errors="replace")


def _node_text_range(text: bytes, start: int, end: int) -> str:
    return text[start:end].decode("utf-8", errors="replace")


def _rust_impl_def(node: Any, text: bytes) -> _TsDef | None:
    snippet = _node_text(node, text).split("{", 1)[0]
    m = re.search(r"\bimpl\s*(?:<[^>]*>\s*)?(?:(?P<trait>[A-Za-z_][\w:]*)\s+for\s+)?(?P<typ>[A-Za-z_][\w:]*)", snippet)
    if not m:
        return None
    trait = (m.group("trait") or "").split("::")[-1]
    typ = m.group("typ").split("::")[-1]
    return _TsDef(
        name=f"impl_{trait}_for_{typ}" if trait else f"impl_{typ}",
        kind="impl_block",
        start=int(node.start_byte),
        end=int(node.end_byte),
        line=int(node.start_point[0]) + 1,
        extra=(trait, typ),
    )


def _return_type_name(signature_or_body: str) -> str:
    names = _return_type_names(signature_or_body)
    return names[0] if names else ""


def _return_expression_head(text: str) -> str:
    """Trim a return annotation to the annotation itself.

    The caller truncates a definition at its opening brace, which bounds the
    expression for brace languages but does nothing for Python -- so a
    DOTALL match after `->` swallowed the whole function, and every
    capitalized word in the docstring became a candidate return type. On
    flask that turned `-> ft.AfterRequestCallable[t.Any]` into thirteen
    names including `Decorate`, `Therefore`, `Hello`, and `X`, the last of
    which collided with a real test class and produced a false `returns`
    edge from library code to a test fixture.

    Stops at the first `:` or `{` that closes the signature at bracket depth
    zero, so subscripts like `Dict[str, int]` are unaffected.
    """
    depth = 0
    for index, char in enumerate(text):
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth -= 1
            # A closing bracket below zero ends the parameter list we are in.
            if depth < 0:
                return text[:index]
        elif depth == 0:
            if char == ":":
                return text[:index]
            if char == "\n":
                # A bare newline at depth zero ends a single-line annotation;
                # multi-line annotations stay inside brackets.
                return text[:index]
    return text


_IGNORED_RETURN_TYPES = frozenset(
    {
        "Arc",
        "Box",
        "Cow",
        "Option",
        "Pin",
        "Rc",
        "Ref",
        "Result",
        "RwLock",
        "Vec",
        "Weak",
        "bool",
        "char",
        "f32",
        "f64",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "isize",
        "str",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "usize",
    }
)


def _named_types(expression: str) -> tuple[str, ...]:
    """Concrete type names inside one type expression, order-preserving."""
    names = [
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
        if token[:1].isupper() and token not in _IGNORED_RETURN_TYPES
    ]
    return tuple(dict.fromkeys(names))


def _return_type_names(
    signature_or_body: str,
    *,
    is_annotation: bool = False,
) -> tuple[str, ...]:
    """Type names named by a return annotation.

    Pass ``is_annotation`` when the caller already holds the annotation from
    the parser's own ``return_type`` field. The text path below exists only
    for definitions that never had one -- the regex frontend, and defs
    restored from graphs built before it was captured.
    """
    if is_annotation:
        return _named_types(signature_or_body)
    head = signature_or_body.split("{", 1)[0].rstrip(";")
    match = re.search(r"->\s*(?P<types>.+)$", head, flags=re.S)
    if not match:
        return ()
    return _named_types(_return_expression_head(re.split(r"\bwhere\b", match.group("types"), maxsplit=1)[0]))


def _select_owner_type(
    owner: str,
    source: SourceFile,
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
) -> str | None:
    candidates = [
        node_id
        for node_id in name_to_symbols.get(owner, ())
        if nodes.get(node_id) and nodes[node_id].kind in {"struct", "enum", "trait", "class", "type"}
    ]
    local = [node_id for node_id in candidates if nodes[node_id].path == source.rel]
    if len(local) == 1:
        return local[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


# `const { Assist } = require('./helper')` -- CommonJS destructuring. Unlike
# `const send = require('send')`, which binds the whole module and is handled as
# a module binding, each destructured name is a real exported symbol and must
# resolve like an ESM named import. Without this, CommonJS files resolved their
# same-file calls but lost every cross-file import edge.
_JS_DESTRUCTURED_REQUIRE = re.compile(
    r"\b(?:const|let|var)\s*\{([^}]+)\}\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)


def _imported_symbol_modules(suffix: str, text: str) -> dict[str, str]:
    """Map an imported name to its *full* module specifier.

    ``_imported_symbol_sources`` keeps only the final component, which is all a
    basename match needs and strictly less than the source states: `pkg.sub.
    helpers` and `other.helpers` both reduce to `helpers`. Retaining the whole
    specifier lets an import be resolved to the file it names.
    """
    modules: dict[str, str] = {}
    if suffix == ".py":
        pattern = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(?:\(([^)]+)\)|([^\n#]+))", re.MULTILINE)
        for match in pattern.finditer(text):
            specifier = match.group(1)
            for part in (match.group(2) or match.group(3) or "").split(","):
                name = part.strip().split(" as ", 1)[0].strip()
                if _identifier(name):
                    modules[name] = specifier
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for match in re.finditer(r"import\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", text):
            for part in match.group(1).split(","):
                name = part.strip().split(" as ", 1)[0].strip()
                if _identifier(name):
                    modules[name] = match.group(2)
        for match in _JS_DESTRUCTURED_REQUIRE.finditer(text):
            for part in match.group(1).split(","):
                name = part.strip().split(":", 1)[-1].strip()
                if _identifier(name):
                    modules[name] = match.group(2)
    return modules


def _imported_symbol_sources(suffix: str, text: str) -> dict[str, str]:
    """Map imported symbol local name to its module/file stem source.
    e.g. 'from helper import transform' -> {'transform': 'helper'}
    """
    sources: dict[str, str] = {}
    if suffix == ".py":
        pattern = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(?:\(([^)]+)\)|([^\n#]+))", re.MULTILINE)
        for m in pattern.finditer(text):
            module_name = m.group(1).split(".")[-1]
            imported_part = m.group(2) or m.group(3) or ""
            for part in imported_part.split(","):
                name = part.strip().split(" as ", 1)[0].strip()
                if _identifier(name):
                    sources[name] = module_name
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for m in re.finditer(r"import\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", text):
            module_name = Path(m.group(2)).stem
            for part in m.group(1).split(","):
                name = part.strip().split(" as ", 1)[0].strip()
                if _identifier(name):
                    sources[name] = module_name
        for m in _JS_DESTRUCTURED_REQUIRE.finditer(text):
            module_name = Path(m.group(2)).stem
            for part in m.group(1).split(","):
                name = part.strip().split(":", 1)[-1].strip()
                if _identifier(name):
                    sources[name] = module_name
    return sources


def _normalized_path_part(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _resolve_path_qualified_target(
    call: _CallSite,
    name_to_symbols: dict[str, list[str]],
    nodes: dict[str, Node],
) -> str | None:
    """Resolve ``module::function`` using the qualifier instead of its ambiguous leaf."""
    qualifier = tuple(
        part
        for raw in call.qualifier.split("::")
        if (part := _normalized_path_part(raw)) and part not in {"crate", "self", "super"}
    )
    if not qualifier:
        return None
    scored: list[tuple[int, str]] = []
    for target_id in name_to_symbols.get(call.name, ()):
        target = nodes.get(target_id)
        if target is None or target.kind not in {"function", "method"}:
            continue
        path_parts = {
            _normalized_path_part(part) for part in re.split(r"[/\\]", target.path) if _normalized_path_part(part)
        }
        context = _normalized_path_part(f"{target.path} {target.summary}")
        # The nearest module/type qualifier is mandatory. Earlier crate or
        # namespace components only break ties.
        if qualifier[-1] not in path_parts and qualifier[-1] not in context:
            continue
        score = 4
        score += sum(2 for part in qualifier[:-1] if part in path_parts or part in context)
        scored.append((score, target_id))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


_PYTHON_BUILTIN_TYPES = frozenset(
    {"bool", "bytes", "bytearray", "dict", "float", "frozenset", "int", "list", "set", "str", "tuple"}
)


def _method_owner(node_id: str, nodes: dict[str, Node]) -> str:
    node = nodes.get(node_id)
    if not node:
        return ""
    if node.parent:
        parent = nodes.get(node.parent)
        if parent:
            return parent.label
    for fact in node.facts:
        if fact.startswith("javascript_owner:"):
            return f"{node.path}::{fact.split(':', 1)[1]}"
    return ""


def _ancestor_chain(type_name: str, base_classes: dict[str, tuple[str, ...]]) -> list[str]:
    """Base classes of *type_name*, nearest first, breadth-first.

    Bounded and cycle-safe: a malformed or self-referential hierarchy must not
    hang extraction, and depth beyond a few links is not evidence worth
    claiming.
    """
    seen = {type_name}
    order: list[str] = []
    frontier = list(base_classes.get(type_name, ()))
    depth = 0
    while frontier and depth < 8:
        nxt: list[str] = []
        for name in frontier:
            if name in seen:
                continue
            seen.add(name)
            order.append(name)
            nxt.extend(base_classes.get(name, ()))
        frontier = nxt
        depth += 1
    return order


def _resolve_member_call(
    *,
    source: SourceFile,
    source_id: str,
    call: _CallSite,
    receiver_types: dict[str, str],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
    base_classes: dict[str, tuple[str, ...]] | None = None,
) -> str:
    base_classes = base_classes or {}
    receiver_type = receiver_types.get(call.receiver, "")
    if not receiver_type and source.path.suffix.lower() == ".rs" and _rust_qualified_type_receiver(call.receiver):
        receiver_type = call.receiver.split("::")[-1]
    if (
        not receiver_type
        and source.path.suffix.lower() == ".py"
        and _identifier(call.receiver)
        and call.receiver[:1].isupper()
    ):
        receiver_type = call.receiver
    if source.path.suffix.lower() == ".py" and receiver_type.startswith("builtins."):
        # Literal/constructor inference has proven that this receiver belongs
        # to Python's runtime, not to a same-named method in the repository.
        # Do not manufacture an edge, but also do not report the call as an
        # internal resolution miss merely because the graph defines `get`,
        # `append`, `add`, etc. on unrelated project classes.
        return "external_resolved"
    all_candidates = [
        node_id
        for node_id in name_to_symbols.get(call.name, ())
        if node_id != source_id
        and nodes.get(node_id)
        and nodes[node_id].kind == "method"
        and _lang_family(nodes[node_id].path) == _lang_family(source.rel)
    ]
    if not receiver_type and _identifier(call.receiver) and call.receiver[:1].isupper():
        # Static/qualified calls such as C# ``Flow.Root()`` carry their type
        # directly in the receiver.  Accept that evidence only when this graph
        # actually owns the named method on that owner; capitalization alone is
        # too weak to turn an arbitrary variable into a type.
        candidate_owners = {_method_owner(node_id, nodes) for node_id in all_candidates}
        if call.receiver in candidate_owners:
            receiver_type = call.receiver
    if not receiver_type:
        # A matching method name is not receiver evidence.  Keeping this as
        # telemetry instead of materializing name-only candidate edges avoids
        # turning list.append()/dict.get() collisions into graph topology.
        # No internal symbol carries this method name at all, so there is
        # nothing in the graph this call could have resolved to: not owning the
        # callee is the correct outcome, not a miss. See _unmatched_or_external.
        return "unknown_receiver" if all_candidates else "external_resolved"
    candidates = [node_id for node_id in all_candidates if _method_owner(node_id, nodes) == receiver_type]
    if not candidates and base_classes:
        # Inherited call: the receiver's type is known and the method exists,
        # just on an ancestor. Requiring an exact owner match made every such
        # call unresolvable -- `app.route()` on a Flask misses because `route`
        # is defined on a base class. Walk the chain nearest-first so an
        # override still wins over the definition it overrides.
        for ancestor in _ancestor_chain(receiver_type, base_classes):
            candidates = [node_id for node_id in all_candidates if _method_owner(node_id, nodes) == ancestor]
            if candidates:
                receiver_type = ancestor
                break
    if len(candidates) > 1:
        # Nearest scope again, one level down: two files can each declare a
        # class of the same name with the same method, and a receiver built in
        # this file means this file's class. Without this, `class Engine` in
        # core.js and an unrelated `class Engine` in core.ts made every
        # `e.Run()` in both files ambiguous, and each lost its edge. Ties still
        # fall through to the candidate path rather than picking arbitrarily.
        source_path = source.rel.replace("\\", "/")
        same_file = [
            node_id for node_id in candidates if nodes[node_id].path.replace("\\", "/") == source_path
        ]
        if len(same_file) == 1:
            candidates = same_file
    if len(candidates) == 1:
        edges.append(
            Edge(
                source_id,
                candidates[0],
                "calls",
                confidence=0.97,
                provenance="tree_sitter_type_resolved",
                source_location=source.rel,
                evidence=f"receiver {call.receiver}:{receiver_type}",
            )
        )
        return "resolved"
    if candidates:
        for target in sorted(candidates)[:8]:
            edges.append(
                Edge(
                    source_id,
                    target,
                    "calls_candidate",
                    confidence=0.45 if receiver_type else 0.3,
                    provenance="tree_sitter_ambiguous_call",
                    source_location=source.rel,
                    evidence=(
                        f"receiver {call.receiver}:{receiver_type}; {len(candidates)} candidates"
                        if receiver_type
                        else f"receiver type unresolved; {len(candidates)} candidates"
                    ),
                )
            )
        return "ambiguous"
    # Receiver type is known and every candidate was filtered out. Split on
    # whether the graph owns the method name at all: if some internal symbol
    # defines it, this call should have resolved and did not (a real miss); if
    # none does, the callee lives outside the graph and declining to link it is
    # correct. Collapsing both into one bucket made the largest telemetry
    # counter unable to distinguish working from broken.
    return "unmatched" if all_candidates else "external_resolved"


def _module_extensionless(path: str) -> str:
    normalised = path.replace("\\", "/")
    dot = normalised.rfind(".")
    return normalised[:dot] if dot > normalised.rfind("/") else normalised


def _resolve_module_specifier(specifier: str, source_rel: str, suffix: str) -> tuple[str, bool] | None:
    """Path an import specifier names, plus whether it was relative.

    Returns an extension-less repository path such as ``pkg/sub/helpers``. A
    bare JS/TS specifier (``lodash``) names a package rather than a path in this
    repository and yields ``None``, which leaves the existing heuristics to
    decide. This is the difference between knowing where an import points and
    guessing from its last component.
    """
    normalised_source = source_rel.replace("\\", "/")
    source_dir = normalised_source.rsplit("/", 1)[0] if "/" in normalised_source else ""
    directory = source_dir.split("/") if source_dir else []

    if suffix == ".py":
        if specifier.startswith("."):
            level = len(specifier) - len(specifier.lstrip("."))
            remainder = specifier[level:]
            # One dot is the current package; each extra dot climbs one level.
            ascend = level - 1
            if ascend > len(directory):
                return None
            base = directory[: len(directory) - ascend] if ascend else list(directory)
            tail = [part for part in remainder.split(".") if part]
            resolved = "/".join([*base, *tail])
            return (resolved, True) if resolved else None
        resolved = specifier.replace(".", "/")
        return (resolved, False) if resolved else None

    if specifier.startswith("."):
        parts = list(directory)
        for segment in specifier.split("/"):
            if segment in {"", "."}:
                continue
            if segment == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(segment)
        resolved = "/".join(parts)
        return (resolved, True) if resolved else None
    return None


def _module_specifier_candidates(
    specifier: str,
    source_rel: str,
    suffix: str,
    candidates: list[str],
    nodes: dict[str, Node],
) -> list[str]:
    """Candidates whose file is the module the specifier actually names."""
    resolved = _resolve_module_specifier(specifier, source_rel, suffix)
    if resolved is None:
        return []
    target, relative = resolved
    matched: list[str] = []
    for candidate in candidates:
        path = _module_extensionless(nodes[candidate].path)
        if path == target or path == f"{target}/__init__":
            matched.append(candidate)
        elif not relative and (path.endswith(f"/{target}") or path.endswith(f"/{target}/__init__")):
            # An absolute dotted module is written from the import root, which
            # may itself sit under `src/` or another source directory.
            matched.append(candidate)
    return matched


def _directory_parts(path: str) -> list[str]:
    """Directory components of a file path, nearest-last."""
    return [part for part in re.split(r"[/\\]", path) if part][:-1]


def _nearest_import_candidate(
    candidates: list[str],
    nodes: dict[str, Node],
    source_rel: str,
) -> str | None:
    """Pick the candidate whose directory is closest to the importing file.

    Module basenames repeat constantly in real trees (`helpers.py`, `utils.py`,
    `index.ts`), so matching an import by basename alone leaves several
    candidates and previously discarded all of them. Name resolution theory
    treats this as a visibility question rather than a naming one: a reference
    resolves along the shortest path to a declaration, and a nearer declaration
    shadows a farther one. Directory distance is the available approximation of
    that path, so a sibling module beats a same-named module elsewhere.

    Ties still return ``None``. Two candidates equally near are genuinely
    ambiguous, and dropping the edge keeps the extractor's precision property
    that it never fabricates a call it cannot justify.
    """
    source_dir = _directory_parts(source_rel)
    scored: list[tuple[int, int, str]] = []
    for candidate in candidates:
        candidate_dir = _directory_parts(nodes[candidate].path)
        shared = 0
        for left, right in zip(source_dir, candidate_dir):
            if left.casefold() != right.casefold():
                break
            shared += 1
        # A sibling module -- same directory, not merely a shared prefix -- is
        # the strongest evidence available without a real module graph.
        sibling = 1 if shared == len(source_dir) == len(candidate_dir) else 0
        scored.append((sibling, shared, candidate))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    best = scored[0]
    if len(scored) > 1 and (scored[1][0], scored[1][1]) == (best[0], best[1]):
        return None
    return best[2]


def _select_import_target(
    name: str,
    targets: list[str],
    stem: str | None,
    nodes: dict[str, Node],
    src_lang: str | None,
    reexports: dict[tuple[str, str], str],
    source_rel: str = "",
    specifier: str = "",
    suffix: str = "",
) -> str | None:
    compatible = [
        target
        for target in targets
        if (node := nodes.get(target)) is not None and (src_lang is None or _lang_family(node.path) in {None, src_lang})
    ]
    if len(compatible) == 1:
        return compatible[0]
    # Strongest evidence first: an import specifier usually names its module
    # outright, and resolving it is a lookup rather than a guess. `from
    # pkg.sub.helpers import Widget` is fully determined even when four other
    # files are also called `helpers.py`.
    if specifier and source_rel:
        located = _module_specifier_candidates(specifier, source_rel, suffix, compatible, nodes)
        if len(located) == 1:
            return located[0]
    if not stem:
        return None

    matching = [target for target in compatible if Path(nodes[target].path).stem.casefold() == stem.casefold()]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1 and source_rel and (nearest := _nearest_import_candidate(matching, nodes, source_rel)):
        return nearest

    reexport = reexports.get((stem.casefold(), name))
    return reexport if reexport in compatible else None


def _reexported_symbols(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    edges: list[Edge],
) -> dict[tuple[str, str], str]:
    source_paths = {source.file_node_id: source.rel for source, _defs, _root in defs_by_file}
    grouped: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        if edge.type != "imports_from":
            continue
        source_path = source_paths.get(edge.source, "").replace("\\", "/")
        if not source_path.endswith("/__init__.py"):
            continue
        target = nodes.get(edge.target)
        if target is None:
            continue
        package = Path(source_path).parent.name.casefold()
        grouped.setdefault((package, target.label), []).append(edge.target)
    return {key: values[0] for key, values in grouped.items() if len(set(values)) == 1}


def _imported_symbol_names(suffix: str, text: str) -> set[str]:
    names: set[str] = set()
    if suffix == ".rs":
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("use "):
                continue
            body = stripped[4:].rstrip(";")
            for group in re.findall(r"\{([^}]+)\}", body):
                for part in group.split(","):
                    name = part.strip().split(" as ", 1)[0].split("::")[-1].strip()
                    if _identifier(name):
                        names.add(name)
            tail = body.split("::")[-1].split(" as ", 1)[0].strip()
            if _identifier(tail) and tail not in {"self", "super", "crate"}:
                names.add(tail)
    elif suffix == ".py":
        pattern = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(?:\(([^)]+)\)|([^\n#]+))", re.MULTILINE)
        for m in pattern.finditer(text):
            imported_part = m.group(2) or m.group(3) or ""
            for part in imported_part.split(","):
                name = part.strip().split(" as ", 1)[0].strip()
                if _identifier(name):
                    names.add(name)
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for group in re.findall(r"import\s+\{([^}]+)\}", text):
            for part in group.split(","):
                name = part.strip().split(" as ", 1)[0].strip()
                if _identifier(name):
                    names.add(name)
        for m in _JS_DESTRUCTURED_REQUIRE.finditer(text):
            for part in m.group(1).split(","):
                name = part.strip().split(":", 1)[-1].strip()
                if _identifier(name):
                    names.add(name)
    return names


def _identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value))


_CALL_NODE_TYPES = {
    "call_expression",  # JS/TS, Go, Rust, C/C++, Kotlin, Scala, Swift
    "call",  # Python, Ruby
    "invocation_expression",  # C#
    "method_invocation",  # Java
    "function_call_expression",  # PHP
    "member_call_expression",  # PHP  (obj->method())
    "scoped_call_expression",  # PHP  (Class::method())
    "command",  # Ruby (method call without parentheses)
    "command_call",  # Ruby (receiver.method arg)
    "method_call",  # misc grammars
}

# Fields that hold the callee across the grammars above.
_CALL_NAME_FIELDS = ("function", "name", "method")

# Path/scope-qualified callee expressions -- Type::function(...) (Rust) or
# Namespace::function(...) / Class::static_method(...) (C++) -- name a
# lexically fixed target, unlike receiver.method(...) where the receiver's
# *type* determines what's actually called. These are NOT treated as
# "qualified" for resolution purposes: the trailing name (e.g. "from_uni" in
# `QuadPoly::from_uni(...)`) is still safe to look up like a bare call.
# Deliberately not extended to languages where static and instance member
# access are structurally identical (Python's `attribute` covers both
# `Class.method()` and `instance.method()`; same for C#/JS/Java `.`-access)
# -- there the grammar gives no signal to split them safely, so those stay
# qualified/unresolved.
_PATH_QUALIFIED_CALL_TYPES = {
    "scoped_identifier",  # Rust: Type::function(...), module::function(...)
    "qualified_identifier",  # C++: Namespace::function(...), Class::static_method(...)
}


def _rust_qualified_type_receiver(value: str) -> bool:
    """Whether a Rust receiver explicitly names a unit-struct/type path."""
    parts = value.split("::")
    return bool(len(parts) >= 1 and all(_identifier(part) for part in parts) and parts[-1][:1].isupper())


def _call_sites_in_range(
    root: Any,
    text: bytes,
    start: int,
    end: int,
    *,
    suffix: str = "",
) -> set[_CallSite]:
    """Return bounded call-site facts, retaining receiver text for type resolution."""
    sites: set[_CallSite] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if int(node.end_byte) < start or int(node.start_byte) > end:
            continue
        stack.extend(reversed(list(getattr(node, "named_children", ()))))
        if node.type not in _CALL_NODE_TYPES:
            continue
        fn = None
        for field in _CALL_NAME_FIELDS:
            try:
                fn = node.child_by_field_name(field)
            except Exception:
                fn = None
            if fn is not None:
                break
        used_named_child_fallback = fn is None
        if fn is None:
            # Fall back to the first named child that is not the argument list.
            for child in getattr(node, "named_children", ()):
                if "argument" not in child.type:
                    fn = child
                    break
        if fn is None:
            continue
        if suffix == ".swift" and used_named_child_fallback:
            # Swift folds the final call in `First() + Second()` into an outer
            # `call_expression(additive_expression(... rhs: Second),
            # call_suffix)`. The generic fallback sees the whole additive
            # expression as the callee, misclassifies `Second` as a qualified
            # call on `First()`, and drops it during receiver resolution.
            # The suffix applies specifically to the RHS identifier. Nested
            # compound expressions repeat this shape, so each later call is
            # recovered as the traversal visits its corresponding wrapper.
            has_call_suffix = any(
                child.type == "call_suffix"
                for child in getattr(node, "named_children", ())
            )
            try:
                rhs = fn.child_by_field_name("rhs")
            except Exception:
                rhs = None
            if has_call_suffix and rhs is not None and rhs.type in _NAME_NODE_TYPES:
                fn = rhs
        is_qualified = fn.type not in _NAME_NODE_TYPES and fn.type not in _PATH_QUALIFIED_CALL_TYPES
        name = _call_name(fn, text)
        if name:
            receiver = ""
            qualifier = ""
            if fn.type in _PATH_QUALIFIED_CALL_TYPES:
                qualified_text = _node_text(fn, text).strip()
                parts = qualified_text.split("::")
                if len(parts) >= 2:
                    qualifier = "::".join(parts[:-1])
            # Java/Kotlin `method_invocation` carries the receiver as a sibling
            # `object` field on the call node itself, so the name reads as a
            # bare identifier and the call was misclassified as unqualified --
            # every Java member call went undetected (0 sites, cycle 8's C#
            # finding is worse in Java). Other languages nest the receiver
            # inside the name/function child, so this only fires where the call
            # node exposes its own object field.
            if not is_qualified and fn.type in _NAME_NODE_TYPES:
                direct_object = None
                for field in ("object", "receiver"):
                    try:
                        direct_object = node.child_by_field_name(field)
                    except Exception:
                        direct_object = None
                    if direct_object is not None:
                        break
                if direct_object is not None:
                    is_qualified = True
                    receiver = _node_text(direct_object, text).strip()
            if is_qualified:
                # `expression` is C#'s object field on member_access_expression
                # (its object is reachable only via the field, not as a named
                # child, so the named-child fallback below cannot recover it).
                # Ordered last with the break so languages that use
                # value/object/receiver still bind their own field first.
                # Skip when a direct object field already set the receiver above.
                for field in () if receiver else ("value", "object", "receiver", "expression"):
                    try:
                        receiver_node = fn.child_by_field_name(field)
                    except Exception:
                        receiver_node = None
                    if receiver_node is not None:
                        receiver = _node_text(receiver_node, text).strip()
                        break
                if not receiver:
                    children = list(getattr(fn, "named_children", ()))
                    if len(children) >= 2:
                        receiver = _node_text(children[0], text).strip()
                # `self.x` (Rust/Python) and `this.x` (TS/JS) are the one field form
                # the resolver can type, via the owner's field table.
                rust_field_receiver = bool(re.fullmatch(r"(?:self|this)\.[A-Za-z_$][\w$]*", receiver))
                # `build_report(x).render()` -- the receiver is whatever the
                # inner call returns. Normalize it to a bare `name()` key so
                # the frontend can bind it to that function's return type
                # without this layer having to model arguments.
                call_receiver = re.fullmatch(
                    r"(?:[A-Za-z_][A-Za-z0-9_]*::)*([A-Za-z_][A-Za-z0-9_]*)\s*\(.*\)",
                    receiver,
                    re.DOTALL,
                )
                if call_receiver is not None:
                    receiver = f"{call_receiver.group(1)}()"
                elif re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+",
                    receiver,
                ):
                    # Preserve dotted module namespaces such as
                    # ``flask.helpers``. Resolution still requires the first
                    # component to be a proven import alias.
                    pass
                elif (
                    not _identifier(receiver)
                    and receiver != "self"
                    and not rust_field_receiver
                    and not _rust_qualified_type_receiver(receiver)
                ):
                    receiver = ""
            sites.add(
                _CallSite(
                    name=name,
                    qualified=is_qualified,
                    receiver=receiver,
                    qualifier=qualifier,
                )
            )
    return sites


def _callback_arg_names_in_range(root: Any, text: bytes, start: int, end: int) -> set[str]:
    """Return bare-identifier names passed as call arguments in [start, end).

    Static call-graph analysis only recognizes ``name(...)`` as a call site,
    so a function invoked exclusively via function-pointer/callback
    dispatch -- ``SetMainCallback2(CB2_InitBattle)`` (C), ``setTimeout(cb, ms)``
    (JS), ``signal.connect(handler)`` (Python) -- reads as having zero
    callers even when it's genuinely used extensively. This walks the same
    call-expression nodes as ``_call_sites_in_range`` but looks at the
    ``arguments`` field instead of the callee, collecting any argument that
    is itself a bare name (not a nested call, literal, or other expression).
    Also unwraps Python/keyword-style ``func=callback`` arguments (e.g.
    argparse's ``set_defaults(func=cmd_scan)``) via their ``value`` field --
    an extremely common callback-registration idiom that a bare
    ``arg.type in _NAME_NODE_TYPES`` check would otherwise miss entirely,
    since the direct argument-list child is a ``keyword_argument`` wrapper,
    not the identifier itself.
    Verified empirically (not assumed) that tree-sitter's C, JavaScript, and
    Python grammars all expose this via ``child_by_field_name("arguments")``
    despite differing node type names (``argument_list`` vs ``arguments``).
    """
    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if int(node.end_byte) < start or int(node.start_byte) > end:
            continue
        stack.extend(reversed(list(getattr(node, "named_children", ()))))
        if node.type not in _CALL_NODE_TYPES:
            continue
        try:
            args_node = node.child_by_field_name("arguments")
        except Exception:
            args_node = None
        if args_node is None:
            continue
        for arg in getattr(args_node, "named_children", ()):
            candidate = arg
            if arg.type == "keyword_argument":
                try:
                    candidate = arg.child_by_field_name("value") or arg
                except Exception:
                    candidate = arg
            if candidate.type in _NAME_NODE_TYPES:
                name = _node_text(candidate, text)
                if name:
                    names.add(name)
    return names


def _call_name(node: Any, text: bytes) -> str:
    if node.type in _NAME_NODE_TYPES:
        return _node_text(node, text)
    parts: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in _NAME_NODE_TYPES:
            parts.append(_node_text(current, text))
        stack.extend(reversed(list(getattr(current, "named_children", ()))))
    return parts[-1] if parts else ""
