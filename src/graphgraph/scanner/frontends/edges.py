"""Relation builders that turn resolved syntax into graph edges."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ...graph.core import Edge, Node
from ..ast import _lang_family
from .binding_providers import (
    DIRECT_FIELD_BINDING_PRIORITY,
    ENCLOSING_INSTANCE_PRIORITY,
    FIELD_BINDING_PRIORITY,
    FieldBindingContext,
    LocalBindingContext,
    field_bindings,
    local_bindings,
)
from .grammars import profile_for_suffix
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
from .persistent_facts import PythonProjectTypeFacts
from .python import (
    _python_attribute_uses,
    _python_fixture_return_types,
    _python_imported_global_facts,
    _python_imported_return_facts,
    _python_module_global_facts,
    _python_module_return_facts,
)
from .rust import (
    _rust_macro_bare_call_names_in_range,
)
from .scope_graph import ScopeGraph, type_scope
from .syntax import (
    _call_sites_in_range,
    _callback_arg_names_in_range,
    _definition_node_id,
    _imported_symbol_modules,
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
    _ts_return_type_from_body,
)

_TS_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
_CPP_SUFFIXES = frozenset({".cpp", ".cxx", ".cc", ".h", ".hh", ".hpp"})


def _unique_callables_for_language(
    name_to_symbols: Mapping[str, list[str]],
    nodes: Mapping[str, Node],
    language: str | None,
) -> dict[str, str]:
    """Return names with one callable candidate in the source language.

    Symbol labels are not globally unique across a polyglot repository. A
    Python ``middle`` must not make a same-named Rust or JavaScript function
    ambiguous; cross-language call edges are already forbidden. Partitioning
    the candidate relation by the same language-family invariant preserves
    soundness while recovering direct calls in every stratum.
    """
    result: dict[str, str] = {}
    for name, ids in name_to_symbols.items():
        compatible = [
            node_id
            for node_id in ids
            if (node := nodes.get(node_id)) is not None
            and node.kind in {"function", "method"}
            and _lang_family(node.path) == language
        ]
        if len(compatible) == 1:
            result[name] = compatible[0]
    return result


def _callable_receiver_owner(source: SourceFile, definition: _TsDef) -> str:
    """Owner key used only for member-call matching.

    Class names are project-visible nominal types. JavaScript property objects
    such as ``res`` and ``app`` are module-local structural namespaces unless
    an import proves otherwise, so include their file provenance. This keeps
    two unrelated ``res.send`` objects in different modules from linking by
    spelling alone.
    """
    if any(
        fact.startswith("javascript_owner:")
        for fact in definition.facts
    ):
        return f"{source.rel}::{definition.owner}"
    return definition.owner


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
            if not parents and child.kind == "method" and child.owner:
                # Go declares a method beside its type, not inside it, so
                # containment cannot be read off the byte ranges. The receiver
                # names the owner explicitly; bind to it when the file declares
                # exactly one type of that name. Ownership drives receiver
                # matching, so an ambiguous name must not be guessed.
                named = [
                    parent
                    for parent in materialized
                    if parent.name == child.owner and parent.kind in owner_kinds | {"type"}
                ]
                if len(named) == 1:
                    parents = named
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
    unique_by_language: dict[str | None, dict[str, str]] = {}

    for source, defs, root in defs_by_file:
        src_lang = _lang_family(source.rel)
        # `setdefault` evaluates its default eagerly, so passing the call
        # directly recomputed this repository-wide table once per *file*
        # rather than once per language, making resolution O(files x symbols).
        unique_callables = unique_by_language.get(src_lang)
        if unique_callables is None:
            unique_callables = _unique_callables_for_language(name_to_symbols, nodes, src_lang)
            unique_by_language[src_lang] = unique_callables
        if not unique_callables:
            continue
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
    language = _SUFFIX_LANGUAGE.get(suffix, suffix.lstrip(".") or "unknown")
    return field_bindings(
        language,
        FieldBindingContext(source, tuple(defs), root),
    )


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
    result, _scope_graph = _project_field_indexes(defs_by_file)
    return result


def _project_field_indexes(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
) -> tuple[dict[tuple[str, str], TypeFact], ScopeGraph]:
    """Build compatibility field facts and the language-partitioned scope graph."""

    result: dict[tuple[str, str], TypeFact] = {}
    scope_graph = ScopeGraph()
    for source, defs, root in defs_by_file:
        suffix = source.path.suffix.lower()
        language = _SUFFIX_LANGUAGE.get(suffix, suffix.lstrip(".") or "unknown")
        for definition in defs:
            if definition.kind not in {
                "class",
                "interface",
                "struct",
                "trait",
                "type",
            }:
                continue
            for base in definition.extra:
                if base:
                    scope_graph.add_parent(
                        type_scope(language, definition.name),
                        type_scope(language, base),
                    )
        for (owner, field), field_type in _file_field_types(source, defs, root).items():
            if not field_type:
                continue
            key = (owner, field)
            fact = TypeFact.from_evidence(
                field_type,
                Evidence("field_type", f"{source.rel}:{owner}.{field}"),
            )
            result[key] = result.get(key, TypeFact()).join(fact)
            scope_graph.add_binding(type_scope(language, owner), field, fact)
    return result, scope_graph


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
    *,
    python_project_facts: PythonProjectTypeFacts | None = None,
) -> _MemberCallStats:
    # 1. Identify callables unique within each compatible language stratum.
    unique_by_language: dict[str | None, dict[str, str]] = {}
    reexports = _reexported_symbols(defs_by_file, nodes, edges)

    # Edge identity seen so far. This was rebuilt from the whole `edges` list
    # once per definition, making the scan quadratic in edge count: 2,252
    # rebuilds over a list past 12,000 edges on sympy/core, 11% of scan time.
    # Since `edges` is appended to here and in `_resolve_member_call`, the set
    # catches up on whatever arrived since it last looked rather than requiring
    # every appender to record its key -- correct no matter who appends, and
    # O(total edges) per scan instead of O(definitions x edges).
    existing_edge_keys: set[tuple[str, str, str]] = set()
    absorbed_edge_count = 0

    project_field_types, scope_graph = _project_field_indexes(defs_by_file)
    project_python_globals = _project_python_global_type_facts(defs_by_file)
    project_python_returns = _project_python_return_facts(defs_by_file)
    if python_project_facts is not None:
        # Fresh and restored contributions use the same idempotent join.  The
        # fresh subset is retained above for direct extractor use in tests and
        # for non-Python field facts; duplicate Python evidence is harmless.
        for key, fact in python_project_facts.fields.items():
            project_field_types[key] = project_field_types.get(key, TypeFact()).join(fact)
            owner, field = key
            scope_graph.add_binding(type_scope("python", owner), field, fact)
        for key, fact in python_project_facts.globals.items():
            project_python_globals[key] = project_python_globals.get(key, TypeFact()).join(fact)
        for key, fact in python_project_facts.returns.items():
            project_python_returns[key] = project_python_returns.get(key, TypeFact()).join(fact)

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
        imported_modules = _imported_symbol_modules(suffix, source.text)
        module_aliases = module_alias_targets(suffix, source.text)
        # Names bound to an entire imported module. A bare call to one of these
        # invokes the module, never a same-named method defined nearby. Member
        # bindings are excluded: those name a real exported symbol and must stay
        # resolvable.
        import_bound_names = whole_module_binding_names(suffix, source.text)
        src_lang = _lang_family(source.rel)
        # See the note in the pass above: `setdefault` evaluated its default on
        # every iteration, so this repository-wide table was rebuilt per file.
        unique_callables = unique_by_language.get(src_lang)
        if unique_callables is None:
            unique_callables = _unique_callables_for_language(name_to_symbols, nodes, src_lang)
            unique_by_language[src_lang] = unique_callables
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
                source.rel,
                imported_modules.get(name, ""),
                suffix,
            )
            if target:
                local_resolutions[name] = target
        # 3. File-local definitions bind tighter than any repository-wide guess.
        # A bare call to `N` inside a file that also defines `N` means *that*
        # `N`. Without this layer the name has to be globally unique within its
        # language to resolve at all, so merely *adding* an unrelated file that
        # defines the same name deleted a correct same-file edge elsewhere in
        # the repository (measured: -19 edges on Flask from one added copy).
        # Only plain functions are bound: a bare call cannot reach a method.
        # An explicit import of the same name is a real rebinding, so it wins.
        for local_def in defs:
            # An ownerless "method" is a free function under another name:
            # Ruby's top-level `def` parses as a method but belongs to no type,
            # and a bare call reaches it exactly as it would a function. Methods
            # that do have an owner are handled by the class scope above.
            free_callable = local_def.kind == "function" or (
                local_def.kind == "method" and not local_def.owner
            )
            if not free_callable or local_def.name in all_imported:
                continue
            local_id = _definition_node_id(source, local_def)
            if local_id in nodes:
                local_resolutions[local_def.name] = local_id
        callable_defs = [d for d in sorted(defs, key=lambda d: d.start) if d.kind in {"function", "method"}]
        # Enclosing-class scope. In C#, Java, C++, Scala and Ruby an unqualified
        # call reaches a sibling member of the same class or object, so that
        # type is a real binding scope sitting between the file and the
        # repository. Python, JS/TS and Rust require an explicit receiver
        # (`self.`, `this.`, `Self::`), so adding them here would invent calls
        # the language cannot express.
        same_class_methods: dict[str, dict[str, str]] = {}
        if suffix in {".cs", ".java", ".scala", ".rb"} or suffix in _CPP_SUFFIXES:
            for method_def in defs:
                if method_def.kind != "method" or not method_def.owner:
                    continue
                method_id = _definition_node_id(source, method_def)
                if method_id in nodes:
                    same_class_methods.setdefault(method_def.owner, {})[method_def.name] = method_id
        # One encode per file. This was previously re-run for every callable in
        # the file, re-encoding the whole source once per definition.
        text_bytes = source.text.encode("utf-8", errors="replace")
        profile = profile_for_suffix(suffix)
        file_field_types = _file_field_types(source, defs, root)
        js_object_owners = frozenset(
            d.owner
            for d in defs
            if suffix in _TS_SUFFIXES and d.kind == "method" and d.owner
        )
        for d in callable_defs:
            src_id = _definition_node_id(source, d)
            if src_id not in nodes:
                continue
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
            if d.node is not None and suffix != ".py":
                # Collection already blanked this definition's literals; reusing
                # that avoids walking every descendant a second time. It is only
                # populated for callables, so anything else still computes here.
                body = d.literal_free_text or _syntax_text_without_literals(d.node, text_bytes)
            else:
                body = raw_body
            receiver_owner = _callable_receiver_owner(source, d) if d.owner else ""
            structural_owner = any(
                fact.startswith("javascript_owner:") for fact in d.facts
            )
            binds_structural_this = "javascript_this:assigned_owner" in d.facts
            binds_enclosing_receiver = bool(d.owner) and not (
                suffix in _TS_SUFFIXES
                and structural_owner
                and not binds_structural_this
            )
            bindings = local_bindings(
                LocalBindingContext(
                    language=language,
                    body=body,
                    source_rel=source.rel,
                    owner=d.owner or "",
                    receiver_owner=receiver_owner,
                    binds_enclosing_receiver=binds_enclosing_receiver,
                    structural_owners=js_object_owners,
                    field_types=project_field_types,
                    initial_facts=python_initial_facts,
                    call_return_facts=python_call_return_facts,
                    unique_return_types=unique_return_types,
                    call_receiver_types=call_receiver_types,
                    unique_fixture_return_types=unique_fixture_return_types,
                )
            )
            if d.owner:
                if binds_enclosing_receiver:
                    enclosing_fact = TypeFact.from_evidence(
                        receiver_owner,
                        Evidence(
                            "enclosing_instance",
                            f"{source.rel}:{d.owner}",
                        ),
                    )
                    for alias in profile.self_aliases:
                        bindings.bind(
                            alias,
                            enclosing_fact,
                            priority=ENCLOSING_INSTANCE_PRIORITY,
                        )

                direct_fields = {
                    field_name: TypeFact.from_evidence(
                        field_type,
                        Evidence(
                            "field_type",
                            f"{source.rel}:{d.owner}.{field_name}",
                        ),
                    )
                    for (owner, field_name), field_type in file_field_types.items()
                    if owner == d.owner and field_type
                }
                for field_name, fact in direct_fields.items():
                    for prefix in profile.field_receiver_prefixes:
                        bindings.bind(
                            f"{prefix}{field_name}",
                            fact,
                            priority=DIRECT_FIELD_BINDING_PRIORITY,
                        )
                    if profile.bare_field_receivers:
                        bindings.bind(
                            field_name,
                            fact,
                            priority=DIRECT_FIELD_BINDING_PRIORITY,
                        )

                inherited_fields = (
                    scope_graph.visible_bindings(
                        type_scope(language, d.owner),
                        include_start=False,
                    )
                    if profile.inherited_field_receivers
                    else {}
                )
                for field_name, resolution in inherited_fields.items():
                    if field_name in direct_fields:
                        continue
                    if resolution.fact.concrete is None:
                        continue
                    for prefix in profile.field_receiver_prefixes:
                        bindings.bind(
                            f"{prefix}{field_name}",
                            resolution.fact,
                            priority=FIELD_BINDING_PRIORITY,
                        )
                    if profile.bare_field_receivers:
                        bindings.bind(
                            field_name,
                            resolution.fact,
                            priority=FIELD_BINDING_PRIORITY,
                        )
            local_types = bindings.concrete_types
            calls = _call_sites_in_range(
                root,
                text_bytes,
                d.start,
                d.end,
                suffix=suffix,
            )
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
            # ``calls`` is a set because repeated sites collapse to one fact.
            # Sort the finite relation before projection so duplicate edges to
            # the same target retain deterministic receiver evidence across
            # processes and clean/incremental builds.
            for call in sorted(
                calls,
                key=lambda item: (
                    item.name,
                    item.qualified,
                    item.receiver,
                    item.qualifier,
                ),
            ):
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
                        scope_graph=scope_graph,
                    )
                    stats = stats.add(outcome, call.receiver, language)
                    continue
                tgt_id = (
                    _resolve_path_qualified_target(call, name_to_symbols, nodes) if call.qualifier else None
                ) or (
                    # Nearest scope first: the caller's own class, then the
                    # file, then the repository-wide unique name.
                    same_class_methods.get(d.owner, {}).get(call.name)
                    if not call.qualifier and d.owner
                    else None
                ) or local_resolutions.get(call.name)
                if not tgt_id:
                    # The graph defines this name somewhere but resolution could
                    # not choose. The call site is real and is being discarded,
                    # so record it: a caller count computed downstream is a
                    # lower bound, and "zero callers" must not read as proof.
                    if name_to_symbols.get(call.name):
                        stats = stats.add_bare_unmatched()
                    continue
                # A self-call is a real edge and the only evidence that a
                # function is recursive, so it is recorded rather than dropped.
                # Consumers that must not count it already exclude it:
                # `caller_counts` skips `source == target` so a dead recursive
                # function still reports zero production callers, and traversal
                # seeds its visited set with the start nodes so a self-loop
                # cannot revisit.
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
                if absorbed_edge_count < len(edges):
                    for edge in edges[absorbed_edge_count:]:
                        existing_edge_keys.add((edge.source, edge.target, edge.type))
                    absorbed_edge_count = len(edges)
                # `_python_attribute_uses` returns a set and the dedup key below
                # ignores receiver and line, so when one attribute is reached
                # from several places the surviving edge was whichever tuple the
                # set yielded first -- hash-seed dependent: 9 edges changed their
                # recorded line *and receiver* between PYTHONHASHSEED=0 and =1 on
                # sympy/core. Ordering by line makes the earliest use win.
                attribute_uses = sorted(
                    _python_attribute_uses(body),
                    key=lambda use: (use[3], use[0], use[1], use[2]),
                )
                for receiver, field_name, relation, line in attribute_uses:
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
                    if key in existing_edge_keys:
                        continue
                    existing_edge_keys.add(key)
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
    unresolved: list[tuple[SourceFile, str, list[str], str | None, str | None, str, str]] = []
    for source, _defs, _root in defs_by_file:
        suffix = source.path.suffix.lower()
        src_lang = _lang_family(source.rel)
        imported_names = _imported_symbol_names(suffix, source.text)
        imported_sources = _imported_symbol_sources(suffix, source.text)
        imported_modules = _imported_symbol_modules(suffix, source.text)

        for name in imported_names:
            targets = name_to_symbols.get(name, [])
            stem = imported_sources.get(name)
            specifier = imported_modules.get(name, "")
            target = _select_import_target(
                name, targets, stem, nodes, src_lang, {}, source.rel, specifier, suffix
            )

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
                unresolved.append((source, name, targets, stem, src_lang, specifier, suffix))

    reexports = _reexported_symbols(defs_by_file, nodes, edges)
    for source, name, targets, stem, src_lang, specifier, suffix in unresolved:
        target = _select_import_target(
            name, targets, stem, nodes, src_lang, reexports, source.rel, specifier, suffix
        )
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
