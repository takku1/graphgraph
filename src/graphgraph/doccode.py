from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core import Graph, Node
from .terms import term_key


DOC_KINDS = {"section", "concept", "markdown", "rst", "html", "text", "doc"}
CODE_KINDS = {
    "file",
    "module",
    "class",
    "function",
    "method",
    "struct",
    "enum",
    "trait",
    "impl",
    "interface",
    "package",
    "service",
    "data",
}

DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".html", ".htm"}
CODE_EXTENSIONS = {
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".kt",
    ".swift",
    ".scala",
    ".rb",
    ".php",
    ".lua",
    ".sql",
}


@dataclass(frozen=True)
class DocCodePairing:
    key: str
    doc_nodes: tuple[str, ...]
    code_nodes: tuple[str, ...]
    other_nodes: tuple[str, ...]


@dataclass(frozen=True)
class DocCodeCoverage:
    paired_keys: int
    doc_only_keys: int
    code_only_keys: int
    unlabeled_keys: int
    paired_examples: tuple[DocCodePairing, ...]
    doc_only_examples: tuple[DocCodePairing, ...]
    code_only_examples: tuple[DocCodePairing, ...]
    unlabeled_examples: tuple[DocCodePairing, ...]


@dataclass(frozen=True)
class DocCodeComponentPairing:
    component: str
    doc_nodes: tuple[str, ...]
    code_nodes: tuple[str, ...]
    other_nodes: tuple[str, ...]
    doc_keys: tuple[str, ...]
    code_keys: tuple[str, ...]


@dataclass(frozen=True)
class DocCodeComponentCoverage:
    paired_components: int
    doc_only_components: int
    code_only_components: int
    unlabeled_components: int
    paired_examples: tuple[DocCodeComponentPairing, ...]
    doc_only_examples: tuple[DocCodeComponentPairing, ...]
    code_only_examples: tuple[DocCodeComponentPairing, ...]
    unlabeled_examples: tuple[DocCodeComponentPairing, ...]


def node_semantic_key(node: Node) -> str:
    base = node.label or Path(node.path).stem or node.id
    return term_key(base)


def is_doc_like(node: Node) -> bool:
    path = node.path.replace("\\", "/").lower()
    if node.kind in DOC_KINDS:
        return True
    return path.startswith("docs/") or Path(path).suffix in DOC_EXTENSIONS


def is_code_like(node: Node) -> bool:
    path = node.path.replace("\\", "/").lower()
    if node.kind in CODE_KINDS:
        return True
    return Path(path).suffix in CODE_EXTENSIONS or path.startswith(("src/", "lib/", "app/", "server/", "crates/", "packages/"))


def summarize_doc_code_coverage(graph: Graph) -> DocCodeCoverage:
    grouped: dict[str, DictBucket] = {}
    for node in graph.nodes.values():
        key = node_semantic_key(node)
        if not key:
            continue
        bucket = grouped.setdefault(key, DictBucket())
        if is_doc_like(node):
            bucket.doc_nodes.append(node.id)
        elif is_code_like(node):
            bucket.code_nodes.append(node.id)
        else:
            bucket.other_nodes.append(node.id)

    paired = []
    doc_only = []
    code_only = []
    unlabeled = []
    for key, bucket in grouped.items():
        pairing = DocCodePairing(
            key=key,
            doc_nodes=tuple(sorted(bucket.doc_nodes)),
            code_nodes=tuple(sorted(bucket.code_nodes)),
            other_nodes=tuple(sorted(bucket.other_nodes)),
        )
        if bucket.doc_nodes and bucket.code_nodes:
            paired.append(pairing)
        elif bucket.doc_nodes:
            doc_only.append(pairing)
        elif bucket.code_nodes:
            code_only.append(pairing)
        else:
            unlabeled.append(pairing)

    paired.sort(key=_pairing_sort_key)
    doc_only.sort(key=_pairing_sort_key)
    code_only.sort(key=_pairing_sort_key)
    unlabeled.sort(key=_pairing_sort_key)

    return DocCodeCoverage(
        paired_keys=len(paired),
        doc_only_keys=len(doc_only),
        code_only_keys=len(code_only),
        unlabeled_keys=len(unlabeled),
        paired_examples=tuple(paired[:8]),
        doc_only_examples=tuple(doc_only[:8]),
        code_only_examples=tuple(code_only[:8]),
        unlabeled_examples=tuple(unlabeled[:8]),
    )


def summarize_doc_code_components(graph: Graph) -> DocCodeComponentCoverage:
    components = _active_components(graph)
    paired: list[DocCodeComponentPairing] = []
    doc_only: list[DocCodeComponentPairing] = []
    code_only: list[DocCodeComponentPairing] = []
    unlabeled: list[DocCodeComponentPairing] = []

    for index, component_nodes in enumerate(components, start=1):
        doc_nodes: list[str] = []
        code_nodes: list[str] = []
        other_nodes: list[str] = []
        doc_keys: list[str] = []
        code_keys: list[str] = []
        for node_id in component_nodes:
            node = graph.nodes[node_id]
            key = node_semantic_key(node)
            if is_doc_like(node):
                doc_nodes.append(node_id)
                if key:
                    doc_keys.append(key)
            elif is_code_like(node):
                code_nodes.append(node_id)
                if key:
                    code_keys.append(key)
            else:
                other_nodes.append(node_id)

        pairing = DocCodeComponentPairing(
            component=f"component_{index}",
            doc_nodes=tuple(sorted(doc_nodes)),
            code_nodes=tuple(sorted(code_nodes)),
            other_nodes=tuple(sorted(other_nodes)),
            doc_keys=tuple(sorted(dict.fromkeys(doc_keys))),
            code_keys=tuple(sorted(dict.fromkeys(code_keys))),
        )
        if pairing.doc_nodes and pairing.code_nodes:
            paired.append(pairing)
        elif pairing.doc_nodes:
            doc_only.append(pairing)
        elif pairing.code_nodes:
            code_only.append(pairing)
        else:
            unlabeled.append(pairing)

    paired.sort(key=_component_sort_key)
    doc_only.sort(key=_component_sort_key)
    code_only.sort(key=_component_sort_key)
    unlabeled.sort(key=_component_sort_key)

    return DocCodeComponentCoverage(
        paired_components=len(paired),
        doc_only_components=len(doc_only),
        code_only_components=len(code_only),
        unlabeled_components=len(unlabeled),
        paired_examples=tuple(paired[:8]),
        doc_only_examples=tuple(doc_only[:8]),
        code_only_examples=tuple(code_only[:8]),
        unlabeled_examples=tuple(unlabeled[:8]),
    )


def doc_code_bias(graph: Graph) -> float:
    """Return a 0..1 balance hint for doc-vs-code retrieval bias."""
    coverage = summarize_doc_code_components(graph)
    doc_side = coverage.paired_components + coverage.doc_only_components
    code_side = coverage.paired_components + coverage.code_only_components
    total = doc_side + code_side
    if total <= 0:
        return 0.5
    return doc_side / total


@dataclass
class DictBucket:
    doc_nodes: list[str] = field(default_factory=list)
    code_nodes: list[str] = field(default_factory=list)
    other_nodes: list[str] = field(default_factory=list)


def _pairing_sort_key(pairing: DocCodePairing) -> tuple[int, str]:
    return (-len(pairing.doc_nodes) - len(pairing.code_nodes), pairing.key)


def _component_sort_key(pairing: DocCodeComponentPairing) -> tuple[int, str]:
    return (-len(pairing.doc_nodes) - len(pairing.code_nodes), pairing.component)


def _active_components(graph: Graph) -> list[tuple[str, ...]]:
    parent: dict[str, str] = {}

    def find(node_id: str) -> str:
        parent.setdefault(node_id, node_id)
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    active_nodes = [node_id for node_id, node in graph.nodes.items() if node.active]
    for node_id in active_nodes:
        parent.setdefault(node_id, node_id)

    for edge in graph.edges:
        if not edge.active:
            continue
        if edge.source not in parent or edge.target not in parent:
            continue
        union(edge.source, edge.target)

    components: dict[str, list[str]] = {}
    for node_id in active_nodes:
        components.setdefault(find(node_id), []).append(node_id)
    return [tuple(sorted(nodes)) for nodes in components.values()]
