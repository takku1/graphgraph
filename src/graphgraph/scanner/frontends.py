from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol

from ..core import Edge, Node
from ..operations import _dedupe_edges
from .ast import extract_symbols


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


class Extractor(Protocol):
    name: str
    confidence: float

    def extract_symbols(self, files: list[SourceFile], max_total_symbols: int) -> ExtractionResult:
        ...


class RegexExtractor:
    name = "regex"
    confidence = 0.75

    def extract_symbols(self, files: list[SourceFile], max_total_symbols: int) -> ExtractionResult:
        tuples = [(f.path, f.rel, f.file_node_id, f.text) for f in files]
        nodes, edges = extract_symbols(tuples, max_total_symbols=max_total_symbols)
        return ExtractionResult(nodes=nodes, edges=edges, frontend=self.name)


class TreeSitterExtractor:
    name = "tree_sitter"
    confidence = 0.95

    def extract_symbols(self, files: list[SourceFile], max_total_symbols: int) -> ExtractionResult:
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]] = []
        name_to_symbols: dict[str, list[str]] = {}
        total = 0

        for source in files:
            parser = _parser_for_suffix(source.path.suffix.lower())
            if parser is None:
                continue
            text_bytes = source.text.encode("utf-8", errors="replace")
            tree = parser.parse(text_bytes)
            root = tree.root_node
            defs = _collect_defs(source, root, text_bytes)
            defs_by_file.append((source, defs, root))
            seen_names: set[str] = set()
            for d in defs:
                if total >= max_total_symbols:
                    break
                if d.kind == "impl_block" or d.name in seen_names:
                    continue
                seen_names.add(d.name)
                node_id = f"{source.file_node_id}__{d.name}"
                nodes[node_id] = Node(
                    id=node_id,
                    label=d.name,
                    kind=d.kind,
                    path=source.rel,
                    summary=f"L{d.line}",
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
        _add_nested_contains(defs_by_file, nodes, edges)
        _add_rust_fields(defs_by_file, nodes, edges)
        _add_returns(defs_by_file, nodes, name_to_symbols, edges)
        _add_imports_from(defs_by_file, nodes, name_to_symbols, edges)
        _add_tree_sitter_calls(defs_by_file, nodes, name_to_symbols, edges)
        return ExtractionResult(nodes=nodes, edges=_dedupe_edges(edges), frontend=self.name)


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
            available=False,
            confidence=0.95,
            description="Planned Code Property Graph layer for control/data/type flow.",
        ),
    ]


def select_extractor(prefer: str = "auto") -> Extractor:
    if prefer == "tree_sitter":
        if not tree_sitter_available():
            raise RuntimeError("tree_sitter is not installed.")
        return TreeSitterExtractor()
    if prefer == "auto" and tree_sitter_available():
        return TreeSitterExtractor()
    return RegexExtractor()


@dataclass(frozen=True)
class _TsDef:
    name: str
    kind: str
    start: int
    end: int
    line: int
    extra: tuple[str, ...] = ()


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
        ))
    return defs


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
        if nested is not None and node.type in {"type_declaration", "lexical_declaration"}:
            return nested
    return None


def _node_text(node: Any, text: bytes) -> str:
    return text[int(node.start_byte):int(node.end_byte)].decode("utf-8", errors="replace")


def _node_text_range(text: bytes, start: int, end: int) -> str:
    return text[start:end].decode("utf-8", errors="replace")


def _rust_impl_def(node: Any, text: bytes) -> _TsDef | None:
    snippet = _node_text(node, text).split("{", 1)[0]
    m = re.search(r"\bimpl\s*(?:<[^>]*>\s*)?(?:(?P<trait>[A-Za-z_][\w:]*)\s+for\s+)?(?P<typ>[A-Za-z_][\w:]*)", snippet)
    if not m or not m.group("trait"):
        return None
    trait = m.group("trait").split("::")[-1]
    typ = m.group("typ").split("::")[-1]
    return _TsDef(
        name=f"impl_{trait}_for_{typ}",
        kind="impl_block",
        start=int(node.start_byte),
        end=int(node.end_byte),
        line=int(node.start_point[0]) + 1,
        extra=(trait, typ),
    )


def _rust_fields_in_range(root: Any, text: bytes, start: int, end: int) -> list[tuple[str, int]]:
    fields: list[tuple[str, int]] = []
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
            fields.append((name, int(node.start_point[0]) + 1))
    return fields


def _return_type_name(signature_or_body: str) -> str:
    head = signature_or_body.split("{", 1)[0].rstrip(";")
    match = re.search(r"->\s*(?:&\s*)?(?:'[\w_]+\s+)?(?P<typ>[A-Za-z_][A-Za-z0-9_:<>]*)", head)
    if not match:
        return ""
    typ = match.group("typ").split("::")[-1]
    typ = typ.split("<", 1)[0]
    return typ if _identifier(typ) else ""


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
        materialized = [d for d in defs if f"{source.file_node_id}__{d.name}" in nodes and d.kind != "impl_block"]
        for child in materialized:
            if child.kind not in child_kinds:
                continue
            parents = [
                parent for parent in materialized
                if parent.kind in owner_kinds
                and parent.start < child.start
                and child.end < parent.end
            ]
            if not parents:
                continue
            parent = min(parents, key=lambda d: d.end - d.start)
            parent_id = f"{source.file_node_id}__{parent.name}"
            child_id = f"{source.file_node_id}__{child.name}"
            if parent_id != child_id:
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
        structs = [d for d in defs if d.kind == "struct" and f"{source.file_node_id}__{d.name}" in nodes]
        if not structs:
            continue
        for struct in structs:
            struct_id = f"{source.file_node_id}__{struct.name}"
            for field_name, line in _rust_fields_in_range(root, text, struct.start, struct.end):
                field_id = f"{struct_id}__field_{field_name}"
                if field_id not in nodes:
                    nodes[field_id] = Node(
                        id=field_id,
                        label=field_name,
                        kind="field",
                        path=source.rel,
                        summary=f"L{line}",
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
            src_id = f"{source.file_node_id}__{d.name}"
            if src_id not in nodes:
                continue
            return_type = _return_type_name(_node_text_range(text, d.start, d.end))
            if not return_type:
                continue
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
        for m in re.finditer(r"^from\s+([\w.]+)\s+import\s+(.+)$", text, re.MULTILINE):
            module_name = m.group(1).split(".")[-1]
            for part in m.group(2).split(","):
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


def _add_tree_sitter_calls(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    # 1. Identify globally unique callables
    unique_callables = {
        name: ids[0] for name, ids in name_to_symbols.items()
        if len(ids) == 1 and nodes[ids[0]].kind in {"function", "method"}
    }

    for source, defs, root in defs_by_file:
        suffix = source.path.suffix.lower()
        imported_sources = _imported_symbol_sources(suffix, source.text)
        
        # Build local resolutions dictionary starting with globally unique callables
        local_resolutions = dict(unique_callables)

        # 2. Add locally imported symbols, using module stem matching for disambiguation
        all_imported = _imported_symbol_names(suffix, source.text)
        for name in all_imported:
            targets = name_to_symbols.get(name, [])
            if len(targets) == 1:
                local_resolutions[name] = targets[0]
            elif len(targets) > 1:
                # Disambiguate by matching import stem (e.g. 'helper') to target file stem
                stem = imported_sources.get(name)
                if stem:
                    matching = []
                    for tgt_id in targets:
                        node = nodes.get(tgt_id)
                        if node:
                            node_stem = Path(node.path).stem
                            if node_stem.lower() == stem.lower():
                                matching.append(tgt_id)
                    if len(matching) == 1:
                        local_resolutions[name] = matching[0]

        callable_defs = [d for d in sorted(defs, key=lambda d: d.start) if d.kind in {"function", "method"}]
        for d in callable_defs:
            src_id = f"{source.file_node_id}__{d.name}"
            if src_id not in nodes:
                continue
            calls = _call_names_in_range(root, source.text.encode("utf-8", errors="replace"), d.start, d.end)
            for call in calls:
                tgt_id = local_resolutions.get(call)
                if tgt_id and tgt_id != src_id:
                    edges.append(Edge(src_id, tgt_id, "calls", confidence=0.9, provenance="tree_sitter"))


def _add_imports_from(
    defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]],
    nodes: dict[str, Node],
    name_to_symbols: dict[str, list[str]],
    edges: list[Edge],
) -> None:
    for source, _defs, _root in defs_by_file:
        suffix = source.path.suffix.lower()
        imported_names = _imported_symbol_names(suffix, source.text)
        imported_sources = _imported_symbol_sources(suffix, source.text)
        
        for name in imported_names:
            targets = name_to_symbols.get(name, [])
            target = None
            if len(targets) == 1:
                target = targets[0]
            elif len(targets) > 1:
                # Disambiguate by matching import stem to target file stem
                stem = imported_sources.get(name)
                if stem:
                    matching = []
                    for tgt_id in targets:
                        node = nodes.get(tgt_id)
                        if node:
                            node_stem = Path(node.path).stem
                            if node_stem.lower() == stem.lower():
                                matching.append(tgt_id)
                    if len(matching) == 1:
                        target = matching[0]

            if target and not target.startswith(source.file_node_id + "__"):
                edges.append(Edge(
                    source.file_node_id,
                    target,
                    "imports_from",
                    confidence=0.85,
                    provenance="tree_sitter",
                    source_location=source.rel,
                ))


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
        for m in re.finditer(r"^from\s+[\w.]+\s+import\s+(.+)$", text, re.MULTILINE):
            for part in m.group(1).split(","):
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


def _call_names_in_range(root: Any, text: bytes, start: int, end: int) -> set[str]:
    names: set[str] = set()
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
        name = _call_name(fn, text) if fn is not None else ""
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
