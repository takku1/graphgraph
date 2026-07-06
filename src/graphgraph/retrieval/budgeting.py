from __future__ import annotations

import math
from collections import Counter

from ..core import Edge, Graph
from ..ontology import is_weak_relation, provenance_confidence, traversal_strength
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
    """Limit weak edge types after graph expansion.

    Low-density contexts keep the historic per-relation caps. Dense or
    weak-heavy contexts use a shaped edge budget: relation quotas are allocated
    by relation mass and utility, then individual edges are ranked by
    confidence, provenance, traversal strength, and endpoint diversity.
    """
    if _use_shaped_edge_budget(edges, max_nodes=max_nodes, weak_limit=weak_limit):
        return _budget_edges_shaped(edges, max_nodes=max_nodes, weak_limit=weak_limit)

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


def _use_shaped_edge_budget(edges: list[Edge], max_nodes: int | None, weak_limit: int | None) -> bool:
    if weak_limit is not None or len(edges) < 24:
        return False
    limited_relations = {edge.type for edge in edges if _limited_relation(edge.type)}
    if len(limited_relations) <= 1:
        return False
    weak_count = sum(1 for edge in edges if _limited_relation(edge.type))
    weak_ratio = weak_count / max(1, len(edges))
    node_scale = max_nodes or len(edges)
    return weak_ratio >= 0.55 or weak_count > max(16, node_scale)


def _budget_edges_shaped(edges: list[Edge], max_nodes: int | None, weak_limit: int | None) -> list[Edge]:
    limited = [edge for edge in edges if _limited_relation(edge.type)]
    if not limited:
        return list(edges)

    target = _weak_edge_target(len(limited), len(edges), max_nodes=max_nodes, weak_limit=weak_limit)
    if len(limited) <= target:
        return list(edges)

    quotas = _relation_quotas(limited, target)
    kept_limited = _select_shaped_edges(limited, quotas)

    kept_ids = {(edge.source, edge.target, edge.type) for edge in kept_limited}
    kept: list[Edge] = []
    for edge in edges:
        if not _limited_relation(edge.type) or (edge.source, edge.target, edge.type) in kept_ids:
            kept.append(edge)
    return kept


def _limited_relation(relation: str) -> bool:
    return relation in DEFAULT_EDGE_TYPE_LIMITS or is_weak_relation(relation)


def _weak_edge_target(weak_count: int, edge_count: int, *, max_nodes: int | None, weak_limit: int | None) -> int:
    if weak_limit is not None:
        return max(1, min(weak_count, weak_limit))
    if max_nodes is None:
        return min(weak_count, DEFAULT_UNKNOWN_WEAK_LIMIT)
    density = edge_count / max(1, max_nodes)
    density_scale = 1.0 / math.sqrt(max(1.0, density))
    base = max(8, int(round(max_nodes * 0.55 * density_scale)))
    return max(4, min(weak_count, base))


def _relation_quotas(edges: list[Edge], target: int) -> dict[str, int]:
    counts = Counter(edge.type for edge in edges)
    utility_sums: Counter[str] = Counter()
    for edge in edges:
        utility_sums[edge.type] += edge.confidence * provenance_confidence(edge.provenance) * max(0.05, edge.weight)
    weighted = {
        relation: math.sqrt(count) * max(0.05, traversal_strength(relation)) * max(0.05, utility_sums[relation] / count)
        for relation, count in counts.items()
    }
    total = sum(weighted.values()) or 1.0
    quotas = {relation: max(1, int(math.floor(target * value / total))) for relation, value in weighted.items()}
    while sum(quotas.values()) < target:
        relation = max(counts, key=lambda rel: (weighted[rel] / max(1, quotas[rel]), counts[rel]))
        quotas[relation] += 1
    while sum(quotas.values()) > target:
        relation = max((rel for rel, quota in quotas.items() if quota > 1), key=lambda rel: quotas[rel], default="")
        if not relation:
            break
        quotas[relation] -= 1
    return {relation: min(counts[relation], quota) for relation, quota in quotas.items()}


def _select_shaped_edges(edges: list[Edge], quotas: dict[str, int]) -> list[Edge]:
    selected: list[Edge] = []
    seen_endpoint_degree: Counter[str] = Counter()
    grouped: dict[str, list[Edge]] = {}
    for edge in edges:
        grouped.setdefault(edge.type, []).append(edge)

    for relation, relation_edges in grouped.items():
        quota = quotas.get(relation, 0)
        if quota <= 0:
            continue
        ranked = sorted(
            relation_edges,
            key=lambda edge: (
                -_edge_machine_utility(edge, seen_endpoint_degree),
                edge.source,
                edge.target,
            ),
        )
        for edge in ranked[:quota]:
            selected.append(edge)
            seen_endpoint_degree[edge.source] += 1
            seen_endpoint_degree[edge.target] += 1
    selected_keys = {(edge.source, edge.target, edge.type): index for index, edge in enumerate(selected)}
    return sorted(selected, key=lambda edge: selected_keys[(edge.source, edge.target, edge.type)])


def _edge_machine_utility(edge: Edge, endpoint_degree: Counter[str]) -> float:
    confidence = edge.confidence * provenance_confidence(edge.provenance)
    utility = traversal_strength(edge.type) * confidence * edge.weight
    diversity_penalty = 1.0 / math.sqrt(1.0 + endpoint_degree[edge.source] + endpoint_degree[edge.target])
    return utility * diversity_penalty
