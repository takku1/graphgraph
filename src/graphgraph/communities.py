from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass

from .core import Edge, Graph, Node


@dataclass(frozen=True)
class Community:
    id: str
    label: str
    nodes: tuple[str, ...]
    summary: str


def detect_path_communities(graph: Graph, max_members: int = 200) -> list[Community]:
    groups: dict[str, list[str]] = defaultdict(list)
    for node_id, node in graph.nodes.items():
        key = _community_key(node)
        groups[key].append(node_id)

    communities: list[Community] = []
    for idx, (key, node_ids) in enumerate(sorted(groups.items())):
        if len(node_ids) < 2:
            continue
        selected = tuple(sorted(node_ids)[:max_members])
        kinds = Counter(graph.nodes[nid].kind for nid in selected)
        labels = [graph.nodes[nid].label for nid in selected[:8]]
        communities.append(Community(
            id=f"community_{idx + 1}",
            label=key,
            nodes=selected,
            summary=f"{len(node_ids)} nodes; top kinds: {_fmt_counts(kinds)}; examples: {', '.join(labels)}",
        ))
    return communities


def add_community_nodes(graph: Graph) -> Graph:
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    for community in detect_path_communities(graph):
        nodes[community.id] = Node(
            id=community.id,
            label=community.label,
            kind="community",
            summary=community.summary,
            scope=community.label,
            confidence=0.8,
            source="community_detection",
        )
        for node_id in community.nodes:
            edges.append(Edge(community.id, node_id, "contains", weight=0.7, confidence=0.8, provenance="community_detection"))
    return Graph(nodes=nodes, edges=_dedupe_edges(edges), metadata={**graph.metadata, "communities": "path"})


def connected_components(graph: Graph, relation_types: set[str] | None = None, max_components: int = 100) -> list[Community]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if relation_types and edge.type not in relation_types:
            continue
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)

    seen: set[str] = set()
    out: list[Community] = []
    for node_id in sorted(graph.nodes):
        if node_id in seen:
            continue
        queue = deque([node_id])
        component: list[str] = []
        seen.add(node_id)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        if len(component) >= 2:
            kinds = Counter(graph.nodes[nid].kind for nid in component if nid in graph.nodes)
            label = _component_label(graph, component)
            out.append(Community(
                id=f"component_{len(out) + 1}",
                label=label,
                nodes=tuple(sorted(component)),
                summary=f"{len(component)} nodes; top kinds: {_fmt_counts(kinds)}",
            ))
        if len(out) >= max_components:
            break
    return out


def _community_key(node: Node) -> str:
    if node.scope:
        return node.scope
    if node.path:
        parts = node.path.split("/")
        dirs = parts[:-1] if len(parts) > 1 else parts
        if len(dirs) >= 3:
            return "/".join(dirs[:3])
        if len(dirs) >= 2:
            return "/".join(dirs[:2])
        if dirs:
            return dirs[0]
        return parts[0]
    if node.kind == "concept":
        return "concepts"
    return node.kind or "unknown"


def _component_label(graph: Graph, node_ids: list[str]) -> str:
    paths = [graph.nodes[nid].path for nid in node_ids if graph.nodes[nid].path]
    if paths:
        parts = paths[0].split("/")
        return "/".join(parts[: min(3, len(parts))])
    return graph.nodes[node_ids[0]].kind


def _fmt_counts(counts: Counter[str]) -> str:
    return ", ".join(f"{kind}={count}" for kind, count in counts.most_common(4))


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Edge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.type)
        if key not in seen:
            seen.add(key)
            out.append(edge)
    return out
