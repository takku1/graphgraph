from __future__ import annotations

from dataclasses import replace

from ..core import Edge, Graph
from ..doccode import doc_code_bias
from ..ontology import provenance_confidence
from ..planning import ContextPlan, compute_subgraph_stats, plan_context
from ..planning.budgets import plan_terms
from ..planning.shape import profile_graph_shape, recommend_node_budget
from ..traversal import relation_rank, traversal_policy

from .budgeting import budget_edges, enrich_runtime_context
from .models import Match, RetrievalResult
from .search import search_nodes


STRUCTURAL_QUERY_CLASSES = {"blast_radius", "multi_hop_path", "reverse_lookup"}
NON_STRUCTURAL_KINDS = {"concept", "section", "markdown", "rst", "html", "text"}


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
    from ..planning.budgets import doc_intensity_score
    doc_intensity = doc_intensity_score(query_class, query)
    graph_bias = doc_code_bias(graph)
    doc_intensity *= 0.75 + graph_bias * 0.5
    plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops)
    if max_nodes is None:
        plan = apply_shape_budget(graph, plan, query)
    candidate_limit = max(plan.anchor_limit, plan.anchor_limit * 3 if query_class in STRUCTURAL_QUERY_CLASSES else plan.anchor_limit)
    matches = search_nodes(graph, query, limit=max(candidate_limit, 1), doc_intensity=doc_intensity)
    effective_anchor_limit = _adaptive_anchor_limit(matches, plan, query) if query_class in STRUCTURAL_QUERY_CLASSES else plan.anchor_limit
    selected_matches = select_anchor_matches(matches, effective_anchor_limit, query_class)
    starts = tuple(match.node.id for match in selected_matches)
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


def apply_shape_budget(graph: Graph, plan: ContextPlan, query: str) -> ContextPlan:
    recommendation = recommend_node_budget(plan.query_class, query, profile_graph_shape(graph))
    if recommendation.recommended_budget == plan.node_budget:
        return plan
    return replace(
        plan,
        node_budget=recommendation.recommended_budget,
        reason=f"{plan.reason}; shape budget: {recommendation.reason}",
        planner_version=f"{plan.planner_version}_shape_budget",
    )


def _adaptive_anchor_limit(matches: tuple[Match, ...], plan: ContextPlan, query: str) -> int:
    """Pick a smaller anchor fanout when the search scores make the answer shape obvious.

    The production default of 6 is still the upper bound for short structural queries,
    but saved benchmark traces show three recurring patterns:
    - concept/section heads usually need one extra anchor to pull the code node;
    - single-token symbol queries split into either a strong singleton or a wide plateau;
    - file-like python/markdown/class anchors are often self-sufficient.

    The goal is to reduce anchor noise without touching the downstream expansion budget.
    """
    if not matches:
        return plan.anchor_limit

    top = matches[0]
    query_terms = plan_terms(query)
    term_count = len(query_terms)
    limit = plan.anchor_limit

    if top.node.kind in {"concept", "section"}:
        return min(limit, 2)

    if term_count == 1:
        if top.node.kind in {"function", "method"}:
            top_stem = _node_stem(top.node.path)
            same_stem = sum(1 for match in matches[:6] if _node_stem(match.node.path) == top_stem)
            top3_distinct = len({_node_stem(match.node.path) for match in matches[:3]})
            top5_ratio = matches[4].score / top.score if len(matches) >= 5 and top.score > 0 else 0.0

            if same_stem >= 4:
                return min(limit, 4)
            if len(matches) >= 2 and top.score / max(matches[1].score, 1e-9) >= 1.5 and top5_ratio < 0.75:
                return min(limit, 1)
            if len(matches) >= 3 and matches[2].score / top.score >= 0.98 and top3_distinct <= 2:
                return min(limit, 3)
            if top3_distinct >= 3 and top5_ratio >= 0.75:
                return min(limit, 5)
            return min(limit, 2 if top.score < 20 else 1)

        if top.node.kind == "python":
            return min(limit, 1 if top.score >= 90 else 2)

        if top.node.kind in {"class", "markdown", "java", "header", "source"}:
            return min(limit, 1)

    if term_count >= 2:
        if top.node.kind == "python":
            return min(limit, 1 if top.score >= 90 else 2)
        if top.node.kind in {"class", "markdown", "java"}:
            return min(limit, 1)

    if len(matches) >= 3 and matches[2].score / top.score >= 0.98:
        return min(limit, 3)
    if len(matches) >= 5 and matches[4].score / top.score >= 0.80:
        return min(limit, 5)
    return limit


def _node_stem(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def select_anchor_matches(matches: tuple[Match, ...], anchor_limit: int, query_class: str) -> tuple[Match, ...]:
    if query_class not in STRUCTURAL_QUERY_CLASSES:
        return matches[:anchor_limit]
    structural = [match for match in matches if match.node.kind not in NON_STRUCTURAL_KINDS]
    if not structural:
        return matches[:anchor_limit]
    selected: list[Match] = []
    seen: set[str] = set()
    for match in structural:
        if match.node.id not in seen:
            selected.append(match)
            seen.add(match.node.id)
        if len(selected) >= anchor_limit:
            return tuple(selected)
    for match in matches:
        if match.node.id not in seen:
            selected.append(match)
            seen.add(match.node.id)
        if len(selected) >= anchor_limit:
            break
    return tuple(selected)
