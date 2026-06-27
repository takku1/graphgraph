from __future__ import annotations

from ..core import Edge, Graph
from ..ontology import provenance_confidence
from ..planning import ContextPlan, compute_subgraph_stats, plan_context
from ..traversal import relation_rank, traversal_policy

from .budgeting import budget_edges, enrich_runtime_context
from .models import RetrievalResult
from .search import search_nodes


def expand_context(
    graph: Graph,
    starts: tuple[str, ...],
    plan: ContextPlan,
    scopes: tuple[str, ...] = (),
) -> tuple[set[str], list[Edge]]:
    policy = traversal_policy(plan.query_class)
    nodes, edges = graph.expand(
        list(starts),
        hops=plan.hops,
        max_nodes=plan.node_budget,
        scopes=scopes,
        direction=plan.direction,
    )
    edges = [
        edge for edge in edges
        if edge.confidence * provenance_confidence(edge.provenance) >= plan.min_confidence
    ]
    edges = sorted(edges, key=lambda e: (*relation_rank(e.type, policy), e.source, e.target))
    
    # --- DYNAMIC EDGE DENSITY THROTTLE ---
    effective_node_budget = plan.node_budget
    if plan.node_budget is not None and len(nodes) > 10:
        density = len(edges) / max(1, len(nodes))
        if density > 1.5:
            scale = max(0.4, min(1.0, 1.5 / density))
            effective_node_budget = max(25, int(plan.node_budget * scale))

    stats = compute_subgraph_stats(graph, nodes, edges)
    weak_limit = adaptive_weak_edge_limit(plan.weak_edge_limit, stats.weak_edge_ratio, stats.relation_entropy, stats.edges)
    edges = budget_edges(edges, max_nodes=effective_node_budget, weak_limit=weak_limit)
    return enrich_runtime_context(graph, nodes, edges, max_nodes=effective_node_budget)


def adaptive_weak_edge_limit(base_limit: int, weak_edge_ratio: float, relation_entropy: float, edge_count: int) -> int:
    if edge_count < base_limit * 2 or weak_edge_ratio < 0.75:
        return base_limit
    if relation_entropy <= 0.2:
        return max(3, base_limit // 2)
    return max(4, int(base_limit * 0.75))


def retrieve_context(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
) -> RetrievalResult:
    from ..planning.budgets import is_doc_query
    is_doc = is_doc_query(query_class, query)
    plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops)
    matches = search_nodes(graph, query, limit=max(plan.anchor_limit, 1), is_doc=is_doc)
    starts = tuple(match.node.id for match in matches[: plan.anchor_limit])
    if not starts:
        return RetrievalResult(starts=(), matches=matches, nodes=set(), edges=[])

    if query_class == "spreading_activation":
        from .activation import ActivationStateCache, spreading_activation
        cache = ActivationStateCache()
        prev_state = cache.load()
        nodes, edges = spreading_activation(
            graph,
            list(starts),
            max_nodes=plan.node_budget or 120,
            previous_activation=prev_state,
        )
    else:
        nodes, edges = expand_context(graph, starts, plan, scopes=scopes)
    return RetrievalResult(starts=starts, matches=matches, nodes=nodes, edges=edges)
