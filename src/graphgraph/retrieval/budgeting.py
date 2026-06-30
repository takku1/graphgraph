from __future__ import annotations

from ..core import Edge, Graph
from ..ontology import is_weak_relation
from ..policies import path_matches

DEFAULT_EDGE_TYPE_LIMITS = {
    "references": 16,
    "links": 16,
    "includes": 16,
}
DEFAULT_UNKNOWN_WEAK_LIMIT = 12


def enrich_runtime_context(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    max_nodes: int | None = None,
    decision_trace_limit: int = 3,
) -> tuple[set[str], list[Edge]]:
    included = set(nodes)
    out_edges = list(edges)

    def room() -> bool:
        return max_nodes is None or len(included) < max_nodes

    policy_nodes = [node for node in graph.nodes.values() if node.kind == "policy" and node.active]
    for policy in policy_nodes:
        if not room():
            break
        for nid in list(included):
            node = graph.nodes.get(nid)
            if not node or not node.path:
                continue
            scopes = tuple(s.strip() for s in policy.scope.split(",") if s.strip())
            if scopes and any(path_matches(scope, node.path) for scope in scopes):
                included.add(policy.id)
                out_edges.append(Edge(nid, policy.id, "constrained_by", provenance="policy", confidence=1.0))
                break

    trace_count = 0
    for edge in graph.edges:
        if trace_count >= decision_trace_limit or not room():
            break
        if edge.type not in {"used_input", "applied_policy"}:
            continue
        if edge.target in included and edge.source in graph.nodes:
            trace = graph.nodes[edge.source]
            if trace.kind == "decision_trace" and trace.active and edge.source not in included:
                included.add(edge.source)
                out_edges.append(edge)
                trace_count += 1

    return included, out_edges


def budget_edges(edges: list[Edge], max_nodes: int | None = None, weak_limit: int | None = None) -> list[Edge]:
    """Limit weak edge types after graph expansion."""
    limits = dict(DEFAULT_EDGE_TYPE_LIMITS)
    if weak_limit is not None:
        for key in limits:
            limits[key] = weak_limit
    if max_nodes is not None:
        if weak_limit is None:
            limits["references"] = max(8, min(limits["references"], max_nodes // 2))
        else:
            limits["references"] = min(limits["references"], max(1, max_nodes // 2))

    counts: dict[str, int] = {}
    kept: list[Edge] = []
    for edge in edges:
        limit = limits.get(edge.type)
        if limit is None and is_weak_relation(edge.type):
            limit = weak_limit if weak_limit is not None else DEFAULT_UNKNOWN_WEAK_LIMIT
        if limit is None:
            kept.append(edge)
            continue
        current = counts.get(edge.type, 0)
        if current < limit:
            counts[edge.type] = current + 1
            kept.append(edge)
    return kept
