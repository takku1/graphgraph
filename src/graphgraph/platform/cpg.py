from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterator

from ..graph.core import Edge, Graph, Node
from ..graph.operations import dedupe_edges
from ..scanner.frontends import (
    DEFINITION_NODE_TYPES,
    NAME_NODE_TYPES,
    parse_with_timeout,
    parser_for_suffix,
    parser_unavailable_reason,
)
from .contracts import (
    CapabilityReceipt,
    EvidenceBatch,
    PythonAstEvidenceProvider,
)

_SUPPORTED_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".cxx",
    ".cc",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".kt",
    ".scala",
    ".swift",
}
_CONTROL_TYPES = {
    "if_statement",
    "if_expression",
    "for_statement",
    "for_expression",
    "for_in_statement",
    "while_statement",
    "while_expression",
    "do_statement",
    "loop_expression",
    "try_statement",
    "try_expression",
    "with_statement",
    "match_expression",
    "match_statement",
    "switch_statement",
    "switch_expression",
    "when_expression",
    "conditional_expression",
    "catch_clause",
}
_ASSIGNMENT_TYPES = {
    "assignment",
    "assignment_expression",
    "augmented_assignment",
    "augmented_assignment_expression",
    "variable_declarator",
    "init_declarator",
    "short_var_declaration",
    "let_declaration",
    "const_item",
    "static_item",
    "property_declaration",
}
_DECLARATION_TYPES = _ASSIGNMENT_TYPES | {
    "field_declaration",
    "constant_declaration",
    "local_variable_declaration",
}
_PARAMETER_MARKERS = ("parameter", "formal_parameter", "parameter_declaration")
_TYPE_NODE_TYPES = {
    "type_identifier",
    "primitive_type",
    "predefined_type",
    "generic_type",
    "scoped_type_identifier",
    "array_type",
    "pointer_type",
    "reference_type",
    "nullable_type",
    "function_type",
    "user_type",
}
_NON_DATA_FIELDS = {
    "function",
    "method",
    "field",
    "property",
    "attribute",
    "type",
    "return_type",
}


class CpgEvidenceProvider:
    """Normalize multi-language control, data, field, and type evidence."""

    name = "cpg"
    version = "1"
    capabilities = (
        "reads",
        "writes",
        "control_flow",
        "field_of",
        "type_of",
        "returns",
    )
    incremental = True

    def __init__(
        self,
        *,
        max_nodes: int = 5000,
        max_edges: int = 20000,
        parse_timeout_micros: int = 2_000_000,
    ) -> None:
        self.max_nodes = max(0, max_nodes)
        self.max_edges = max(0, max_edges)
        self.parse_timeout_micros = max(0, parse_timeout_micros)

    def supports_path(self, path: str) -> bool:
        return Path(path).suffix.casefold() in _SUPPORTED_SUFFIXES

    def collect(self, graph: Graph, paths: tuple[str, ...] = ()) -> EvidenceBatch:
        selected = {path.replace("\\", "/") for path in paths}
        sources = _graph_sources(graph, selected, self.supports_path)
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        warnings: list[str] = []
        python_paths = tuple(path for path in sources if path.casefold().endswith(".py"))
        if python_paths:
            python = PythonAstEvidenceProvider(max_nodes=1_000_000, max_edges=2_000_000).collect(
                graph,
                python_paths,
            )
            nodes.update((node.id, node) for node in python.nodes)
            edges.extend(python.edges)
            warnings.extend(python.receipt.warnings)
        symbols = _symbols_by_path(graph, set(sources) - set(python_paths))
        for rel_path, source in sorted(sources.items()):
            if rel_path in python_paths:
                continue
            parser = parser_for_suffix(source.suffix)
            if parser is None:
                warnings.append(
                    f"{rel_path}:grammar_unavailable:{parser_unavailable_reason(source.suffix)}"
                )
                continue
            try:
                text = source.read_text(encoding="utf-8", errors="replace")
                text_bytes = text.encode("utf-8", errors="replace")
                tree = parse_with_timeout(parser, text_bytes, self.parse_timeout_micros)
                if tree is None:
                    raise TimeoutError("Tree-sitter parse timed out")
            except (OSError, RuntimeError, TimeoutError) as exc:
                warnings.append(f"{rel_path}:{type(exc).__name__}")
                continue
            language = source.suffix.casefold().lstrip(".")
            for definition in _definition_nodes(tree.root_node):
                name = _definition_name(definition, text_bytes)
                if not name:
                    continue
                line = definition.start_point[0] + 1
                owner = _resolve_owner(symbols.get((rel_path, name), ()), line)
                if owner is None:
                    continue
                _definition_evidence(
                    owner,
                    definition,
                    text_bytes,
                    rel_path,
                    language,
                    nodes,
                    edges,
                )
        edges = dedupe_edges(edges)
        emitted_nodes = len(nodes)
        emitted_edges = len(edges)
        selected_nodes = dict(list(nodes.items())[: self.max_nodes])
        allowed_ids = set(graph.nodes) | set(selected_nodes)
        viable_edges = [
            edge for edge in edges if edge.source in allowed_ids and edge.target in allowed_ids
        ]
        selected_edges = viable_edges[: self.max_edges]
        nodes_truncated = max(0, emitted_nodes - len(selected_nodes))
        edges_truncated = max(0, emitted_edges - len(selected_edges))
        if nodes_truncated or edges_truncated:
            warnings.append(
                f"evidence budget reached: nodes={nodes_truncated} edges={edges_truncated} truncated"
            )
        return EvidenceBatch(
            tuple(selected_nodes.values()),
            tuple(selected_edges),
            CapabilityReceipt(
                self.name,
                self.version,
                self.capabilities,
                nodes_emitted=emitted_nodes,
                edges_emitted=emitted_edges,
                nodes_truncated=nodes_truncated,
                edges_truncated=edges_truncated,
                paths_processed=len(sources),
                warnings=tuple(dict.fromkeys(warnings)),
            ),
        )


def _graph_sources(
    graph: Graph,
    selected: set[str],
    supports_path,
) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for node in graph.nodes.values():
        rel_path = node.path.replace("\\", "/")
        if selected and rel_path not in selected:
            continue
        if not rel_path or not supports_path(rel_path) or not node.source:
            continue
        source = Path(node.source)
        if source.is_file():
            sources.setdefault(rel_path, source)
    return sources


def _symbols_by_path(
    graph: Graph,
    paths: set[str],
) -> dict[tuple[str, str], list[Node]]:
    symbols: dict[tuple[str, str], list[Node]] = {}
    for node in graph.nodes.values():
        path = node.path.replace("\\", "/")
        if path in paths and node.label:
            symbols.setdefault((path, node.label), []).append(node)
    return symbols


def _definition_nodes(root: Any) -> Iterator[Any]:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in DEFINITION_NODE_TYPES:
            yield node
        stack.extend(reversed(node.children))


def _definition_name(node: Any, text: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        name = next((child for child in node.children if child.type in NAME_NODE_TYPES), None)
    return _node_text(name, text) if name is not None else ""


def _resolve_owner(candidates: list[Node] | tuple[Node, ...], line: int) -> Node | None:
    if not candidates:
        return None
    exact = [node for node in candidates if node.line == line]
    if len(exact) == 1:
        return exact[0]
    ranked = sorted(
        candidates,
        key=lambda node: (abs((node.line or line) - line), node.id),
    )
    return ranked[0] if ranked else None


def _definition_evidence(
    owner: Node,
    definition: Any,
    text: bytes,
    rel_path: str,
    language: str,
    nodes: dict[str, Node],
    edges: list[Edge],
) -> None:
    return_type = definition.child_by_field_name("return_type")
    if return_type is None and owner.kind in {"function", "method"}:
        return_type = definition.child_by_field_name("type")
    if return_type is not None:
        type_id = _type_node(nodes, rel_path, _node_text(return_type, text), language)
        edges.append(_edge(owner.id, type_id, "returns", rel_path, definition, "return type"))

    control_nodes: list[tuple[Any, str]] = []
    for item, parent, field in _walk_owned(definition):
        if item.type in _CONTROL_TYPES:
            block_id = _control_node(nodes, owner, item, rel_path, language)
            control_nodes.append((item, block_id))
        if _is_parameter(item):
            _typed_declaration(owner, item, text, rel_path, language, nodes, edges, field_of=False)
        elif item.type in _DECLARATION_TYPES:
            _typed_declaration(
                owner,
                item,
                text,
                rel_path,
                language,
                nodes,
                edges,
                field_of=owner.kind in {"class", "struct", "interface", "type"},
            )
        if item.type not in NAME_NODE_TYPES or item.type in _TYPE_NODE_TYPES:
            continue
        name = _node_text(item, text)
        if not _is_data_name(name) or _definition_name_reference(item, parent, field):
            continue
        if _has_parameter_ancestor(item, definition) or _has_type_ancestor(item, definition):
            continue
        data_id = _data_node(nodes, owner, name, rel_path, item, language)
        relation = "writes" if _is_write(item, definition) else "reads"
        edges.append(_edge(owner.id, data_id, relation, rel_path, item, f"identifier:{name}"))

    control_nodes.sort(key=lambda item: (item[0].start_byte, item[0].end_byte))
    for item, block_id in control_nodes:
        parent_block = next(
            (
                candidate_id
                for candidate, candidate_id in reversed(control_nodes)
                if candidate.start_byte < item.start_byte and candidate.end_byte >= item.end_byte
            ),
            owner.id,
        )
        edges.append(_edge(parent_block, block_id, "control_flow", rel_path, item, "nested control"))


def _walk_owned(root: Any) -> Iterator[tuple[Any, Any, str]]:
    stack: list[tuple[Any, Any, str]] = []
    for index in range(root.child_count - 1, -1, -1):
        child = root.child(index)
        stack.append((child, root, root.field_name_for_child(index) or ""))
    while stack:
        item, parent, field = stack.pop()
        yield item, parent, field
        if item.type in DEFINITION_NODE_TYPES:
            continue
        for index in range(item.child_count - 1, -1, -1):
            child = item.child(index)
            stack.append((child, item, item.field_name_for_child(index) or ""))


def _typed_declaration(
    owner: Node,
    declaration: Any,
    text: bytes,
    rel_path: str,
    language: str,
    nodes: dict[str, Node],
    edges: list[Edge],
    *,
    field_of: bool,
) -> None:
    name_node = declaration.child_by_field_name("name")
    if name_node is None:
        name_node = declaration.child_by_field_name("pattern")
    if name_node is None:
        name_node = next(
            (child for child in declaration.children if child.type in NAME_NODE_TYPES),
            None,
        )
    if name_node is None:
        return
    name = _node_text(name_node, text)
    if not _is_data_name(name):
        return
    kind = "field" if field_of else "data"
    data_id = _data_node(nodes, owner, name, rel_path, name_node, language, kind=kind)
    if field_of:
        edges.append(_edge(data_id, owner.id, "field_of", rel_path, name_node, "field declaration"))
    else:
        edges.append(_edge(owner.id, data_id, "writes", rel_path, name_node, "declaration"))
    type_node = declaration.child_by_field_name("type")
    if type_node is None and declaration.parent is not None:
        type_node = declaration.parent.child_by_field_name("type")
    if type_node is not None:
        type_id = _type_node(nodes, rel_path, _node_text(type_node, text), language)
        edges.append(_edge(data_id, type_id, "type_of", rel_path, type_node, "declared type"))


def _is_parameter(node: Any) -> bool:
    return "parameter" in node.type or node.type in _PARAMETER_MARKERS


def _has_parameter_ancestor(node: Any, root: Any) -> bool:
    parent = node.parent
    while parent is not None and parent != root:
        if _is_parameter(parent):
            return True
        parent = parent.parent
    return False


def _has_type_ancestor(node: Any, root: Any) -> bool:
    parent = node.parent
    while parent is not None and parent != root:
        if parent.type in _TYPE_NODE_TYPES or parent.type.endswith("_type"):
            return True
        parent = parent.parent
    return False


def _definition_name_reference(node: Any, parent: Any, field: str) -> bool:
    if field in _NON_DATA_FIELDS:
        return True
    return parent.type in DEFINITION_NODE_TYPES and field == "name"


def _is_write(node: Any, root: Any) -> bool:
    current = node
    parent = node.parent
    while parent is not None and parent != root:
        if parent.type in _ASSIGNMENT_TYPES:
            field = _field_name(parent, current)
            return field in {"left", "name", "pattern", "declarator"} or parent.type in {
                "variable_declarator",
                "init_declarator",
                "short_var_declaration",
                "let_declaration",
            }
        current = parent
        parent = parent.parent
    return False


def _field_name(parent: Any, child: Any) -> str:
    for index in range(parent.child_count):
        if parent.child(index) == child:
            return parent.field_name_for_child(index) or ""
    return ""


def _data_node(
    nodes: dict[str, Node],
    owner: Node,
    name: str,
    rel_path: str,
    syntax: Any,
    language: str,
    *,
    kind: str = "data",
) -> str:
    node_id = f"cpg:data:{owner.id}:{name}"
    line = syntax.start_point[0] + 1
    nodes.setdefault(
        node_id,
        Node(
            node_id,
            name,
            kind=kind,
            path=rel_path,
            summary=f"L{line} {kind} {name}",
            facts=(f"language:{language}",),
            parent=owner.id,
            source=owner.source,
            confidence=0.9,
        ),
    )
    return node_id


def _type_node(nodes: dict[str, Node], rel_path: str, name: str, language: str) -> str:
    normalized = " ".join(name.split()) or "unknown"
    digest = hashlib.sha256(f"{rel_path}\0{normalized}".encode("utf-8")).hexdigest()[:16]
    node_id = f"cpg:type:{digest}"
    nodes.setdefault(
        node_id,
        Node(
            node_id,
            normalized,
            kind="type",
            path=rel_path,
            facts=(f"language:{language}",),
            confidence=0.9,
        ),
    )
    return node_id


def _control_node(
    nodes: dict[str, Node],
    owner: Node,
    syntax: Any,
    rel_path: str,
    language: str,
) -> str:
    line = syntax.start_point[0] + 1
    node_id = f"cpg:block:{owner.id}:{line}:{syntax.start_byte}"
    nodes.setdefault(
        node_id,
        Node(
            node_id,
            syntax.type,
            kind="control_block",
            path=rel_path,
            summary=f"L{line} {syntax.type}",
            facts=(f"language:{language}",),
            parent=owner.id,
            source=owner.source,
            confidence=0.9,
        ),
    )
    return node_id


def _edge(
    source: str,
    target: str,
    relation: str,
    rel_path: str,
    syntax: Any,
    evidence: str,
) -> Edge:
    line = syntax.start_point[0] + 1
    return Edge(
        source,
        target,
        relation,
        confidence=0.9,
        provenance="cpg_tree_sitter",
        evidence=evidence,
        source_location=f"{rel_path}:{line}",
    )


def _node_text(node: Any, text: bytes) -> str:
    return text[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()


def _is_data_name(name: str) -> bool:
    return bool(name) and len(name) <= 160 and not name[0].isdigit()


