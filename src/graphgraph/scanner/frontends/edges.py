"""Relation builders that turn resolved syntax into graph edges."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ...graph.core import Edge, Node
from ..ast import _lang_family
from .cpp import cpp_class_field_types, cpp_local_types
from .csharp import csharp_class_field_types, csharp_local_types
from .languages import _SUFFIX_LANGUAGE
from .model import (
    SourceFile,
    _CallSite,
    _MemberCallStats,
    _TsDef,
)
from .module_calls import (
    module_alias_targets,
    resolve_module_qualified_call,
    whole_module_binding_names,
)
from .python import (
    _python_attribute_uses,
    _python_class_field_types,
    _python_fixture_return_types,
    _python_imported_global_facts,
    _python_imported_return_facts,
    _python_local_types,
    _python_module_global_facts,
    _python_module_return_facts,
    _python_parameter_names,
)
from .rust import (
    _rust_fields_in_range,
    _rust_local_call_return_types,
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
    _syntax_text_without_literals,
)
from .type_facts import Evidence, TypeFact, join_type_fact_maps
from .typescript import (
    _ts_class_field_types,
    _ts_local_call_return_types,
    _ts_local_types,
    _ts_return_type_from_body,
)

_TS_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
_CPP_SUFFIXES = frozenset({".cpp", ".cxx", ".cc", ".h", ".hh", ".hpp"})


def _add_tree_sitter_implements(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
    nodes: dict[str, Node] | None = None,
) -> None:
    nodes = nodes if nodes is not None else {}
    for source, defs, _root in defs_by_file:
        for d in defs:
            # Rust `impl Trait for Type` encodes (trait, type) in extra.
            if d.kind == "impl_block" and len(d.extra) == 2:
                trait_name, type_name = d.extra
                if not trait_name:
                    continue
                for type_id in name_to_symbols.get(type_name, []):
                    for trait_id in name_to_symbols.get(trait_name, []):
                        if type_id != trait_id:
                            edges.append(
                                Edge(type_id, trait_id, "implements", confidence=0.95, provenance="tree_sitter")
                            )
                continue
            # Class inheritance: `class Flask(App)` stores its base names in
            # extra. Without these edges a call on a typed receiver can only
            # match a method owned by that exact class, so every inherited
            # call is unresolvable even though both ends are in the graph.
            if d.kind != "class" or not d.extra:
                continue
            child_id = _definition_node_id(source, d)
            if child_id not in nodes:
                continue
            for base_name in d.extra:
                base_ids = name_to_symbols.get(base_name, [])
                # Ambiguous base names would attach the wrong hierarchy; a
                # single definition is the only safe attribution.
                if len(base_ids) != 1 or base_ids[0] == child_id:
                    continue
                if nodes.get(base_ids[0]) is not None and nodes[base_ids[0]].kind == "class":
                    edges.append(
                        Edge(
                            child_id,
                            base_ids[0],
                            "implements",
                            confidence=0.95,
                            provenance="tree_sitter_base_class",
                            source_location=f"{source.rel}:{d.line}",
                        )
                    )


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
                parent
                for parent in materialized
                if parent.kind in owner_kinds and parent.start < child.start and child.end <= parent.end
            ]
            if not parents:
                continue
            parent = min(parents, key=lambda d: d.end - d.start)
            parent_id = _definition_node_id(source, parent)
            child_id = _definition_node_id(source, child)
            if parent_id != child_id:
                nodes[child_id] = replace(nodes[child_id], parent=parent_id)
                edges.append(
                    Edge(
                        parent_id,
                        child_id,
                        "contains",
                        confidence=0.95,
                        provenance="tree_sitter",
                        source_location=f"{source.rel}:{child.line}",
                    )
                )


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
            # Prefer the parser's own annotation; fall back to scanning source
            # only for defs that predate it (regex frontend, restored graphs).
            annotation = d.return_type or _node_text_range(text, d.start, d.end)
            for return_type in _return_type_names(annotation, is_annotation=bool(d.return_type)):
                targets = name_to_symbols.get(return_type, [])
                if len(targets) != 1 or targets[0] == src_id:
                    continue
                edges.append(
                    Edge(
                        src_id,
                        targets[0],
                        "returns",
                        confidence=0.9,
                        provenance="tree_sitter",
                        source_location=f"{source.rel}:{d.line}",
                    )
                )


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
        name: ids[0]
        for name, ids in name_to_symbols.items()
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


def _file_field_types(
    source: SourceFile,
    defs: list[_TsDef],
    root: Any,
) -> dict[tuple[str, str], str]:
    """`(owner, field) -> declared type` for one file, in any supported language."""
    suffix = source.path.suffix.lower()
    if suffix == ".rs":
        text_bytes = source.text.encode("utf-8", errors="replace")
        fields: dict[tuple[str, str], str] = {}
        for struct in (item for item in defs if item.kind == "struct"):
            for field_name, field_type, _line in _rust_fields_in_range(
                root, text_bytes, struct.start, struct.end
            ):
                if field_type:
                    fields[(struct.name, field_name)] = field_type
        return fields
    if suffix == ".py":
        return dict(_python_class_field_types(source.text))
    if suffix in _TS_SUFFIXES:
        return dict(_ts_class_field_types(source.text))
    if suffix in {".cs", ".java"}:
        return dict(csharp_class_field_types(source.text))
    if suffix in _CPP_SUFFIXES:
        return dict(cpp_class_field_types(source.text))
    return {}


def _project_field_types(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
) -> dict[tuple[str, str], str]:
    """Repo-wide `(owner, field) -> type`, with ambiguous declarations dropped.

    A field declaration has to be visible outside the file that declares it:
    `app = ctx.app` in `templating.py` needs `AppContext.app` from `ctx.py`.
    Confining this map to one file made the join a near no-op -- measured at one
    additional resolved call across flask, requests, and mem0.

    Two different declarations of the same `(owner, field)` -- distinct classes
    that happen to share a name -- are dropped rather than arbitrated, the same
    discipline `return_types_by_name` uses. An ambiguous field is not receiver
    evidence, and inventing one here would spend the precision this resolver
    exists to protect.
    """
    return {
        key: concrete
        for key, fact in _project_field_type_facts(defs_by_file).items()
        if (concrete := fact.concrete) is not None
    }


def _project_field_type_facts(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
) -> dict[tuple[str, str], TypeFact]:
    """Repo-wide field facts retaining source provenance and ambiguity."""
    result: dict[tuple[str, str], TypeFact] = {}
    for source, defs, root in defs_by_file:
        for (owner, field), field_type in _file_field_types(source, defs, root).items():
            if not field_type:
                continue
            key = (owner, field)
            fact = TypeFact.from_evidence(
                field_type,
                Evidence("field_type", f"{source.rel}:{owner}.{field}"),
            )
            result[key] = result.get(key, TypeFact()).join(fact)
    return result


def _project_python_global_types(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
) -> dict[tuple[str, str], str]:
    """Repo-wide annotated module globals keyed by module provenance."""
    return {
        key: concrete
        for key, fact in _project_python_global_type_facts(defs_by_file).items()
        if (concrete := fact.concrete) is not None
    }


def _project_python_global_type_facts(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
) -> dict[tuple[str, str], TypeFact]:
    """Repo-wide annotated module-global facts retaining ambiguity."""
    result: dict[tuple[str, str], TypeFact] = {}
    for source, _defs, _root in defs_by_file:
        if source.path.suffix.lower() != ".py":
            continue
        module_stem = source.path.stem
        for name, fact in _python_module_global_facts(source.text, source.rel).items():
            key = (module_stem, name)
            result[key] = result.get(key, TypeFact()).join(fact)
    return _join_python_package_reexports(
        defs_by_file,
        result,
        _python_imported_global_facts,
    )


def _project_python_return_facts(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
) -> dict[tuple[str, str], TypeFact]:
    """Repo-wide Python return facts keyed by module provenance and symbol."""
    result: dict[tuple[str, str], TypeFact] = {}
    for source, _defs, _root in defs_by_file:
        if source.path.suffix.lower() != ".py":
            continue
        for name, fact in _python_module_return_facts(source.text, source.rel).items():
            key = (source.path.stem, name)
            result[key] = result.get(key, TypeFact()).join(fact)
    return _join_python_package_reexports(
        defs_by_file,
        result,
        _python_imported_return_facts,
    )


def _join_python_package_reexports(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    direct_facts: Mapping[tuple[str, str], TypeFact],
    import_facts: Callable[
        [str, Mapping[tuple[str, str], TypeFact]],
        dict[str, TypeFact],
    ],
) -> dict[tuple[str, str], TypeFact]:
    """Propagate facts through package ``__init__`` re-exports.

    The finite worklist is bounded by package count. Each successful join is
    monotone, and a package key is derived from its directory rather than from
    a global symbol-name match.
    """
    result = dict(direct_facts)
    packages = [
        source
        for source, _defs, _root in defs_by_file
        if source.path.suffix.lower() == ".py" and source.path.name == "__init__.py"
    ]
    remaining_rounds = len(packages)
    changed = True
    while changed and remaining_rounds:
        changed = False
        remaining_rounds -= 1
        for source in packages:
            package_name = source.path.parent.name
            for local_name, fact in import_facts(source.text, result).items():
                key = (package_name, local_name)
                joined = result.get(key, TypeFact()).join(fact)
                if joined != result.get(key, TypeFact()):
                    result[key] = joined
                    changed = True
    return result


def _add_tree_sitter_calls(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> _MemberCallStats:
    # 1. Identify globally unique callables
    unique_callables = {
        name: ids[0]
        for name, ids in name_to_symbols.items()
        if len(ids) == 1 and nodes[ids[0]].kind in {"function", "method"}
    }
    reexports = _reexported_symbols(defs_by_file, nodes, edges)

    # Class name -> declared base names, so a call on a typed receiver can find
    # a method defined on an ancestor. Without it, resolution requires the
    # method to be owned by the receiver's exact class, and every inherited
    # call fails with both ends already present in the graph.
    base_classes: dict[str, tuple[str, ...]] = {}
    for _source, defs, _root in defs_by_file:
        for definition in defs:
            if definition.kind == "class" and definition.extra:
                base_classes.setdefault(definition.name, tuple(definition.extra))

    project_field_types = _project_field_type_facts(defs_by_file)
    project_python_globals = _project_python_global_type_facts(defs_by_file)
    project_python_returns = _project_python_return_facts(defs_by_file)

    # Repo-wide map of function name -> its single concrete return type, used
    # to type inline call receivers (`parse_ir(src).lower()`, normalized to
    # the key `parse_ir()`). Names returning more than one concrete type are
    # dropped: an ambiguous return is not receiver evidence.
    return_types_by_name: dict[str, set[str]] = {}
    for source, defs, _root in defs_by_file:
        source_suffix = source.path.suffix.lower()
        if source_suffix not in ({".rs"} | _TS_SUFFIXES):
            continue
        text_bytes = source.text.encode("utf-8", errors="replace")
        for definition in (item for item in defs if item.kind in {"function", "method"}):
            body_text = _node_text_range(text_bytes, definition.start, definition.end)
            # Rust reads the `-> Type` annotation; JS/TS has none, so infer the
            # factory return type from `return new X()` in the body.
            return_type = (
                _return_type_name(body_text) if source_suffix == ".rs" else _ts_return_type_from_body(body_text)
            )
            if return_type:
                return_types_by_name.setdefault(definition.name, set()).add(return_type)
    unique_return_types = {name: next(iter(types)) for name, types in return_types_by_name.items() if len(types) == 1}
    fixture_return_types_by_name: dict[str, set[str]] = {}
    for source, _defs, _root in defs_by_file:
        if source.path.suffix.lower() != ".py":
            continue
        for name, type_name in _python_fixture_return_types(source.text).items():
            fixture_return_types_by_name.setdefault(name, set()).add(type_name)
    unique_fixture_return_types = {
        name: next(iter(types)) for name, types in fixture_return_types_by_name.items() if len(types) == 1
    }
    call_receiver_types = {f"{name}()": value for name, value in unique_return_types.items()}

    stats = _MemberCallStats()
    for source, defs, root in defs_by_file:
        suffix = source.path.suffix.lower()
        language = _SUFFIX_LANGUAGE.get(suffix, suffix.lstrip(".") or "unknown")
        imported_sources = _imported_symbol_sources(suffix, source.text)
        module_aliases = module_alias_targets(suffix, source.text)
        # Names bound to an entire imported module. A bare call to one of these
        # invokes the module, never a same-named method defined nearby. Member
        # bindings are excluded: those name a real exported symbol and must stay
        # resolvable.
        import_bound_names = whole_module_binding_names(suffix, source.text)
        src_lang = _lang_family(source.rel)
        python_initial_facts: dict[str, TypeFact] = {}
        python_call_return_facts: dict[str, TypeFact] = {}
        if suffix == ".py":
            # These are file facts, not callable facts. Parsing the complete
            # module inside the callable loop changes the work from one parse
            # per file to one parse per callable and made a 37-file Requests
            # scan exceed 60 seconds.
            python_initial_facts = join_type_fact_maps(
                _python_module_global_facts(source.text, source.rel),
                _python_imported_global_facts(source.text, project_python_globals),
            )
            python_call_return_facts = join_type_fact_maps(
                _python_module_return_facts(source.text, source.rel),
                _python_imported_return_facts(source.text, project_python_returns),
            )

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
        ts_field_types: dict[tuple[str, str], str] = {}
        csharp_field_types: dict[tuple[str, str], str] = {}
        cpp_field_types: dict[tuple[str, str], str] = {}
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
        elif suffix in _TS_SUFFIXES:
            ts_field_types = _ts_class_field_types(source.text)
        elif suffix in {".cs", ".java"}:
            csharp_field_types = csharp_class_field_types(source.text)
        elif suffix in _CPP_SUFFIXES:
            cpp_field_types = cpp_class_field_types(source.text)
        for d in callable_defs:
            src_id = _definition_node_id(source, d)
            if src_id not in nodes:
                continue
            text_bytes = source.text.encode("utf-8", errors="replace")
            # Blank comments and string literals before pattern-matching the
            # body. Commented-out code and code inside strings otherwise read
            # as real declarations: `// let fake: Wrong = x` typed a local
            # named `fake`, which then attached calls to whatever class
            # `Wrong` named. The parse tree already marks these regions.
            # Only the pattern-matching extractors need this. Python's uses a
            # real AST parse, which already ignores comments and string
            # contents -- and blanking literals leaves whitespace that its
            # parser then rejects outright.
            raw_body = _node_text_range(text_bytes, d.start, d.end)
            body = (
                _syntax_text_without_literals(d.node, text_bytes)
                if d.node is not None and suffix != ".py"
                else raw_body
            )
            if suffix in _TS_SUFFIXES:
                local_types = _ts_local_types(body)
                # `const s = createStore();` -- bind the local to the factory's
                # inferred return type, unless a stronger annotation/`new` type
                # was already found (setdefault preserves the direct evidence).
                for binding, inferred in _ts_local_call_return_types(body, unique_return_types).items():
                    local_types.setdefault(binding, inferred)
            elif suffix == ".rs":
                local_types = _rust_local_types(body)
                # `let ir = parse_ir(src);` -- bind the local to the callee's
                # return type, but only where nothing stronger is known.
                # A declared annotation or parameter type is direct evidence;
                # a return type is inferred, and letting it overwrite the
                # former loses real resolutions (measured: -83 calls edges,
                # while the resolved/unknown *ratio* rose, because displaced
                # sites fall out of that ratio's denominator entirely).
                for binding, inferred in _rust_local_call_return_types(body, unique_return_types).items():
                    local_types.setdefault(binding, inferred)
                for binding, inferred in call_receiver_types.items():
                    local_types.setdefault(binding, inferred)
            elif suffix == ".py":
                # Field types let an attribute-valued assignment (`app = ctx.app`)
                # carry the declared type of the field it reads. Without them a
                # receiver bound this way stayed untyped even when both its
                # receiver's type and that field were already known.
                local_types = _python_local_types(
                    body,
                    field_types=project_field_types,
                    owner=d.owner or "",
                    initial_facts=python_initial_facts,
                    call_return_facts=python_call_return_facts,
                )
                normalized_path = "/" + source.rel.replace("\\", "/").casefold()
                if "/tests/" in normalized_path or Path(source.rel).name.casefold().startswith("test_"):
                    # Pytest fixture injection binds a test parameter to the
                    # same-named fixture function's return value. Only accept
                    # a repository-unique concrete return type.
                    for parameter in _python_parameter_names(body):
                        if inferred := unique_fixture_return_types.get(parameter):
                            local_types.setdefault(parameter, inferred)
            elif suffix in {".cs", ".java"}:
                # Java shares C#'s declaration shapes (`Type x`, `new Type()`,
                # typed params), so the same inference serves both.
                local_types = csharp_local_types(body)
            elif suffix in _CPP_SUFFIXES:
                local_types = cpp_local_types(body)
            else:
                local_types = {}
            if d.owner:
                local_types["self"] = d.owner
                if suffix == ".py":
                    local_types["cls"] = d.owner
                # C#/Java/TS/C++ spell the enclosing-instance receiver `this`,
                # not `self`; without this a `this.Method()` / `this->Method()`
                # call never resolved to its own class.
                if suffix in _TS_SUFFIXES or suffix in {".cs", ".java"} or suffix in _CPP_SUFFIXES:
                    local_types["this"] = d.owner
                field_types = (
                    ts_field_types
                    if suffix in _TS_SUFFIXES
                    else rust_field_types
                    if suffix == ".rs"
                    else csharp_field_types
                    if suffix in {".cs", ".java"}
                    else cpp_field_types
                    if suffix in _CPP_SUFFIXES
                    else python_field_types
                )
                owner_fields = {
                    field_name: field_type
                    for (owner, field_name), field_type in field_types.items()
                    if owner == d.owner
                }
                # The enclosing-instance receiver is spelled differently per
                # language, and C#/Java also read fields *bare* (`_repo.M()`,
                # not `this._repo.M()`).
                if suffix in {".cs", ".java"}:
                    qualified_prefix, bare_access = "this.", True
                elif suffix in _TS_SUFFIXES:
                    qualified_prefix, bare_access = "this.", False
                elif suffix in _CPP_SUFFIXES:
                    qualified_prefix, bare_access = "this->", True
                else:  # rust, python
                    qualified_prefix, bare_access = "self.", False
                local_types.update(
                    {f"{qualified_prefix}{field_name}": field_type for field_name, field_type in owner_fields.items()}
                )
                if bare_access:
                    # A real local of the same name is stronger evidence, so
                    # setdefault lets the already-populated local win.
                    for field_name, field_type in owner_fields.items():
                        local_types.setdefault(field_name, field_type)
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
                    # Try import-aware module.func() resolution before the
                    # receiver-type resolver. It only binds when a top-level
                    # symbol of the imported module matches, so obj.method()
                    # calls find nothing here and fall through untouched.
                    module_target = resolve_module_qualified_call(
                        call.receiver,
                        call.name,
                        module_aliases,
                        name_to_symbols,
                        nodes,
                        src_id,
                        src_lang,
                        reexports,
                    )
                    if module_target:
                        edges.append(
                            Edge(
                                src_id,
                                module_target,
                                "calls",
                                confidence=0.94,
                                provenance="tree_sitter_module_qualified",
                                source_location=source.rel,
                                evidence=f"module {call.receiver}.{call.name}",
                            )
                        )
                        stats = stats.add("resolved", call.receiver, language)
                        continue
                    outcome = _resolve_member_call(
                        source=source,
                        source_id=src_id,
                        call=call,
                        receiver_types=local_types,
                        nodes=nodes,
                        name_to_symbols=name_to_symbols,
                        edges=edges,
                        base_classes=base_classes,
                    )
                    stats = stats.add(outcome, call.receiver, language)
                    continue
                tgt_id = (
                    _resolve_path_qualified_target(call, name_to_symbols, nodes) if call.qualifier else None
                ) or local_resolutions.get(call.name)
                if not tgt_id or tgt_id == src_id:
                    continue
                tgt_node = nodes.get(tgt_id)
                # A bare call cannot reach a method: methods are invoked through
                # a receiver, and that form is `call.qualified`, handled above.
                # Without this, express's `var send = require('send')` followed
                # by `send(req, path, opts)` bound to the local `res.send`
                # method -- a real cross-module false positive, and the only
                # precision defect the multi-language gray-box run found.
                if (
                    not call.qualifier
                    and tgt_node is not None
                    and tgt_node.kind == "method"
                    and call.name in import_bound_names
                ):
                    continue
                tgt_lang = _lang_family(tgt_node.path) if tgt_node else None
                if src_lang is not None and tgt_lang is not None and src_lang != tgt_lang:
                    continue
                edges.append(
                    Edge(
                        src_id,
                        tgt_id,
                        "calls",
                        confidence=(0.96 if call.qualifier else 0.88 if call in rust_macro_calls else 0.9),
                        provenance=(
                            "tree_sitter_path_resolved"
                            if call.qualifier
                            else "tree_sitter_macro_token_tree"
                            if call in rust_macro_calls
                            else "tree_sitter"
                        ),
                    )
                )
            if suffix == ".py":
                normalized_path = "/" + source.rel.replace("\\", "/").casefold()
                if "/tests/" not in normalized_path and not Path(source.rel).name.casefold().startswith("test_"):
                    continue
                existing = {(edge.source, edge.target, edge.type) for edge in edges}
                for receiver, field_name, relation, line in _python_attribute_uses(body):
                    receiver_type = local_types.get(receiver, "")
                    if not receiver_type:
                        continue
                    candidates = [
                        node_id
                        for node_id in name_to_symbols.get(field_name, ())
                        if node_id != src_id
                        and (node := nodes.get(node_id)) is not None
                        and node.kind in {"field", "method", "property"}
                        and _lang_family(node.path) == src_lang
                        and node.parent in nodes
                        and nodes[node.parent].label == receiver_type
                    ]
                    if len(candidates) != 1:
                        continue
                    key = (src_id, candidates[0], relation)
                    if key in existing:
                        continue
                    existing.add(key)
                    edges.append(
                        Edge(
                            src_id,
                            candidates[0],
                            relation,
                            confidence=0.94,
                            provenance="python_ast_typed_attribute_use",
                            source_location=f"{source.rel}:{line or d.line}",
                            evidence=f"pytest fixture receiver {receiver}:{receiver_type}.{field_name}",
                        )
                    )
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
                edges.append(
                    Edge(
                        source.file_node_id,
                        target,
                        "imports_from",
                        confidence=0.85,
                        provenance="tree_sitter",
                        source_location=source.rel,
                    )
                )
            elif targets:
                unresolved.append((source, name, targets, stem, src_lang))

    reexports = _reexported_symbols(defs_by_file, nodes, edges)
    for source, name, targets, stem, src_lang in unresolved:
        target = _select_import_target(name, targets, stem, nodes, src_lang, reexports)
        if target and not target.startswith(source.file_node_id + "__"):
            edges.append(
                Edge(
                    source.file_node_id,
                    target,
                    "imports_from",
                    confidence=0.85,
                    provenance="tree_sitter_reexport",
                    source_location=source.rel,
                )
            )
