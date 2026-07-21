"""Generic tree-sitter traversal: definition collection, call sites, and symbol resolution."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ...graph.core import Edge, Node
from ..ast import _lang_family
from .model import (
    SourceFile,
    _CallSite,
    _TsDef,
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
    "constant",  # Ruby class/module names
}

DEFINITION_NODE_TYPES = MappingProxyType(_DEF_TYPES)

NAME_NODE_TYPES = frozenset(_NAME_NODE_TYPES)

_LANGUAGE_CACHE: dict[str, Any] = {}

_LANGUAGE_LOAD_ERRORS: dict[str, str] = {}

_PARSER_CACHE: dict[str, Any] = {}

_PARSER_LOAD_ERRORS: dict[str, str] = {}

def _collect_defs(source: SourceFile, root: Any, text: bytes) -> list[_TsDef]:
    defs: list[_TsDef] = []
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
            continue
        name_node = _name_node(node)
        if name_node is None:
            continue
        name = _node_text(name_node, text)
        if not name:
            continue
        defs.append(_TsDef(
            name=name,
            kind=kind,
            start=int(node.start_byte),
            end=int(node.end_byte),
            line=int(node.start_point[0]) + 1,
            facts=_definition_facts(source, node, text),
            extra=_base_class_names(node, text),
        ))
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

def _syntax_text_without_literals(node: Any, text: bytes) -> str:
    """Return a node's source with non-executable literal regions blanked."""
    start = int(node.start_byte)
    segment = bytearray(text[start:int(node.end_byte)])
    stack = list(getattr(node, "children", ()))
    while stack:
        child = stack.pop()
        child_type = str(getattr(child, "type", "")).casefold()
        is_non_code = (
            "comment" in child_type
            or "string" in child_type
            or "regex" in child_type
            or child_type in {"char_literal", "character_literal", "heredoc_body"}
        )
        if is_non_code:
            left = max(0, int(child.start_byte) - start)
            right = min(len(segment), int(child.end_byte) - start)
            segment[left:right] = b" " * max(0, right - left)
            continue
        stack.extend(getattr(child, "children", ()))
    return bytes(segment).decode("utf-8", errors="replace")

def _definition_facts(source: SourceFile, node: Any, text: bytes) -> tuple[str, ...]:
    """Project language attributes into small, queryable normalized-IR facts."""
    if _DEF_TYPES.get(node.type) not in {"function", "method"}:
        return ()
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
        return tuple(facts)

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
    if (
        re.search(r"\b(?:BTreeSet|HashSet)\s*::\s*(?:new|default)\s*\(", snippet)
        and re.search(r"\.insert\s*\(", snippet)
    ):
        facts.extend(("collection_contract:unique", "semantic_operation:deduplication"))
    return tuple(dict.fromkeys(facts))

def _attach_lexical_method_owners(defs: list[_TsDef]) -> list[_TsDef]:
    """Mark callables directly nested in a type as owned methods."""
    owner_kinds = {"class", "trait", "struct", "enum", "interface", "type"}
    owned: list[_TsDef] = []
    for definition in defs:
        if definition.kind not in {"function", "method"}:
            owned.append(definition)
            continue
        enclosing = [
            parent for parent in defs
            if parent is not definition
            and parent.start < definition.start
            and definition.end <= parent.end
        ]
        parent = min(enclosing, key=lambda item: item.end - item.start, default=None)
        if parent is None or parent.kind not in owner_kinds:
            owned.append(definition)
            continue
        owned.append(replace(
            definition,
            kind="method",
            owner=parent.name,
            extra=("", parent.name),
        ))
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
    return text[int(node.start_byte):int(node.end_byte)].decode("utf-8", errors="replace")

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

def _return_type_names(signature_or_body: str) -> tuple[str, ...]:
    head = signature_or_body.split("{", 1)[0].rstrip(";")
    match = re.search(r"->\s*(?P<types>.+)$", head, flags=re.S)
    if not match:
        return ()
    ignored = {
        "Arc", "Box", "Cow", "Option", "Pin", "Rc", "Ref", "Result", "RwLock",
        "Vec", "Weak", "bool", "char", "f32", "f64", "i8", "i16", "i32", "i64",
        "i128", "isize", "str", "u8", "u16", "u32", "u64", "u128", "usize",
    }
    return_expression = re.split(r"\bwhere\b", match.group("types"), maxsplit=1)[0]
    names = [
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", return_expression)
        if token[:1].isupper() and token not in ignored
    ]
    return tuple(dict.fromkeys(names))

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
            _normalized_path_part(part)
            for part in re.split(r"[/\\]", target.path)
            if _normalized_path_part(part)
        }
        context = _normalized_path_part(f"{target.path} {target.summary}")
        # The nearest module/type qualifier is mandatory. Earlier crate or
        # namespace components only break ties.
        if qualifier[-1] not in path_parts and qualifier[-1] not in context:
            continue
        score = 4
        score += sum(
            2
            for part in qualifier[:-1]
            if part in path_parts or part in context
        )
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
    if not node or not node.parent:
        return ""
    parent = nodes.get(node.parent)
    return parent.label if parent else ""


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
    all_candidates = [
        node_id
        for node_id in name_to_symbols.get(call.name, ())
        if node_id != source_id
        and nodes.get(node_id)
        and nodes[node_id].kind == "method"
        and _lang_family(nodes[node_id].path) == _lang_family(source.rel)
    ]
    if not receiver_type:
        # A matching method name is not receiver evidence.  Keeping this as
        # telemetry instead of materializing name-only candidate edges avoids
        # turning list.append()/dict.get() collisions into graph topology.
        return "unknown_receiver" if all_candidates else "unresolved"
    candidates = [node_id for node_id in all_candidates if _method_owner(node_id, nodes) == receiver_type]
    if not candidates and base_classes:
        # Inherited call: the receiver's type is known and the method exists,
        # just on an ancestor. Requiring an exact owner match made every such
        # call unresolvable -- `app.route()` on a Flask misses because `route`
        # is defined on a base class. Walk the chain nearest-first so an
        # override still wins over the definition it overrides.
        for ancestor in _ancestor_chain(receiver_type, base_classes):
            candidates = [
                node_id for node_id in all_candidates
                if _method_owner(node_id, nodes) == ancestor
            ]
            if candidates:
                receiver_type = ancestor
                break
    if len(candidates) == 1:
        edges.append(Edge(
            source_id,
            candidates[0],
            "calls",
            confidence=0.97,
            provenance="tree_sitter_type_resolved",
            source_location=source.rel,
            evidence=f"receiver {call.receiver}:{receiver_type}",
        ))
        return "resolved"
    if candidates:
        for target in sorted(candidates)[:8]:
            edges.append(Edge(
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
            ))
        return "ambiguous"
    return "unresolved"

def _select_import_target(
    name: str,
    targets: list[str],
    stem: str | None,
    nodes: dict[str, Node],
    src_lang: str | None,
    reexports: dict[tuple[str, str], str],
) -> str | None:
    compatible = [
        target
        for target in targets
        if (node := nodes.get(target)) is not None
        and (src_lang is None or _lang_family(node.path) in {None, src_lang})
    ]
    if len(compatible) == 1:
        return compatible[0]
    if not stem:
        return None

    matching = [target for target in compatible if Path(nodes[target].path).stem.casefold() == stem.casefold()]
    if len(matching) == 1:
        return matching[0]

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
    return names

def _identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value))

_CALL_NODE_TYPES = {
    "call_expression",           # JS/TS, Go, Rust, C/C++, Kotlin, Scala, Swift
    "call",                      # Python, Ruby
    "invocation_expression",     # C#
    "method_invocation",         # Java
    "function_call_expression",  # PHP
    "member_call_expression",    # PHP  (obj->method())
    "scoped_call_expression",    # PHP  (Class::method())
    "command",                   # Ruby (method call without parentheses)
    "command_call",              # Ruby (receiver.method arg)
    "method_call",               # misc grammars
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
    "scoped_identifier",   # Rust: Type::function(...), module::function(...)
    "qualified_identifier",  # C++: Namespace::function(...), Class::static_method(...)
}

def _rust_qualified_type_receiver(value: str) -> bool:
    """Whether a Rust receiver explicitly names a unit-struct/type path."""
    parts = value.split("::")
    return bool(
        len(parts) >= 1
        and all(_identifier(part) for part in parts)
        and parts[-1][:1].isupper()
    )

def _call_sites_in_range(root: Any, text: bytes, start: int, end: int) -> set[_CallSite]:
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
        if fn is None:
            # Fall back to the first named child that is not the argument list.
            for child in getattr(node, "named_children", ()):
                if "argument" not in child.type:
                    fn = child
                    break
        if fn is None:
            continue
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
            if is_qualified:
                for field in ("value", "object", "receiver"):
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
                rust_field_receiver = bool(re.fullmatch(r"self\.[A-Za-z_][A-Za-z0-9_]*", receiver))
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
                elif (
                    not _identifier(receiver)
                    and receiver != "self"
                    and not rust_field_receiver
                    and not _rust_qualified_type_receiver(receiver)
                ):
                    receiver = ""
            sites.add(_CallSite(
                name=name,
                qualified=is_qualified,
                receiver=receiver,
                qualifier=qualifier,
            ))
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
