from __future__ import annotations

import re
from collections import Counter

from ..graph.core import Edge, Graph, Node

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOP = {"the", "and", "for", "from", "with", "this", "that", "into", "node", "file", "class", "function"}


def detect_communities(graph: Graph, *, max_rounds: int = 12) -> dict[str, str]:
    """Deterministic weighted label propagation without an optional graph dependency."""
    active = sorted(node_id for node_id, node in graph.nodes.items() if node.active)
    labels = {node_id: node_id for node_id in active}
    neighbors: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in active}
    for edge in graph.edges:
        if edge.active and edge.source in neighbors and edge.target in neighbors:
            weight = max(0.0, edge.traversal_val)
            if weight:
                neighbors[edge.source].append((edge.target, weight))
                neighbors[edge.target].append((edge.source, weight))
    for _ in range(max_rounds):
        changed = False
        for node_id in active:
            scores: Counter[str] = Counter()
            for neighbor, weight in neighbors[node_id]:
                scores[labels[neighbor]] += weight
            if scores:
                best = min(scores, key=lambda label: (-scores[label], label))
                if best != labels[node_id]:
                    labels[node_id] = best
                    changed = True
        if not changed:
            break
    canonical = {label: f"community:{index + 1}" for index, label in enumerate(sorted(set(labels.values())))}
    return {node_id: canonical[label] for node_id, label in labels.items()}


def build_hierarchy(graph: Graph, communities: dict[str, str] | None = None) -> Graph:
    communities = communities or detect_communities(graph)
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    members: dict[str, list[Node]] = {}
    for node_id, community in communities.items():
        if node_id in nodes:
            members.setdefault(community, []).append(nodes[node_id])
    for community, community_nodes in sorted(members.items()):
        terms = Counter(
            word.casefold()
            for node in community_nodes
            for word in _WORD_RE.findall(" ".join((node.label, node.kind, node.path, node.summary)))
            if word.casefold() not in _STOP
        )
        keywords = [term for term, _count in terms.most_common(6)]
        paths = Counter((node.path.replace("\\", "/").split("/", 1)[0] if node.path else "") for node in community_nodes)
        dominant_path = paths.most_common(1)[0][0] if paths else ""
        nodes[community] = Node(
            id=community,
            label=dominant_path or ", ".join(keywords[:3]) or community,
            kind="community",
            summary=f"{len(community_nodes)} nodes; topics: {', '.join(keywords)}",
            facts=tuple(f"keyword:{keyword}" for keyword in keywords),
            scope=dominant_path,
            confidence=0.8,
        )
        for member in community_nodes:
            edges.append(Edge(community, member.id, "contains", confidence=0.8, provenance="community"))
    return Graph(nodes=nodes, edges=edges, metadata={**graph.metadata, "communities": str(len(members))})
