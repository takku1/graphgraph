"""Rust-specific extraction: impl blocks, fields, macros, and type references."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from ...graph.core import Edge, Node
from .model import (
    SourceFile,
    _TsDef,
)
from .syntax import (
    _definition_node_id,
    _definition_summary,
    _identifier,
    _method_owner,
    _node_text,
    _node_text_range,
    _return_type_name,
    _select_owner_type,
)


def _rust_fields_in_range(root: Any, text: bytes, start: int, end: int) -> list[tuple[str, str, int]]:
    fields: list[tuple[str, str, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if int(node.end_byte) < start or int(node.start_byte) > end:
            continue
        stack.extend(reversed(list(getattr(node, "named_children", ()))))
        if node.type != "field_declaration":
            continue
        if int(node.start_byte) < start or int(node.end_byte) > end:
            continue
        name_node = None
        for child in getattr(node, "named_children", ()):
            if child.type == "field_identifier":
                name_node = child
                break
        if name_node is None:
            continue
        name = _node_text(name_node, text)
        if _identifier(name):
            try:
                type_node = node.child_by_field_name("type")
            except Exception:
                type_node = None
            if type_node is None:
                type_node = next(
                    (
                        child
                        for child in getattr(node, "named_children", ())
                        if child is not name_node and child.type != "visibility_modifier"
                    ),
                    None,
                )
            type_name = _rust_type_name(_node_text(type_node, text) if type_node is not None else "")
            fields.append((name, type_name, int(node.start_point[0]) + 1))
    return fields

def _rust_type_name(value: str) -> str:
    wrappers = {
        "Arc", "Box", "Cow", "Mutex", "Option", "Pin", "Rc", "Ref", "Result",
        "RwLock", "Vec", "Weak",
    }
    candidates = [
        token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", value)
        if token[:1].isupper() and token not in wrappers
    ]
    return candidates[0] if candidates else ""

def _add_rust_method_owners(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    """Attach Rust impl methods to their owning type.

    The owner is structural evidence used by receiver-call resolution. It also
    repairs a hierarchy gap: Rust methods are lexically inside ``impl`` blocks,
    not inside the struct declaration itself.
    """
    for source, defs, _root in defs_by_file:
        if source.path.suffix.lower() != ".rs":
            continue
        for definition in defs:
            if definition.kind != "method" or not definition.owner:
                continue
            method_id = _definition_node_id(source, definition)
            if method_id not in nodes:
                continue
            owner_id = _select_owner_type(definition.owner, source, nodes, name_to_symbols)
            if not owner_id:
                continue
            nodes[method_id] = replace(nodes[method_id], parent=owner_id)
            edges.append(Edge(
                owner_id,
                method_id,
                "contains",
                confidence=0.97,
                provenance="tree_sitter_type_resolved",
                source_location=f"{source.rel}:{definition.line}",
            ))

def _add_rust_fields(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    edges: list[Edge],
) -> None:
    for source, defs, root in defs_by_file:
        if source.path.suffix.lower() != ".rs":
            continue
        text = source.text.encode("utf-8", errors="replace")
        structs = [d for d in defs if d.kind == "struct" and _definition_node_id(source, d) in nodes]
        if not structs:
            continue
        for struct in structs:
            struct_id = _definition_node_id(source, struct)
            for field_name, field_type, line in _rust_fields_in_range(root, text, struct.start, struct.end):
                field_id = f"{struct_id}__field_{field_name}"
                if field_id not in nodes:
                    nodes[field_id] = Node(
                        id=field_id,
                        label=field_name,
                        kind="field",
                        path=source.rel,
                        summary=_definition_summary(source.text, line),
                        facts=(f"type:{field_type}",) if field_type else (),
                        parent=struct_id,
                        source=str(source.path),
                        confidence=0.9,
                    )
                edges.append(Edge(
                    struct_id,
                    field_id,
                    "contains",
                    confidence=0.9,
                    provenance="tree_sitter",
                    source_location=f"{source.rel}:{line}",
                ))
                edges.append(Edge(
                    field_id,
                    struct_id,
                    "field_of",
                    confidence=0.9,
                    provenance="tree_sitter",
                    source_location=f"{source.rel}:{line}",
                ))

def _add_rust_test_field_references(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    edges: list[Edge],
) -> None:
    """Link typed Rust field assertions directly to their schema fields."""
    fields_by_name: dict[str, list[str]] = {}
    field_types: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node.kind == "field":
            fields_by_name.setdefault(node.label, []).append(node_id)
            field_type = next(
                (
                    fact.split(":", 1)[1]
                    for fact in node.facts
                    if fact.startswith("type:") and len(fact.split(":", 1)) == 2
                ),
                "",
            )
            if field_type:
                field_types[node_id] = field_type
    if not fields_by_name:
        return
    return_types_by_name: dict[str, set[str]] = {}
    for source, defs, _root in defs_by_file:
        if source.path.suffix.lower() != ".rs":
            continue
        text_bytes = source.text.encode("utf-8", errors="replace")
        for definition in (item for item in defs if item.kind in {"function", "method"}):
            return_type = _return_type_name(
                _node_text_range(text_bytes, definition.start, definition.end)
            )
            if return_type:
                return_types_by_name.setdefault(definition.name, set()).add(return_type)
    unique_return_types = {
        name: next(iter(types))
        for name, types in return_types_by_name.items()
        if len(types) == 1
    }
    existing = {(edge.source, edge.target, edge.type) for edge in edges}
    for source, defs, root in defs_by_file:
        normalized = "/" + source.rel.replace("\\", "/").casefold()
        if source.path.suffix.lower() != ".rs" or (
            "/tests/" not in normalized
            and not Path(source.rel).name.casefold().endswith(("_test.rs", "tests.rs"))
        ):
            continue
        text_bytes = source.text.encode("utf-8", errors="replace")
        for definition in (item for item in defs if item.kind in {"function", "method"}):
            source_id = _definition_node_id(source, definition)
            if source_id not in nodes:
                continue
            body = _node_text_range(text_bytes, definition.start, definition.end)
            receiver_types = _rust_local_types(body)
            receiver_types.update(_rust_local_call_return_types(body, unique_return_types))
            if definition.owner:
                receiver_types["self"] = definition.owner
            accesses = sorted(
                _rust_field_accesses_in_range(
                    root,
                    text_bytes,
                    definition.start,
                    definition.end,
                ),
                key=lambda item: (item[0].count("."), item),
            )
            for receiver, field_name in accesses:
                receiver_type = receiver_types.get(receiver, "")
                if not receiver_type:
                    continue
                candidates = [
                    node_id
                    for node_id in fields_by_name.get(field_name, ())
                    if _method_owner(node_id, nodes) == receiver_type
                ]
                if len(candidates) != 1:
                    continue
                field_type = field_types.get(candidates[0], "")
                if field_type:
                    receiver_types[f"{receiver}.{field_name}"] = field_type
                key = (source_id, candidates[0], "references")
                if key in existing:
                    continue
                existing.add(key)
                edges.append(Edge(
                    source_id,
                    candidates[0],
                    "references",
                    confidence=0.94,
                    provenance="tree_sitter_type_resolved_field_assertion",
                    source_location=source.rel,
                    evidence=f"test receiver {receiver}:{receiver_type}.{field_name}",
                ))

def _rust_local_call_return_types(
    body: str,
    return_types: dict[str, str],
) -> dict[str, str]:
    inferred: dict[str, str] = {}
    for match in re.finditer(
        r"\blet\s+(?:mut\s+)?(?P<variable>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*:\s*[^=;]+)?\s*=\s*(?:[A-Za-z_][A-Za-z0-9_]*::)*"
        r"(?P<function>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
        body,
    ):
        return_type = return_types.get(match.group("function"), "")
        if return_type:
            inferred[match.group("variable")] = return_type
    return inferred

def _rust_type_names_in_range(text: bytes, start: int, end: int) -> set[str]:
    """Return conservative Rust type/enum references from one definition body."""
    snippet = _node_text_range(text, start, end)
    names: set[str] = set()
    patterns = (
        r"\b([A-Z][A-Za-z0-9_]*)\s*::",
        r"(?:[:&<,(]\s*)([A-Z][A-Za-z0-9_]*)\b",
        r"->\s*(?:Result\s*<\s*)?(?:Option\s*<\s*)?([A-Z][A-Za-z0-9_]*)\b",
    )
    for pattern in patterns:
        names.update(match.group(1) for match in re.finditer(pattern, snippet))
    return names

def _add_rust_type_references(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    """Link Rust functions/tests to uniquely named schema types they use.

    These are ``references`` rather than ``calls`` edges. They make type-level
    impact queries (for example, tests constructing ``Expr::Constant``) visible
    without claiming runtime dispatch.
    """
    type_kinds = {"class", "enum", "interface", "struct", "trait", "type"}
    unique_types = {
        name: ids[0]
        for name, ids in name_to_symbols.items()
        if len(ids) == 1 and nodes[ids[0]].kind in type_kinds
    }
    if not unique_types:
        return
    existing = {(edge.source, edge.target, edge.type) for edge in edges}
    for source, defs, _root in defs_by_file:
        if source.path.suffix.lower() != ".rs":
            continue
        text_bytes = source.text.encode("utf-8", errors="replace")
        for definition in (item for item in defs if item.kind in {"function", "method"}):
            source_id = _definition_node_id(source, definition)
            if source_id not in nodes:
                continue
            for name in _rust_type_names_in_range(text_bytes, definition.start, definition.end):
                target_id = unique_types.get(name)
                key = (source_id, target_id or "", "references")
                if not target_id or target_id == source_id or key in existing:
                    continue
                edges.append(Edge(
                    source_id,
                    target_id,
                    "references",
                    confidence=0.88,
                    provenance="tree_sitter_type_reference",
                    source_location=f"{source.rel}:{definition.line}",
                ))
                existing.add(key)

def _rust_local_types(body: str) -> dict[str, str]:
    """Extract conservative local receiver types from Rust parameters/lets."""
    result: dict[str, str] = {}
    type_pattern = r"(?:&\s*)?(?:'\w+\s+)?(?:mut\s+)?([A-Za-z_][A-Za-z0-9_:]*)"
    for match in re.finditer(
        rf"(?:^|[,(])\s*(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*{type_pattern}",
        body.split("{", 1)[0],
    ):
        type_name = match.group(2).split("::")[-1]
        if type_name[:1].isupper():
            result[match.group(1)] = type_name
    for match in re.finditer(
        rf"\blet\s+(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*{type_pattern}",
        body,
    ):
        type_name = match.group(2).split("::")[-1]
        if type_name[:1].isupper():
            result[match.group(1)] = type_name
    for match in re.finditer(
        r"\blet\s+(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*&?\s*([A-Z][A-Za-z0-9_:]*)\s*(?:::\w+\s*\(|\{)",
        body,
    ):
        result.setdefault(match.group(1), match.group(2).split("::")[-1])
    return result

def _rust_macro_bare_call_names_in_range(
    root: Any,
    text: bytes,
    start: int,
    end: int,
) -> set[str]:
    """Recover Rust calls hidden in macro token trees.

    The Rust grammar intentionally leaves macro bodies as ``token_tree``
    rather than parsing their expressions. Within those bounded trees,
    ``identifier`` immediately followed by a parenthesized token tree is the
    lowest reliable call signal. Macro heads (``name!``), method calls
    (``.name``), and path continuations (``::name``) are excluded.
    """
    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if int(node.end_byte) < start or int(node.start_byte) > end:
            continue
        stack.extend(reversed(list(getattr(node, "named_children", ()))))
        if node.type != "token_tree":
            continue
        children = list(getattr(node, "named_children", ()))
        for index, child in enumerate(children[:-1]):
            if child.type != "identifier":
                continue
            arguments = children[index + 1]
            if arguments.type != "token_tree":
                continue
            argument_text = _node_text(arguments, text).lstrip()
            if not argument_text.startswith("("):
                continue
            gap = text[int(child.end_byte):int(arguments.start_byte)].decode(
                "utf-8",
                errors="replace",
            )
            if "!" in gap:
                continue
            prefix = text[max(start, int(child.start_byte) - 2):int(child.start_byte)].decode(
                "utf-8",
                errors="replace",
            ).rstrip()
            if prefix.endswith((".", ":")):
                continue
            name = _node_text(child, text).strip()
            if _identifier(name):
                names.add(name)
    return names

def _rust_field_accesses_in_range(
    root: Any,
    text: bytes,
    start: int,
    end: int,
) -> set[tuple[str, str]]:
    accesses: set[tuple[str, str]] = set()
    snippet = _node_text_range(text, start, end)
    for match in re.finditer(
        r"\b(?P<chain>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b",
        snippet,
    ):
        parts = match.group("chain").split(".")
        accesses.update(
            (".".join(parts[:index]), parts[index])
            for index in range(1, len(parts))
        )
    stack = [root]
    while stack:
        node = stack.pop()
        if int(node.end_byte) < start or int(node.start_byte) > end:
            continue
        stack.extend(reversed(list(getattr(node, "named_children", ()))))
        if node.type != "field_expression":
            continue
        try:
            receiver_node = node.child_by_field_name("value")
            field_node = node.child_by_field_name("field")
        except Exception:
            continue
        if receiver_node is None or field_node is None:
            continue
        receiver = _node_text(receiver_node, text).strip()
        field_name = _node_text(field_node, text).strip()
        if _identifier(receiver) and _identifier(field_name):
            accesses.add((receiver, field_name))
    return accesses
