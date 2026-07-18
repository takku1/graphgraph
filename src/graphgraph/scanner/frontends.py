from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from ..graph.core import Edge, Node
from ..graph.operations import _dedupe_edges
from .ast import _is_context_symbol, _lang_family, extract_symbols

__all__ = [
    "FrontendCapability",
    "SourceFile",
    "ExtractionResult",
    "Extractor",
    "RegexExtractor",
    "TreeSitterExtractor",
    "DEFINITION_NODE_TYPES",
    "NAME_NODE_TYPES",
    "tree_sitter_available",
    "available_frontends",
    "parse_with_timeout",
    "parser_for_suffix",
    "select_extractor",
]


def _definition_summary(text: str, line: int) -> str:
    lines = text.splitlines()
    excerpt = lines[line - 1].strip() if 0 < line <= len(lines) else ""
    excerpt = re.sub(r"\s+", " ", excerpt)[:160]
    return f"L{line} {excerpt}".rstrip()


@dataclass(frozen=True)
class FrontendCapability:
    name: str
    available: bool
    confidence: float
    description: str


@dataclass(frozen=True)
class SourceFile:
    path: Path
    rel: str
    file_node_id: str
    text: str


@dataclass(frozen=True)
class ExtractionResult:
    nodes: dict[str, Node]
    edges: list[Edge]
    frontend: str
    truncated: bool = False
    fallback_files: tuple[str, ...] = ()
    failed_files: tuple[str, ...] = ()
    unsupported_files: tuple[str, ...] = ()
    timeout_files: tuple[str, ...] = ()
    parse_error_files: tuple[str, ...] = ()
    resolved_member_calls: int = 0
    ambiguous_member_calls: int = 0
    unresolved_member_calls: int = 0


class Extractor(Protocol):
    name: str
    confidence: float

    def extract_symbols(
        self,
        files: list[SourceFile],
        max_total_symbols: int,
        context_nodes: dict[str, Node] | None = None,
    ) -> ExtractionResult:
        ...


class RegexExtractor:
    name = "regex"
    confidence = 0.75

    def extract_symbols(
        self,
        files: list[SourceFile],
        max_total_symbols: int,
        context_nodes: dict[str, Node] | None = None,
    ) -> ExtractionResult:
        tuples = [(f.path, f.rel, f.file_node_id, f.text) for f in files]
        nodes, edges, truncated = extract_symbols(tuples, max_total_symbols=max_total_symbols, context_nodes=context_nodes)
        return ExtractionResult(nodes=nodes, edges=edges, frontend=self.name, truncated=truncated)


class TreeSitterExtractor:
    name = "tree_sitter"
    confidence = 0.95

    def __init__(self, *, fallback_on_error: bool = False, parse_timeout_micros: int = 2_000_000) -> None:
        self.fallback_on_error = fallback_on_error
        self.parse_timeout_micros = max(0, parse_timeout_micros)

    def extract_symbols(
        self,
        files: list[SourceFile],
        max_total_symbols: int,
        context_nodes: dict[str, Node] | None = None,
    ) -> ExtractionResult:
        context_ids = set((context_nodes or {}).keys())
        nodes: dict[str, Node] = dict(context_nodes or {})
        edges: list[Edge] = []
        defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]] = []
        name_to_symbols: dict[str, list[str]] = {}
        total = 0
        truncated = False
        fallback_sources: list[SourceFile] = []
        failed_files: list[str] = []
        unsupported_files: list[str] = []
        timeout_files: list[str] = []
        parse_error_files: list[str] = []

        for node_id, node in nodes.items():
            if _is_context_symbol(node):
                name_to_symbols.setdefault(node.label, []).append(node_id)

        for source in files:
            parser = _parser_for_suffix(source.path.suffix.lower())
            if parser is None:
                if self.fallback_on_error:
                    fallback_sources.append(source)
                    unsupported_files.append(source.rel)
                continue
            text_bytes = source.text.encode("utf-8", errors="replace")
            try:
                tree = _parse_with_timeout(parser, text_bytes, self.parse_timeout_micros)
                if tree is None:
                    raise TimeoutError(f"Tree-sitter parse timed out after {self.parse_timeout_micros} microseconds")
            except Exception as exc:
                try:
                    parser.reset()
                except Exception:
                    pass
                if not self.fallback_on_error:
                    raise RuntimeError(f"Tree-sitter failed for {source.rel}: {exc}") from exc
                fallback_sources.append(source)
                failed_files.append(f"{source.rel}:{type(exc).__name__}")
                if isinstance(exc, TimeoutError):
                    timeout_files.append(source.rel)
                else:
                    parse_error_files.append(source.rel)
                continue
            root = tree.root_node
            defs = _collect_defs(source, root, text_bytes)
            defs_by_file.append((source, defs, root))
            seen_ids: set[str] = set()
            for d in defs:
                if total >= max_total_symbols:
                    truncated = True
                    break
                node_id = _definition_node_id(source, d)
                if d.kind == "impl_block" or node_id in seen_ids:
                    continue
                seen_ids.add(node_id)
                summary = _definition_summary(source.text, d.line)
                qualified_name = _definition_qualified_name(d)
                if qualified_name:
                    summary = f"{summary} [{qualified_name}]"
                nodes[node_id] = Node(
                    id=node_id,
                    label=d.name,
                    kind=d.kind,
                    path=source.rel,
                    summary=summary,
                    facts=d.facts,
                    source=str(source.path),
                    confidence=self.confidence,
                )
                edges.append(Edge(
                    source.file_node_id,
                    node_id,
                    "contains",
                    confidence=self.confidence,
                    provenance="tree_sitter",
                    source_location=f"{source.rel}:{d.line}",
                ))
                if len(d.name) > 2:
                    name_to_symbols.setdefault(d.name, []).append(node_id)
                total += 1

        _add_tree_sitter_implements(defs_by_file, name_to_symbols, edges)
        _add_rust_method_owners(defs_by_file, nodes, name_to_symbols, edges)
        _add_nested_contains(defs_by_file, nodes, edges)
        _add_rust_fields(defs_by_file, nodes, edges)
        _add_returns(defs_by_file, nodes, name_to_symbols, edges)
        _add_imports_from(defs_by_file, nodes, name_to_symbols, edges)
        member_call_stats = _add_tree_sitter_calls(defs_by_file, nodes, name_to_symbols, edges)
        _add_rust_test_field_references(defs_by_file, nodes, edges)
        _add_tree_sitter_callback_references(defs_by_file, nodes, name_to_symbols, edges)

        if fallback_sources:
            remaining = max(0, max_total_symbols - total)
            fallback = RegexExtractor().extract_symbols(
                fallback_sources,
                max_total_symbols=remaining,
                context_nodes=nodes,
            )
            nodes.update(fallback.nodes)
            edges.extend(fallback.edges)
            truncated = truncated or fallback.truncated

        new_nodes = {node_id: node for node_id, node in nodes.items() if node_id not in context_ids}
        frontend = "tree_sitter+regex" if fallback_sources else self.name
        return ExtractionResult(
            nodes=new_nodes,
            edges=_dedupe_edges(edges),
            frontend=frontend,
            truncated=truncated,
            fallback_files=tuple(source.rel for source in fallback_sources),
            failed_files=tuple(failed_files),
            unsupported_files=tuple(unsupported_files),
            timeout_files=tuple(timeout_files),
            parse_error_files=tuple(parse_error_files),
            resolved_member_calls=member_call_stats.resolved,
            ambiguous_member_calls=member_call_stats.ambiguous,
            unresolved_member_calls=member_call_stats.unresolved,
        )


def _parse_with_timeout(parser: Any, text: bytes, timeout_micros: int) -> Any | None:
    """Parse one file with Tree-sitter's native cancellation boundary.

    ``timeout_micros`` exists in supported py-tree-sitter releases but is
    deprecated in some newer bindings in favour of progress callbacks.  Keep
    the compatibility branch local so a binding without the attribute still
    parses correctly; it simply cannot provide the native timeout guarantee.
    """
    previous_timeout: Any = None
    # py-tree-sitter 0.25 still exposes the only usable parse-cancellation API
    # as ``timeout_micros`` while warning that a future release will replace it
    # with a progress callback. Isolate that compatibility warning here; once
    # the callback lands in the public parse signature this is the only helper
    # that needs to change.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Use the progress_callback in parse", category=DeprecationWarning)
        timeout_supported = timeout_micros > 0 and hasattr(parser, "timeout_micros")
        if timeout_supported:
            previous_timeout = parser.timeout_micros
            parser.timeout_micros = timeout_micros
        try:
            return parser.parse(text)
        finally:
            if timeout_supported:
                parser.timeout_micros = previous_timeout


def tree_sitter_available() -> bool:
    return find_spec("tree_sitter") is not None and any(
        _language_available(name)
        for name in ("python", "rust", "javascript", "typescript", "go", "java", "c", "cpp", "csharp")
    )


def available_frontends() -> list[FrontendCapability]:
    return [
        FrontendCapability(
            name="regex",
            available=True,
            confidence=0.75,
            description="Dependency-free baseline extractor for imports, definitions, calls, and weak references.",
        ),
        FrontendCapability(
            name="tree_sitter",
            available=tree_sitter_available(),
            confidence=0.95,
            description="Optional per-language CST frontend; normalizes into graphgraph IR when installed.",
        ),
        FrontendCapability(
            name="cpg",
            available=tree_sitter_available(),
            confidence=0.95,
            description="Multi-language control, data, field, and type evidence normalized into GraphGraph IR.",
        ),
    ]


def select_extractor(prefer: str = "auto") -> Extractor:
    if prefer == "tree_sitter":
        if not tree_sitter_available():
            raise RuntimeError("tree_sitter is not installed.")
        return TreeSitterExtractor()
    if prefer == "auto" and tree_sitter_available():
        return TreeSitterExtractor(fallback_on_error=True)
    return RegexExtractor()


@dataclass(frozen=True)
class _TsDef:
    name: str
    kind: str
    start: int
    end: int
    line: int
    extra: tuple[str, ...] = ()
    owner: str = ""
    facts: tuple[str, ...] = ()


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


_SUFFIX_LANGUAGE = {
    ".py": "python",
    ".rs": "rust",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".scala": "scala",
    ".swift": "swift",
}

_LANGUAGE_MODULES = {
    "python": ("tree_sitter_python",),
    "rust": ("tree_sitter_rust",),
    "javascript": ("tree_sitter_javascript",),
    "typescript": ("tree_sitter_typescript",),
    "tsx": ("tree_sitter_typescript",),
    "go": ("tree_sitter_go",),
    "java": ("tree_sitter_java",),
    "c": ("tree_sitter_c",),
    "cpp": ("tree_sitter_cpp",),
    "csharp": ("tree_sitter_c_sharp",),
    "ruby": ("tree_sitter_ruby",),
    "php": ("tree_sitter_php",),
    "kotlin": ("tree_sitter_kotlin",),
    "scala": ("tree_sitter_scala",),
    "swift": ("tree_sitter_swift",),
}

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


def _language_available(name: str) -> bool:
    if find_spec("tree_sitter_language_pack") is not None:
        return True
    return any(find_spec(module_name) is not None for module_name in _LANGUAGE_MODULES.get(name, ()))


@lru_cache(maxsize=16)
def _language_for_name(name: str) -> Any | None:
    if find_spec("tree_sitter") is None:
        return None
    try:
        from tree_sitter import Language
    except Exception:
        return None

    if find_spec("tree_sitter_language_pack") is not None:
        try:
            pack = import_module("tree_sitter_language_pack")
            get_language = getattr(pack, "get_language")
            return get_language("typescript" if name == "tsx" else name)
        except Exception:
            pass

    for module_name in _LANGUAGE_MODULES.get(name, ()):
        if find_spec(module_name) is None:
            continue
        try:
            module = import_module(module_name)
            language_obj = module.language()
            try:
                return Language(language_obj)
            except TypeError:
                return language_obj
        except Exception:
            continue
    return None


@lru_cache(maxsize=16)
def _parser_for_language(name: str) -> Any | None:
    language = _language_for_name(name)
    if language is None:
        return None
    try:
        from tree_sitter import Parser
    except Exception:
        return None
    parser = Parser()
    if hasattr(parser, "set_language"):
        parser.set_language(language)
    else:
        parser.language = language
    return parser


def _parser_for_suffix(suffix: str) -> Any | None:
    name = _SUFFIX_LANGUAGE.get(suffix)
    if not name:
        return None
    return _parser_for_language(name)


def parser_for_suffix(suffix: str) -> Any | None:
    """Return the cached Tree-sitter parser registered for a file suffix."""
    return _parser_for_suffix(suffix.casefold())


def parse_with_timeout(parser: Any, text: bytes, timeout_micros: int) -> Any | None:
    """Parse bytes through the scanner's shared timeout compatibility layer."""
    return _parse_with_timeout(parser, text, timeout_micros)


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


def _definition_facts(source: SourceFile, node: Any, text: bytes) -> tuple[str, ...]:
    """Project language attributes into small, queryable normalized-IR facts."""
    if source.path.suffix.lower() != ".rs" or node.type not in {"function_item", "function_signature_item"}:
        return ()
    snippet = _node_text(node, text)
    prefix = _node_text_range(
        text,
        max(0, int(node.start_byte) - 256),
        int(node.start_byte),
    )
    facts: list[str] = []
    test_attribute = r"#\s*\[\s*(?:tokio::)?test(?:\s*\([^]]*\))?\s*\]"
    if re.search(test_attribute, snippet) or re.search(test_attribute + r"\s*$", prefix):
        facts.extend(("role:test", "rust_attribute:test"))
    # These are deliberately operator-level IR facts, not inferred business
    # claims. They translate stable source primitives into tokens an LLM can
    # retrieve without guessing that "each target once" means deduplication or
    # that a pinned-count contract is implemented with `!=`.
    if re.search(r"(?:==|!=|\bassert_(?:eq|ne)!\s*\()", snippet):
        facts.append("semantic_operator:equality")
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
        for d in callable_defs:
            src_id = _definition_node_id(source, d)
            if src_id not in nodes:
                continue
            text_bytes = source.text.encode("utf-8", errors="replace")
            local_types = _rust_local_types(_node_text_range(text_bytes, d.start, d.end)) if suffix == ".rs" else {}
            if d.owner:
                local_types["self"] = d.owner
                local_types.update({
                    f"self.{field_name}": field_type
                    for (owner, field_name), field_type in rust_field_types.items()
                    if owner == d.owner
                })
            calls = _call_sites_in_range(root, text_bytes, d.start, d.end)
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
                tgt_id = local_resolutions.get(call.name)
                if not tgt_id or tgt_id == src_id:
                    continue
                tgt_node = nodes.get(tgt_id)
                tgt_lang = _lang_family(tgt_node.path) if tgt_node else None
                if src_lang is not None and tgt_lang is not None and src_lang != tgt_lang:
                    continue
                edges.append(Edge(src_id, tgt_id, "calls", confidence=0.9, provenance="tree_sitter"))
    return stats


@dataclass(frozen=True)
class _MemberCallStats:
    resolved: int = 0
    ambiguous: int = 0
    unresolved: int = 0

    def add(self, outcome: str) -> _MemberCallStats:
        return _MemberCallStats(
            resolved=self.resolved + (outcome == "resolved"),
            ambiguous=self.ambiguous + (outcome == "ambiguous"),
            unresolved=self.unresolved + (outcome == "unresolved"),
        )


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


def _method_owner(node_id: str, nodes: dict[str, Node]) -> str:
    node = nodes.get(node_id)
    if not node or not node.parent:
        return ""
    parent = nodes.get(node.parent)
    return parent.label if parent else ""


def _resolve_member_call(
    *,
    source: SourceFile,
    source_id: str,
    call: _CallSite,
    receiver_types: dict[str, str],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> str:
    receiver_type = receiver_types.get(call.receiver, "")
    if not receiver_type and source.path.suffix.lower() == ".rs" and _rust_qualified_type_receiver(call.receiver):
        receiver_type = call.receiver.split("::")[-1]
    candidates = [
        node_id
        for node_id in name_to_symbols.get(call.name, ())
        if node_id != source_id
        and nodes.get(node_id)
        and nodes[node_id].kind == "method"
        and _lang_family(nodes[node_id].path) == _lang_family(source.rel)
    ]
    if receiver_type:
        candidates = [node_id for node_id in candidates if _method_owner(node_id, nodes) == receiver_type]
    if len(candidates) == 1 and receiver_type:
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


@dataclass(frozen=True)
class _CallSite:
    name: str
    qualified: bool
    receiver: str = ""


def _rust_qualified_type_receiver(value: str) -> bool:
    """Whether a Rust receiver explicitly names a unit-struct/type path."""
    parts = value.split("::")
    return bool(
        len(parts) >= 1
        and all(_identifier(part) for part in parts)
        and parts[-1][:1].isupper()
    )


def _call_names_in_range(root: Any, text: bytes, start: int, end: int) -> set[tuple[str, bool]]:
    """Return (callee_name, is_qualified) pairs for call sites in [start, end).

    ``is_qualified`` is True for ``receiver.method(...)``-style calls (the
    callee expression is a compound field/member access, not a bare
    identifier) -- resolving those needs the receiver's *type*, which this
    heuristic system doesn't have. Conflating them with bare ``name(...)``
    calls previously matched stdlib/trait method calls like `order.splice()`
    (Vec::splice) to unrelated same-named free functions elsewhere in the
    repo purely by identifier collision. Callers should not resolve
    qualified calls against the global free-function/method name index.

    Path-qualified calls (``_PATH_QUALIFIED_CALL_TYPES``, e.g. Rust's
    ``Type::function(...)``) are the exception: the target is named
    explicitly in the source, not receiver-type-dependent, so they're
    reported as NOT qualified -- otherwise a struct's own associated
    functions (`QuadPoly::from_uni(...)`) would never show a `calls` edge
    pointing at it, making an actively-used struct look isolated/dead.
    """
    return {(site.name, site.qualified) for site in _call_sites_in_range(root, text, start, end)}


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
                if (
                    not _identifier(receiver)
                    and receiver != "self"
                    and not rust_field_receiver
                    and not _rust_qualified_type_receiver(receiver)
                ):
                    receiver = ""
            sites.add(_CallSite(name=name, qualified=is_qualified, receiver=receiver))
    return sites


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


def _callback_arg_names_in_range(root: Any, text: bytes, start: int, end: int) -> set[str]:
    """Return bare-identifier names passed as call arguments in [start, end).

    Static call-graph analysis only recognizes ``name(...)`` as a call site,
    so a function invoked exclusively via function-pointer/callback
    dispatch -- ``SetMainCallback2(CB2_InitBattle)`` (C), ``setTimeout(cb, ms)``
    (JS), ``signal.connect(handler)`` (Python) -- reads as having zero
    callers even when it's genuinely used extensively. This walks the same
    call-expression nodes as ``_call_names_in_range`` but looks at the
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
