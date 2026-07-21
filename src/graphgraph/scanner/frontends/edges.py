"""Relation builders that turn resolved syntax into graph edges."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ...graph.core import Edge, Node
from ..ast import _lang_family
from .model import (
    SourceFile,
    _CallSite,
    _MemberCallStats,
    _TsDef,
)
from .python import (
    _python_class_field_types,
    _python_local_types,
)
from .rust import (
    _rust_fields_in_range,
    _rust_local_types,
    _rust_macro_bare_call_names_in_range,
)
from .syntax import (
    _call_sites_in_range,
    _callback_arg_names_in_range,
    _definition_node_id,
    _imported_symbol_names,
    _imported_symbol_sources,
    _node_text_range,
    _reexported_symbols,
    _resolve_member_call,
    _resolve_path_qualified_target,
    _return_type_name,
    _return_type_names,
    _select_import_target,
)


def _add_tree_sitter_implements(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    for _source, defs, _root in defs_by_file:
        for d in defs:
            if d.kind != "impl_block" or len(d.extra) != 2:
                continue
            trait_name, type_name = d.extra
            if not trait_name:
                continue
            for type_id in name_to_symbols.get(type_name, []):
                for trait_id in name_to_symbols.get(trait_name, []):
                    if type_id != trait_id:
                        edges.append(Edge(type_id, trait_id, "implements", confidence=0.95, provenance="tree_sitter"))

def _add_nested_contains(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    edges: list[Edge],
) -> None:
    owner_kinds = {"class", "trait", "struct", "enum", "interface"}
    child_kinds = {"function", "method", "class", "struct", "enum", "trait", "interface", "type"}
    for source, defs, _root in defs_by_file:
        materialized = [d for d in defs if _definition_node_id(source, d) in nodes and d.kind != "impl_block"]
        for child in materialized:
            if child.kind not in child_kinds:
                continue
            parents = [
                parent for parent in materialized
                if parent.kind in owner_kinds
                and parent.start < child.start
                and child.end <= parent.end
            ]
            if not parents:
                continue
            parent = min(parents, key=lambda d: d.end - d.start)
            parent_id = _definition_node_id(source, parent)
            child_id = _definition_node_id(source, child)
            if parent_id != child_id:
                nodes[child_id] = replace(nodes[child_id], parent=parent_id)
                edges.append(Edge(
                    parent_id,
                    child_id,
                    "contains",
                    confidence=0.95,
                    provenance="tree_sitter",
                    source_location=f"{source.rel}:{child.line}",
                ))

def _add_returns(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    for source, defs, _root in defs_by_file:
        text = source.text.encode("utf-8", errors="replace")
        for d in defs:
            if d.kind not in {"function", "method"}:
                continue
            src_id = _definition_node_id(source, d)
            if src_id not in nodes:
                continue
            for return_type in _return_type_names(_node_text_range(text, d.start, d.end)):
                targets = name_to_symbols.get(return_type, [])
                if len(targets) != 1 or targets[0] == src_id:
                    continue
                edges.append(Edge(
                    src_id,
                    targets[0],
                    "returns",
                    confidence=0.9,
                    provenance="tree_sitter",
                    source_location=f"{source.rel}:{d.line}",
                ))

def _add_tree_sitter_callback_references(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    """Weak `references` edges for names passed as bare call arguments.

    Not a `calls` edge -- passing a function's name as a callback argument
    doesn't prove it's ever actually invoked, unlike a direct `name(...)`
    call site. This exists so a callback-only function (never called
    directly, only registered via e.g. `SetMainCallback2(CB2_InitBattle)`)
    shows up as connected/used rather than reading as isolated/dead, which
    is genuinely misleading for codebases that lean on function-pointer
    dispatch (common in C, and callback-heavy JS).
    """
    unique_callables = {
        name: ids[0] for name, ids in name_to_symbols.items()
        if len(ids) == 1 and nodes[ids[0]].kind in {"function", "method"}
    }
    if not unique_callables:
        return

    for source, defs, root in defs_by_file:
        src_lang = _lang_family(source.rel)
        callable_defs = [d for d in sorted(defs, key=lambda d: d.start) if d.kind in {"function", "method"}]
        for d in callable_defs:
            src_id = _definition_node_id(source, d)
            if src_id not in nodes:
                continue
            for name in _callback_arg_names_in_range(
                root, source.text.encode("utf-8", errors="replace"), d.start, d.end
            ):
                tgt_id = unique_callables.get(name)
                if not tgt_id or tgt_id == src_id:
                    continue
                tgt_node = nodes.get(tgt_id)
                tgt_lang = _lang_family(tgt_node.path) if tgt_node else None
                if src_lang is not None and tgt_lang is not None and src_lang != tgt_lang:
                    continue
                edges.append(Edge(src_id, tgt_id, "references", confidence=0.6, provenance="tree_sitter_callback_ref"))

def _add_tree_sitter_calls(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> _MemberCallStats:
    # 1. Identify globally unique callables
    unique_callables = {
        name: ids[0] for name, ids in name_to_symbols.items()
        if len(ids) == 1 and nodes[ids[0]].kind in {"function", "method"}
    }
    reexports = _reexported_symbols(defs_by_file, nodes, edges)

    # Repo-wide map of function name -> its single concrete return type, used
    # to type inline call receivers (`parse_ir(src).lower()`, normalized to
    # the key `parse_ir()`). Names returning more than one concrete type are
    # dropped: an ambiguous return is not receiver evidence.
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
    call_receiver_types = {
        f"{name}()": next(iter(types))
        for name, types in return_types_by_name.items()
        if len(types) == 1
    }

    stats = _MemberCallStats()
    for source, defs, root in defs_by_file:
        suffix = source.path.suffix.lower()
        imported_sources = _imported_symbol_sources(suffix, source.text)
        src_lang = _lang_family(source.rel)
        
        # Build local resolutions dictionary starting with globally unique callables
        local_resolutions = dict(unique_callables)

        # 2. Add locally imported symbols, using module stem matching for disambiguation
        all_imported = _imported_symbol_names(suffix, source.text)
        for name in all_imported:
            targets = name_to_symbols.get(name, [])
            target = _select_import_target(
                name,
                targets,
                imported_sources.get(name),
                nodes,
                src_lang,
                reexports,
            )
            if target:
                local_resolutions[name] = target
        callable_defs = [d for d in sorted(defs, key=lambda d: d.start) if d.kind in {"function", "method"}]
        rust_field_types: dict[tuple[str, str], str] = {}
        python_field_types: dict[tuple[str, str], str] = {}
        if suffix == ".rs":
            text_bytes = source.text.encode("utf-8", errors="replace")
            for struct in (item for item in defs if item.kind == "struct"):
                for field_name, field_type, _line in _rust_fields_in_range(
                    root,
                    text_bytes,
                    struct.start,
                    struct.end,
                ):
                    if field_type:
                        rust_field_types[(struct.name, field_name)] = field_type
        elif suffix == ".py":
            python_field_types = _python_class_field_types(source.text)
        for d in callable_defs:
            src_id = _definition_node_id(source, d)
            if src_id not in nodes:
                continue
            text_bytes = source.text.encode("utf-8", errors="replace")
            body = _node_text_range(text_bytes, d.start, d.end)
            if suffix == ".rs":
                local_types = _rust_local_types(body)
                local_types.update(call_receiver_types)
            elif suffix == ".py":
                local_types = _python_local_types(body)
            else:
                local_types = {}
            if d.owner:
                local_types["self"] = d.owner
                if suffix == ".py":
                    local_types["cls"] = d.owner
                field_types = rust_field_types if suffix == ".rs" else python_field_types
                local_types.update(
                    {
                        f"self.{field_name}": field_type
                        for (owner, field_name), field_type in field_types.items()
                        if owner == d.owner
                    }
                )
            calls = _call_sites_in_range(root, text_bytes, d.start, d.end)
            rust_macro_calls = (
                {
                    _CallSite(name=name, qualified=False)
                    for name in _rust_macro_bare_call_names_in_range(
                        root,
                        text_bytes,
                        d.start,
                        d.end,
                    )
                }
                if suffix == ".rs"
                else set()
            )
            calls.update(rust_macro_calls)
            for call in calls:
                if call.qualified:
                    outcome = _resolve_member_call(
                        source=source,
                        source_id=src_id,
                        call=call,
                        receiver_types=local_types,
                        nodes=nodes,
                        name_to_symbols=name_to_symbols,
                        edges=edges,
                    )
                    stats = stats.add(outcome)
                    continue
                tgt_id = (
                    _resolve_path_qualified_target(call, name_to_symbols, nodes)
                    if call.qualifier
                    else None
                ) or local_resolutions.get(call.name)
                if not tgt_id or tgt_id == src_id:
                    continue
                tgt_node = nodes.get(tgt_id)
                tgt_lang = _lang_family(tgt_node.path) if tgt_node else None
                if src_lang is not None and tgt_lang is not None and src_lang != tgt_lang:
                    continue
                edges.append(Edge(
                    src_id,
                    tgt_id,
                    "calls",
                    confidence=(
                        0.96
                        if call.qualifier
                        else 0.88
                        if call in rust_macro_calls
                        else 0.9
                    ),
                    provenance=(
                        "tree_sitter_path_resolved"
                        if call.qualifier
                        else "tree_sitter_macro_token_tree"
                        if call in rust_macro_calls
                        else "tree_sitter"
                    ),
                ))
    return stats

def _add_imports_from(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    unresolved: list[tuple[SourceFile, str, list[str], str | None, str | None]] = []
    for source, _defs, _root in defs_by_file:
        suffix = source.path.suffix.lower()
        src_lang = _lang_family(source.rel)
        imported_names = _imported_symbol_names(suffix, source.text)
        imported_sources = _imported_symbol_sources(suffix, source.text)

        for name in imported_names:
            targets = name_to_symbols.get(name, [])
            stem = imported_sources.get(name)
            target = _select_import_target(name, targets, stem, nodes, src_lang, {})

            if target and not target.startswith(source.file_node_id + "__"):
                edges.append(Edge(
                    source.file_node_id,
                    target,
                    "imports_from",
                    confidence=0.85,
                    provenance="tree_sitter",
                    source_location=source.rel,
                ))
            elif targets:
                unresolved.append((source, name, targets, stem, src_lang))

    reexports = _reexported_symbols(defs_by_file, nodes, edges)
    for source, name, targets, stem, src_lang in unresolved:
        target = _select_import_target(name, targets, stem, nodes, src_lang, reexports)
        if target and not target.startswith(source.file_node_id + "__"):
            edges.append(Edge(
                source.file_node_id,
                target,
                "imports_from",
                confidence=0.85,
                provenance="tree_sitter_reexport",
                source_location=source.rel,
            ))
