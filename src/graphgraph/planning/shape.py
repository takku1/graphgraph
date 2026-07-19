from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from ..graph.core import Graph
from ..graph.ontology import is_weak_relation
from .budgets import default_node_budget, is_doc_query
from .token_cost import estimate_surface_tokens, nodes_for_surface_budget, packet_marginal_costs

LOCAL_EDGE_DENSITY_CAP = 1.5

SOURCE_KINDS = {"python", "typescript", "javascript", "rust", "go", "java", "c", "cpp", "header", "lean"}
SYMBOL_KINDS = {"function", "method", "class", "struct", "enum", "trait", "theorem"}
DOC_KINDS = {"markdown", "rst", "text", "section", "paragraph", "concept"}

# Query-complexity prior (lambda) per class: higher means the target evidence is
# concentrated, lower means it is distributed. Drives the regularized budget.
QUERY_COMPLEXITY_LAMBDA = {
    "direct_lookup": 0.08,
    "reverse_lookup": 0.08,
    "multi_hop_path": 0.05,
    "blast_radius": 0.035,
    "subsystem_summary": 0.035,
    "spreading_activation": 0.035,
}
DEFAULT_COMPLEXITY_LAMBDA = 0.04

# Shape-driven multipliers applied to the complexity prior.
DOC_HEAVY_NODE_RATIO = 0.65
DOC_HEAVY_LAMBDA_GAIN = 1.2
SMALL_GRAPH_NODES = 500
SMALL_GRAPH_LAMBDA_GAIN = 1.25
LARGE_GRAPH_NODES = 5000
LARGE_GRAPH_LAMBDA_GAIN = 1.15
DENSE_GRAPH_EDGE_DENSITY = 2.5
WEAK_EDGE_HEAVY_RATIO = 0.45
UNDEREXTRACTED_IMPORTS_PER_FILE = 0.05
UNDEREXTRACTED_MIN_SOURCE_FILES = 20

# Regularized budget U(n) = (1 - e^{-lambda*n}) - c*(tau*n); n* is its closed-form
# optimum. c is the empirically tuned token penalty; the ratio floor keeps ln>0.
TOKEN_PENALTY_COST = 1e-4
MIN_BUDGET_RATIO = 1.1

# Effective edge density inflates raw density by structural noise, then caps it.
WEAK_EDGE_NOISE = 0.30
DOC_NODE_NOISE = 0.20

# Token-window target by query class (fallback DEFAULT for unlisted classes).
DOC_TOKEN_TARGET = 220
DEFAULT_TOKEN_TARGET = 1600
_CONTEXT_TOKEN_TARGET = {
    "negative_query": 64,
    "direct_lookup": 600,
    "reverse_lookup": 600,
    "multi_hop_path": 900,
}

# Node-count bounds by query class: (floor, hard_ceiling); ceiling is further
# clamped to the graph size at call time.
DEFAULT_NODE_BOUNDS = (48, 200)
_NODE_BOUNDS = {
    "direct_lookup": (24, 96),
    "reverse_lookup": (24, 96),
    "multi_hop_path": (32, 140),
}
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
    weak_edges = sum(count for relation, count in relations.items() if is_weak_relation(relation))
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

    # 1. Complexity prior for the query class.
    lambda_ = QUERY_COMPLEXITY_LAMBDA.get(query_class, DEFAULT_COMPLEXITY_LAMBDA)

    # 2. Adjust the prior for graph shape.
    if shape.doc_node_ratio >= DOC_HEAVY_NODE_RATIO:
        lambda_ *= DOC_HEAVY_LAMBDA_GAIN
        if query_class in {"multi_hop_path", "reverse_lookup"}:
            reasons.append("doc-heavy graph trims structural noise")
        else:
            reasons.append("doc-heavy graph keeps recall-first broad expansion")

    if shape.nodes <= SMALL_GRAPH_NODES:
        lambda_ *= SMALL_GRAPH_LAMBDA_GAIN
        if query_class in {"direct_lookup", "reverse_lookup"}:
            reasons.append("small graph direct/reverse lookup")
    elif shape.nodes >= LARGE_GRAPH_NODES:
        lambda_ *= LARGE_GRAPH_LAMBDA_GAIN
        if query_class in {"direct_lookup", "reverse_lookup"}:
            reasons.append("large graph narrows direct/reverse lookup")
        elif query_class in {"blast_radius", "subsystem_summary"} and shape.edge_density >= DENSE_GRAPH_EDGE_DENSITY:
            reasons.append("large dense graph keeps recall-first broad expansion")

    if shape.weak_edge_ratio >= WEAK_EDGE_HEAVY_RATIO and query_class in {"blast_radius", "subsystem_summary"}:
        reasons.append("weak-edge-heavy graph keeps recall-first broad expansion")

    if (
        shape.imports_per_source_file < UNDEREXTRACTED_IMPORTS_PER_FILE
        and shape.source_files >= UNDEREXTRACTED_MIN_SOURCE_FILES
    ):
        reasons.append("warning: import topology looks under-extracted")

    # 3. Marginal token cost per node (tau) from the fitted regression surface.
    density = adjusted_edge_density(shape)
    node_cost, edge_cost = packet_marginal_costs("gg")
    tau = node_cost + edge_cost * density

    # 4. Closed-form optimum of the regularized budget:
    #    U(n) = (1 - e^{-lambda*n}) - c*(tau*n)  =>  n* = (1/lambda) * ln(lambda / (c*tau)).
    ratio = max(MIN_BUDGET_RATIO, lambda_ / (TOKEN_PENALTY_COST * tau))
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
        return DOC_TOKEN_TARGET
    return _CONTEXT_TOKEN_TARGET.get(query_class, DEFAULT_TOKEN_TARGET)


def context_node_bounds(query_class: str, shape: GraphShape) -> tuple[int, int]:
    floor, ceiling = _NODE_BOUNDS.get(query_class, DEFAULT_NODE_BOUNDS)
    return floor, min(ceiling, max(floor, shape.nodes))


def nodes_for_token_target(target_tokens: int, shape: GraphShape) -> int:
    return nodes_for_surface_budget("gg", target_tokens, adjusted_edge_density(shape))


def estimate_gg_max_tokens(nodes: int, shape: GraphShape) -> int:
    density = adjusted_edge_density(shape)
    edges = int(math.ceil(nodes * density))
    return estimate_surface_tokens("gg", nodes, edges)


def adjusted_edge_density(shape: GraphShape) -> float:
    noise_factor = 1.0 + WEAK_EDGE_NOISE * shape.weak_edge_ratio + DOC_NODE_NOISE * shape.doc_node_ratio
    raw_density = shape.edge_density * noise_factor
    return max(0.05, min(LOCAL_EDGE_DENSITY_CAP, raw_density))


def recommend_facts_per_node(node_count: int, max_facts: int = 5) -> int:
    """How many facts to render per node, scaled to how many nodes are selected.

    Every hybrid packet renderer previously hardcoded `node.facts[:2]` or
    `node.facts[:3]` -- a fixed constant regardless of whether the packet
    carries 5 nodes or 500. That meant a small project didn't actually get
    *more detail per thing*, it just had less competition for the same fixed
    per-node allowance; a large project wasn't deliberately made sparser,
    the fixed allowance just added up faster. This makes the density an
    explicit function of selection size: a handful of selected nodes can
    each afford close to `max_facts`; a large selection tapers toward 1.

    The curve (`max_facts / sqrt(node_count)`) and `max_facts` default are a
    reasonable starting point, not a calibrated constant -- unlike
    `estimate_gg_max_tokens` (node/edge-count token cost), there is currently
    no benchmarked per-fact token cost term to fit this against. Treat this
    as provisional; revisit once fact-inclusion has its own benchmark
    signal, per this project's own promotion-evidence bar.
    """
    if node_count <= 0:
        return max_facts
    scaled = max_facts / math.sqrt(node_count)
    return max(1, min(max_facts, round(scaled)))
