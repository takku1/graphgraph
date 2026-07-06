from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ..graph.core import Graph
from .budgets import default_node_budget, is_doc_query

SOURCE_KINDS = {"python", "typescript", "javascript", "rust", "go", "java", "c", "cpp", "header", "lean"}
SYMBOL_KINDS = {"function", "method", "class", "struct", "enum", "trait", "theorem"}
DOC_KINDS = {"markdown", "rst", "text", "section", "concept"}
WEAK_RELATIONS = {"references", "links", "mentions", "discusses", "section_of"}


@dataclass(frozen=True)
class GraphShape:
    nodes: int
    edges: int
    source_files: int
    symbol_nodes: int
    doc_nodes: int
    import_edges: int
    calls_edges: int
    explains_edges: int
    edge_density: float
    imports_per_source_file: float
    calls_per_symbol: float
    weak_edge_ratio: float
    doc_node_ratio: float
    top_node_kinds: tuple[tuple[str, int], ...]
    top_relations: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class BudgetRecommendation:
    query_class: str
    base_budget: int | None
    recommended_budget: int | None
    mode: str
    reason: str


@dataclass(frozen=True)
class ContextWindowRecommendation:
    query_class: str
    base_budget: int | None
    recommended_budget: int | None
    target_tokens: int
    estimated_tokens: int
    saturation: float
    page_node_budget: int | None
    mode: str
    reason: str


def profile_graph_shape(graph: Graph) -> GraphShape:
    node_kinds = Counter(node.kind for node in graph.nodes.values())
    relations = Counter(edge.type for edge in graph.edges if edge.active)
    nodes = len(graph.nodes)
    edges = sum(relations.values())
    source_files = sum(count for kind, count in node_kinds.items() if kind in SOURCE_KINDS)
    symbol_nodes = sum(count for kind, count in node_kinds.items() if kind in SYMBOL_KINDS)
    doc_nodes = sum(count for kind, count in node_kinds.items() if kind in DOC_KINDS)
    import_edges = relations.get("imports", 0)
    calls_edges = relations.get("calls", 0)
    explains_edges = relations.get("explains", 0)
    weak_edges = sum(count for relation, count in relations.items() if relation in WEAK_RELATIONS)
    return GraphShape(
        nodes=nodes,
        edges=edges,
        source_files=source_files,
        symbol_nodes=symbol_nodes,
        doc_nodes=doc_nodes,
        import_edges=import_edges,
        calls_edges=calls_edges,
        explains_edges=explains_edges,
        edge_density=round(edges / max(1, nodes), 4),
        imports_per_source_file=round(import_edges / max(1, source_files), 4),
        calls_per_symbol=round(calls_edges / max(1, symbol_nodes), 4),
        weak_edge_ratio=round(weak_edges / max(1, edges), 4),
        doc_node_ratio=round(doc_nodes / max(1, nodes), 4),
        top_node_kinds=tuple(node_kinds.most_common(10)),
        top_relations=tuple(relations.most_common(10)),
    )


def recommend_node_budget(query_class: str, query: str, shape: GraphShape) -> BudgetRecommendation:
    base = default_node_budget(query_class, query)
    if base is None:
        return BudgetRecommendation(query_class, base, base, "unbounded", "caller requested no node cap")
    if is_doc_query(query_class, query) or query_class == "negative_query":
        return BudgetRecommendation(query_class, base, base, "fixed", "doc/negative queries keep measured fixed budget")

    reasons: list[str] = []

    # 1. Map query class to baseline query complexity parameter lambda_
    # Higher lambda_ means target evidence is concentrated; lower lambda_ means it is distributed.
    lambda_map = {
        "direct_lookup": 0.08,
        "reverse_lookup": 0.08,
        "multi_hop_path": 0.05,
        "blast_radius": 0.035,
        "subsystem_summary": 0.035,
        "spreading_activation": 0.035,
    }
    lambda_ = lambda_map.get(query_class, 0.04)

    # 2. Adjust query complexity based on graph shape parameters
    if shape.doc_node_ratio >= 0.65:
        lambda_ *= 1.2
        if query_class in {"multi_hop_path", "reverse_lookup"}:
            reasons.append("doc-heavy graph trims structural noise")
        else:
            reasons.append("doc-heavy graph keeps recall-first broad expansion")

    if shape.nodes <= 500:
        lambda_ *= 1.25
        if query_class in {"direct_lookup", "reverse_lookup"}:
            reasons.append("small graph direct/reverse lookup")
    elif shape.nodes >= 5000:
        lambda_ *= 1.15
        if query_class in {"direct_lookup", "reverse_lookup"}:
            reasons.append("large graph narrows direct/reverse lookup")
        elif query_class in {"blast_radius", "subsystem_summary"} and shape.edge_density >= 2.5:
            reasons.append("large dense graph keeps recall-first broad expansion")

    if shape.weak_edge_ratio >= 0.45 and query_class in {"blast_radius", "subsystem_summary"}:
        reasons.append("weak-edge-heavy graph keeps recall-first broad expansion")

    if shape.imports_per_source_file < 0.05 and shape.source_files >= 20:
        reasons.append("warning: import topology looks under-extracted")

    # 3. Dynamic marginal token cost per node (tau) from fitted regression surface
    density = adjusted_edge_density(shape)
    tau = 1.496 + 6.215 * density

    # 4. Coarse Planning: Regularized Budget Heuristic:
    # Objective: Maximize expected information gain minus token cost:
    # U(n) = (1 - exp(-lambda_ * n)) - c * (tau * n)
    # Taking the derivative and setting to zero yields the closed-form optimum:
    # n* = (1 / lambda_) * ln(lambda_ / (c * tau))
    # where c = 10^-4 is the empirically tuned token penalty cost.
    c = 1e-4
    ratio = max(1.1, lambda_ / (c * tau))
    budget_n = int(round((1.0 / lambda_) * math.log(ratio)))

    # 5. Enforce operational bounds
    lower_bound, upper_bound = context_node_bounds(query_class, shape)
    recommended = min(upper_bound, max(lower_bound, budget_n))

    # Broad evidence-gathering classes are recall-first: do not trim below default base
    if query_class in {"blast_radius", "subsystem_summary"}:
        recommended = max(base, recommended)

    # If regularized budget heuristic doesn't change budget, report as measured default
    if recommended == base:
        mode = "measured_default"
        reason = "; ".join(reasons) if reasons else "keep measured default budget"
    else:
        mode = "candidate"
        reason = f"Regularized budget: n*={budget_n} (lambda={lambda_:.3f}, tau={tau:.3f})"
        if reasons:
            reason = f"{reason}; " + "; ".join(reasons)

    return BudgetRecommendation(query_class, base, recommended, mode, reason)


def recommend_context_window(
    query_class: str,
    query: str,
    shape: GraphShape,
    *,
    target_tokens: int | None = None,
) -> ContextWindowRecommendation:
    """Recommend a token-window-aware node budget without reading answer keys.

    This is intentionally separate from the measured production default. It
    estimates how many nodes a query can carry before the packet exceeds a
    target token window, then records whether paging/sparsification is needed.
    Benchmarks decide whether the recommendation is promotable.
    """
    base = default_node_budget(query_class, query)
    target = target_tokens or default_context_token_target(query_class, query)
    if is_doc_query(query_class, query) or query_class == "negative_query":
        estimated = estimate_gg_max_tokens(base, shape)
        return ContextWindowRecommendation(
            query_class=query_class,
            base_budget=base,
            recommended_budget=base,
            target_tokens=target,
            estimated_tokens=estimated,
            saturation=round(estimated / max(1, target), 4),
            page_node_budget=None,
            mode="fixed",
            reason="doc/negative queries use fixed compact budgets",
        )

    shape_candidate = recommend_node_budget(query_class, query, shape)
    lower, upper = context_node_bounds(query_class, shape)
    target_budget = nodes_for_token_target(target, shape)
    recommended = min(upper, max(lower, target_budget))

    # Broad evidence-gathering classes are recall-first: do not trim below the
    # existing measured default until a benchmark proves the smaller window.
    if query_class in {"blast_radius", "subsystem_summary"}:
        recommended = max(base, recommended)
    elif shape_candidate.recommended_budget is not None:
        recommended = min(recommended, shape_candidate.recommended_budget)

    if shape.nodes <= 1000 and query_class not in {"direct_lookup", "reverse_lookup"}:
        recommended = min(upper, max(recommended, base))

    estimated = estimate_gg_max_tokens(recommended, shape)
    saturation = estimated / max(1, target)
    page_budget = None
    mode = "single_window"
    reasons: list[str] = []
    if recommended > base:
        reasons.append("undersaturated small/sparse context expands toward token target")
    if recommended < base:
        reasons.append("large/dense/noisy context sparsifies under token target")
    if saturation > 1.10:
        page_budget = max(lower, nodes_for_token_target(target, shape))
        mode = "paged"
        reasons.append("estimated packet exceeds target; emit subsequent pages on demand")
    elif shape.nodes > recommended * 8:
        page_budget = recommended
        mode = "sparse_window"
        reasons.append("project is much larger than query window; keep sparse first page")
    if not reasons:
        reasons.append("current measured budget is near token target")

    return ContextWindowRecommendation(
        query_class=query_class,
        base_budget=base,
        recommended_budget=recommended,
        target_tokens=target,
        estimated_tokens=estimated,
        saturation=round(saturation, 4),
        page_node_budget=page_budget,
        mode=mode,
        reason="; ".join(reasons),
    )


def recommend_observed_context_window(
    query_class: str,
    query: str,
    shape: GraphShape,
    *,
    observed_budget: int,
    observed_nodes: int,
    observed_tokens: int,
    target_tokens: int | None = None,
) -> ContextWindowRecommendation:
    """Recommend a second-pass window from the actual rendered first page.

    The static graph-shape estimate answers "what might this project cost?".
    This observed variant answers "what did this anchored neighborhood cost?".
    It is still answer-key blind: it uses only first-pass packet size and graph
    shape, which are available at runtime after anchor selection.
    """
    base = default_node_budget(query_class, query)
    target = target_tokens or default_context_token_target(query_class, query)
    if is_doc_query(query_class, query) or query_class == "negative_query" or observed_tokens <= 0:
        return ContextWindowRecommendation(
            query_class=query_class,
            base_budget=base,
            recommended_budget=base,
            target_tokens=target,
            estimated_tokens=max(0, observed_tokens),
            saturation=round(observed_tokens / max(1, target), 4) if observed_tokens > 0 else 0.0,
            page_node_budget=None,
            mode="fixed",
            reason="doc/negative queries use fixed compact budgets",
        )

    lower, upper = context_node_bounds(query_class, shape)
    actual_nodes = max(1, observed_nodes)
    scale = target / max(1, observed_tokens)
    scaled_budget = int(round(actual_nodes * scale))
    recommended = min(upper, max(lower, scaled_budget))

    if query_class in {"blast_radius", "subsystem_summary"}:
        recommended = max(base, recommended)

    if observed_nodes < observed_budget:
        recommended = min(recommended, observed_nodes)

    mode = "single_window"
    page_budget = None
    reasons: list[str] = []
    if observed_tokens < target * 0.70 and observed_nodes >= observed_budget:
        reasons.append("first page underfilled target; expand from rendered-token calibration")
    if observed_tokens > target * 1.10:
        mode = "paged"
        page_budget = max(lower, min(observed_budget, recommended))
        reasons.append("first page exceeded target; use calibrated page size")
    elif shape.nodes > max(1, recommended) * 8:
        mode = "sparse_window"
        page_budget = recommended
        reasons.append("project is much larger than calibrated window; keep sparse first page")
    if not reasons:
        reasons.append("first page is near target")

    estimated = int(round(observed_tokens * (recommended / actual_nodes)))
    return ContextWindowRecommendation(
        query_class=query_class,
        base_budget=base,
        recommended_budget=recommended,
        target_tokens=target,
        estimated_tokens=estimated,
        saturation=round(estimated / max(1, target), 4),
        page_node_budget=page_budget,
        mode=mode,
        reason="; ".join(reasons),
    )


def default_context_token_target(query_class: str, query: str = "") -> int:
    if is_doc_query(query_class, query):
        return 220
    if query_class == "negative_query":
        return 64
    if query_class in {"direct_lookup", "reverse_lookup"}:
        return 600
    if query_class == "multi_hop_path":
        return 900
    return 1600


def context_node_bounds(query_class: str, shape: GraphShape) -> tuple[int, int]:
    if query_class in {"direct_lookup", "reverse_lookup"}:
        return 24, min(96, max(24, shape.nodes))
    if query_class == "multi_hop_path":
        return 32, min(140, max(32, shape.nodes))
    return 48, min(200, max(48, shape.nodes))


def nodes_for_token_target(target_tokens: int, shape: GraphShape) -> int:
    intercept = 11.74
    node_coef = 1.496
    edge_coef = 6.215
    density = adjusted_edge_density(shape)
    per_node = max(1.0, node_coef + edge_coef * density)
    return max(1, int((target_tokens - intercept) / per_node))


def estimate_gg_max_tokens(nodes: int, shape: GraphShape) -> int:
    density = adjusted_edge_density(shape)
    edges = int(math.ceil(nodes * density))
    return max(0, int(round(11.74 + 1.496 * nodes + 6.215 * edges)))


def adjusted_edge_density(shape: GraphShape) -> float:
    noise_factor = 1.0 + 0.30 * shape.weak_edge_ratio + 0.20 * shape.doc_node_ratio
    return max(0.05, shape.edge_density * noise_factor)
