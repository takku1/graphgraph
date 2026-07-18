from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from ..graph.core import Edge, Graph, Node


@dataclass(frozen=True)
class CapabilityReceipt:
    provider: str
    version: str
    capabilities: tuple[str, ...]
    nodes_emitted: int = 0
    edges_emitted: int = 0
    nodes_accepted: int = 0
    nodes_duplicate: int = 0
    nodes_rejected: int = 0
    nodes_truncated: int = 0
    edges_accepted: int = 0
    edges_duplicate: int = 0
    edges_rejected: int = 0
    edges_truncated: int = 0
    paths_processed: int = 0
    paths_restored: int = 0
    cache_hit: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceBatch:
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    receipt: CapabilityReceipt = field(
        default_factory=lambda: CapabilityReceipt("unknown", "0", ())
    )


class EvidenceProvider(Protocol):
    name: str
    version: str
    capabilities: tuple[str, ...]
    incremental: bool

    def collect(self, graph: Graph, paths: tuple[str, ...] = ()) -> EvidenceBatch:
        ...


class ProviderRegistry:
    """Runs independent evidence providers and merges their typed evidence."""

    def __init__(self, providers: tuple[EvidenceProvider, ...] = ()) -> None:
        self._providers = {provider.name: provider for provider in providers}

    def register(self, provider: EvidenceProvider) -> None:
        self._providers[provider.name] = provider

    def capabilities(self) -> list[dict[str, object]]:
        return [
            {
                "name": provider.name,
                "version": provider.version,
                "capabilities": list(provider.capabilities),
            }
            for provider in self._providers.values()
        ]

    def apply(self, graph: Graph) -> tuple[Graph, tuple[CapabilityReceipt, ...]]:
        batches = tuple(
            provider.collect(graph)
            for provider in self._providers.values()
        )
        return self.apply_batches(graph, batches)

    def apply_persisted(
        self,
        graph: Graph,
        store: object,
        *,
        changed_paths: tuple[str, ...] = (),
        force: bool = False,
        preferred_paths: tuple[str, ...] = (),
        max_nodes: int | None = None,
        max_edges: int | None = None,
    ) -> tuple[Graph, tuple[CapabilityReceipt, ...]]:
        from .evidence_store import EvidenceStore

        if not isinstance(store, EvidenceStore):
            raise TypeError("store must be an EvidenceStore")
        batches = store.refresh_batches(
            graph,
            self._providers.values(),
            changed_paths=changed_paths,
            force=force,
            preferred_paths=preferred_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        return self.apply_batches(graph, batches)

    def apply_batches(
        self,
        graph: Graph,
        batches: tuple[EvidenceBatch, ...],
    ) -> tuple[Graph, tuple[CapabilityReceipt, ...]]:
        nodes = dict(graph.nodes)
        edges = list(graph.edges)
        edge_keys = {(edge.source, edge.target, edge.type) for edge in edges}
        receipts: list[CapabilityReceipt] = []
        for batch in batches:
            nodes_accepted = 0
            nodes_duplicate = 0
            for node in batch.nodes:
                if node.id in nodes:
                    nodes_duplicate += 1
                else:
                    nodes[node.id] = node
                    nodes_accepted += 1
            edges_accepted = 0
            edges_duplicate = 0
            edges_rejected = 0
            for edge in batch.edges:
                key = (edge.source, edge.target, edge.type)
                if edge.source not in nodes or edge.target not in nodes:
                    edges_rejected += 1
                elif key in edge_keys:
                    edges_duplicate += 1
                else:
                    edges.append(edge)
                    edge_keys.add(key)
                    edges_accepted += 1
            receipts.append(replace(
                batch.receipt,
                nodes_accepted=nodes_accepted,
                nodes_duplicate=nodes_duplicate,
                nodes_rejected=max(
                    0,
                    batch.receipt.nodes_emitted
                    - nodes_accepted
                    - nodes_duplicate
                    - batch.receipt.nodes_truncated,
                ),
                edges_accepted=edges_accepted,
                edges_duplicate=edges_duplicate,
                edges_rejected=max(
                    edges_rejected,
                    batch.receipt.edges_emitted
                    - edges_accepted
                    - edges_duplicate
                    - batch.receipt.edges_truncated,
                ),
            ))
        metadata = dict(graph.metadata)
        metadata["evidence_providers"] = ",".join(receipt.provider for receipt in receipts)
        return Graph(nodes=nodes, edges=edges, metadata=metadata), tuple(receipts)


class StructuralEvidenceProvider:
    """Adds conservative test and configuration relations from scanner evidence."""

    name = "structural"
    version = "1"
    capabilities = ("tests", "configures")
    incremental = False

    def collect(self, graph: Graph, paths: tuple[str, ...] = ()) -> EvidenceBatch:
        edges: list[Edge] = []
        file_nodes = [node for node in graph.nodes.values() if node.path and node.active and _is_file_node(node)]
        selected_paths = set(paths)
        source_by_stem: dict[str, list[Node]] = {}
        for node in file_nodes:
            if selected_paths and node.path not in selected_paths:
                continue
            stem = _source_stem(node.path)
            if stem and not _is_test_path(node.path):
                source_by_stem.setdefault(stem, []).append(node)
        for node in file_nodes:
            if _is_test_path(node.path):
                stem = _source_stem(node.path)
                matches = source_by_stem.get(stem, ())
                if len(matches) == 1:
                    edges.append(Edge(
                        node.id,
                        matches[0].id,
                        "tests",
                        confidence=0.9,
                        provenance="structural_provider",
                        evidence="test/source filename match",
                        source_location=node.path,
                    ))
            if _is_config_path(node.path):
                for edge in graph.edges:
                    if edge.source == node.id and edge.target in graph.nodes:
                        edges.append(Edge(
                            node.id,
                            edge.target,
                            "configures",
                            confidence=0.75,
                            provenance="structural_provider",
                            evidence=f"configuration dependency via {edge.type}",
                            source_location=node.path,
                        ))
        return EvidenceBatch(
            edges=tuple(edges),
            receipt=CapabilityReceipt(
                self.name,
                self.version,
                self.capabilities,
                edges_emitted=len(edges),
                paths_processed=len(selected_paths) if selected_paths else len({node.path for node in file_nodes}),
            ),
        )


class PythonAstEvidenceProvider:
    """Compiler evidence for Python data access, control blocks, fields, and types."""

    name = "python_ast"
    version = "1"
    capabilities = ("reads", "writes", "control_flow", "field_of", "type_of", "returns")
    incremental = True

    def __init__(self, *, max_nodes: int = 5000, max_edges: int = 20000) -> None:
        self.max_nodes = max(0, max_nodes)
        self.max_edges = max(0, max_edges)

    def supports_path(self, path: str) -> bool:
        return path.casefold().endswith(".py")

    def collect(self, graph: Graph, paths: tuple[str, ...] = ()) -> EvidenceBatch:
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        warnings: list[str] = []
        symbols: dict[tuple[str, str], list[Node]] = {}
        sources: dict[str, Path] = {}
        selected_paths = {path.replace("\\", "/") for path in paths}
        for node in graph.nodes.values():
            if node.path.casefold().endswith(".py") and node.label:
                normalized_path = node.path.replace("\\", "/")
                if selected_paths and normalized_path not in selected_paths:
                    continue
                symbols.setdefault((normalized_path, node.label), []).append(node)
                if node.source:
                    source = Path(node.source)
                    if source.is_file():
                        sources.setdefault(normalized_path, source)
        for rel_path, source in sorted(sources.items()):
            try:
                text = source.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text, filename=rel_path)
            except (OSError, SyntaxError) as exc:
                warnings.append(f"{rel_path}:{type(exc).__name__}")
                continue
            for definition in (item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))):
                owner = _resolve_ast_owner(symbols.get((rel_path, definition.name), ()), definition.lineno)
                if owner is None:
                    continue
                if isinstance(definition, ast.ClassDef):
                    self._class_evidence(owner, definition, rel_path, nodes, edges)
                else:
                    self._function_evidence(owner, definition, rel_path, nodes, edges)
        edges = _dedupe_edges(edges)
        emitted_nodes = len(nodes)
        emitted_edges = len(edges)
        selected_nodes = dict(list(nodes.items())[:self.max_nodes])
        allowed_ids = set(graph.nodes) | set(selected_nodes)
        viable_edges = [edge for edge in edges if edge.source in allowed_ids and edge.target in allowed_ids]
        selected_edges = viable_edges[:self.max_edges]
        nodes_truncated = max(0, emitted_nodes - len(selected_nodes))
        edges_truncated = max(0, emitted_edges - len(selected_edges))
        if nodes_truncated or edges_truncated:
            warnings.append(
                f"evidence budget reached: nodes={nodes_truncated} edges={edges_truncated} truncated"
            )
        return EvidenceBatch(
            nodes=tuple(selected_nodes.values()),
            edges=tuple(selected_edges),
            receipt=CapabilityReceipt(
                self.name,
                self.version,
                self.capabilities,
                nodes_emitted=emitted_nodes,
                edges_emitted=emitted_edges,
                nodes_truncated=nodes_truncated,
                edges_truncated=edges_truncated,
                paths_processed=len(sources),
                warnings=tuple(warnings),
            ),
        )

    def _function_evidence(
        self,
        owner: Node,
        definition: ast.FunctionDef | ast.AsyncFunctionDef,
        rel_path: str,
        nodes: dict[str, Node],
        edges: list[Edge],
    ) -> None:
        argument_names = {
            arg.arg for arg in (*definition.args.posonlyargs, *definition.args.args, *definition.args.kwonlyargs)
        }
        if definition.args.vararg:
            argument_names.add(definition.args.vararg.arg)
        if definition.args.kwarg:
            argument_names.add(definition.args.kwarg.arg)
        for arg in (*definition.args.posonlyargs, *definition.args.args, *definition.args.kwonlyargs):
            if arg.annotation:
                type_id = _type_node(nodes, rel_path, _annotation(arg.annotation), arg.lineno)
                edges.append(_evidence_edge(owner.id, type_id, "type_of", rel_path, arg.lineno, f"parameter:{arg.arg}"))
        if definition.returns:
            type_id = _type_node(nodes, rel_path, _annotation(definition.returns), definition.lineno)
            edges.append(_evidence_edge(owner.id, type_id, "returns", rel_path, definition.lineno, "return annotation"))
        owned_items = tuple(_walk_owned_scope(definition))
        for item in owned_items:
            if isinstance(item, ast.Name) and item.id not in argument_names and item.id not in {"self", "cls"}:
                data_id = _data_node(nodes, owner, item.id, rel_path, item.lineno)
                relation = "writes" if isinstance(item.ctx, (ast.Store, ast.Del)) else "reads"
                edges.append(_evidence_edge(owner.id, data_id, relation, rel_path, item.lineno, f"name:{item.id}"))
        blocks = [
            item for item in owned_items
            if isinstance(item, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match))
        ]
        previous = owner.id
        for index, block in enumerate(sorted(blocks, key=lambda item: (item.lineno, item.col_offset))):
            block_id = f"block:{owner.id}:{block.lineno}:{index}"
            nodes.setdefault(block_id, Node(
                block_id,
                type(block).__name__.casefold(),
                kind="control_block",
                path=rel_path,
                summary=f"L{block.lineno} {type(block).__name__}",
                parent=owner.id,
                source=owner.source,
                confidence=0.95,
            ))
            edges.append(_evidence_edge(previous, block_id, "control_flow", rel_path, block.lineno, "lexical control order"))
            previous = block_id

    def _class_evidence(
        self,
        owner: Node,
        definition: ast.ClassDef,
        rel_path: str,
        nodes: dict[str, Node],
        edges: list[Edge],
    ) -> None:
        for item in definition.body:
            if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                continue
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    field_id = _data_node(nodes, owner, target.id, rel_path, target.lineno, kind="field")
                    edges.append(_evidence_edge(field_id, owner.id, "field_of", rel_path, target.lineno, "class assignment"))
                    if isinstance(item, ast.AnnAssign) and item.annotation:
                        type_id = _type_node(nodes, rel_path, _annotation(item.annotation), item.lineno)
                        edges.append(_evidence_edge(field_id, type_id, "type_of", rel_path, item.lineno, "field annotation"))


def _source_stem(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].casefold()
    for prefix in ("test_", "tests_", "spec_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in ("_test", "_tests", "_spec"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name


def _walk_owned_scope(root: ast.AST):
    stack = list(reversed(list(ast.iter_child_nodes(root))))
    while stack:
        item = stack.pop()
        yield item
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(item))))


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    unique: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        unique.setdefault((edge.source, edge.target, edge.type), edge)
    return list(unique.values())


def _is_test_path(path: str) -> bool:
    normalized = "/" + path.replace("\\", "/").casefold() + "/"
    name = normalized.rsplit("/", 2)[-2]
    return "/test/" in normalized or "/tests/" in normalized or name.startswith("test_") or name.endswith(("_test", "_spec"))


def _is_config_path(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return name.startswith(("config.", "settings.")) or name in {
        "pyproject.toml", "package.json", "cargo.toml", "go.mod", "dockerfile", ".env.example"
    }


def _is_file_node(node: Node) -> bool:
    basename = node.path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return node.label.casefold() == basename or node.kind in {
        "file", "python", "javascript", "typescript", "go", "rust", "java", "csharp", "cpp", "ruby", "toml", "json"
    }


def _resolve_ast_owner(candidates: tuple[Node, ...] | list[Node], line: int) -> Node | None:
    if not candidates:
        return None
    return min(candidates, key=lambda node: abs((node.line or line) - line))


def _stable_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha1("\0".join(values).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _data_node(
    nodes: dict[str, Node],
    owner: Node,
    name: str,
    path: str,
    line: int,
    *,
    kind: str = "data_symbol",
) -> str:
    node_id = _stable_id(kind, owner.id, name)
    nodes.setdefault(node_id, Node(
        node_id,
        name,
        kind=kind,
        path=path,
        summary=f"L{line} {name}",
        parent=owner.id,
        source=owner.source,
        confidence=0.95,
    ))
    return node_id


def _type_node(nodes: dict[str, Node], path: str, name: str, line: int) -> str:
    name = name or "unknown"
    node_id = _stable_id("type", path, name)
    nodes.setdefault(node_id, Node(node_id, name, kind="type", path=path, summary=f"L{line} {name}", confidence=0.9))
    return node_id


def _annotation(annotation: ast.expr) -> str:
    try:
        return ast.unparse(annotation)
    except (AttributeError, ValueError):
        return type(annotation).__name__


def _evidence_edge(source: str, target: str, relation: str, path: str, line: int, evidence: str) -> Edge:
    return Edge(
        source,
        target,
        relation,
        confidence=0.95,
        provenance="python_ast_provider",
        evidence=evidence,
        source_location=f"{path}:{line}",
    )
