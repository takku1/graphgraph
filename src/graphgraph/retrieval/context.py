from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

from ..concepts.doccode import doc_code_bias
from ..graph.core import Edge, Graph
from ..graph.ontology import provenance_confidence
from ..graph.traversal import relation_rank, traversal_policy
from ..planning import ContextPlan, compute_subgraph_stats, plan_context
from ..planning.budgets import doc_intensity_score, plan_terms
from ..planning.shape import profile_graph_shape, recommend_node_budget
from .budgeting import budget_edges, enrich_runtime_context
from .models import Match, RetrievalResult
from .search import search_nodes

_NOISE_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),                          # markdown code blocks
    re.compile(r"Sender\s*\(untrusted metadata\)\s*:\s*", re.IGNORECASE),  # untrusted sender prefix
    re.compile(r"\[[\w\s:\-]+UTC\]\s*", re.IGNORECASE),     # timestamp logs
]

def sanitize_query(query: str) -> str:
    """Strip upstream system noise and logs to preserve pure query search intent."""
    text = query or ""
    for pat in _NOISE_PATTERNS:
        text = pat.sub("", text)
    return text.strip()

STRUCTURAL_QUERY_CLASSES = {"blast_radius", "multi_hop_path", "reverse_lookup"}
NON_STRUCTURAL_KINDS = {"concept", "section", "markdown", "rst", "html", "text"}
STRUCTURAL_RELATIONS = {
    "calls", "imports", "imports_from", "reads", "writes", "uses", "implements",
    "tests", "configures", "returns", "defines", "data_flow", "control_flow",
    "formalizes", "implements_algorithm",
}


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
        decay_hubs=(plan.query_class in {"blast_radius", "subsystem_summary"}),
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

        # Cohesion-guided budget trim:
        # If the subgraph has high cohesion (tightly coupled module), we can reduce budget to save tokens.
        unique_undirected_edges = {(min(e.source, e.target), max(e.source, e.target)) for e in edges if e.source in nodes and e.target in nodes}
        n = len(nodes)
        possible_edges = n * (n - 1) // 2 if n > 1 else 0
        cohesion = len(unique_undirected_edges) / possible_edges if possible_edges > 0 else 0.0
        if cohesion > 0.40:
            cohesion_scale = max(0.6, min(1.0, 1.0 - (cohesion - 0.4) * 0.67))
            effective_node_budget = max(20, int((effective_node_budget or plan.node_budget) * cohesion_scale))

    stats = compute_subgraph_stats(graph, nodes, edges)
    weak_limit = adaptive_weak_edge_limit(plan.weak_edge_limit, stats.weak_edge_ratio, stats.relation_entropy, stats.edges)
    edges = budget_edges(edges, max_nodes=effective_node_budget, weak_limit=weak_limit)
    nodes, edges = reserve_start_evidence(graph, nodes, edges, tuple(starts), plan, effective_node_budget)
    nodes, edges = prune_doc_concept_noise(graph, nodes, edges, tuple(starts), plan, effective_node_budget)
    
    # Dynamic Programming Connected Tree Knapsack Context Partitioning
    if effective_node_budget is not None and len(nodes) > effective_node_budget:
        # Fast local BFS to propagate relevance scores from starts to candidates in O(nodes) time
        import collections

        from .tree_knapsack import tree_knapsack_context_partition
        node_values = {s: 1.0 for s in starts}
        outgoing = graph.outgoing()
        incoming = graph.incoming()
        queue = collections.deque(starts)
        visited = set(starts)
        while queue:
            curr = queue.popleft()
            val = node_values.get(curr, 1.0)
            neighbors = [e.target for e in outgoing.get(curr, [])] + [e.source for e in incoming.get(curr, [])]
            for n in neighbors:
                if n in nodes and n not in visited:
                    visited.add(n)
                    node_values[n] = val * 0.85
                    queue.append(n)
                    
        token_budget = effective_node_budget * 80
        dp_nodes = tree_knapsack_context_partition(graph, tuple(starts), nodes, node_values, token_budget)
        if dp_nodes:
            nodes = dp_nodes
            edges = [e for e in edges if e.source in nodes and e.target in nodes]

    edges = shape_edge_budget(edges, tuple(starts), plan, node_count=len(nodes))
    return enrich_runtime_context(graph, nodes, edges, max_nodes=effective_node_budget)


def adaptive_weak_edge_limit(base_limit: int, weak_edge_ratio: float, relation_entropy: float, edge_count: int) -> int:
    if edge_count < base_limit * 2 or weak_edge_ratio < 0.75:
        return base_limit
    if relation_entropy <= 0.2:
        return max(3, base_limit // 2)
    return max(4, int(base_limit * 0.75))


def shape_edge_budget(edges: list[Edge], starts: tuple[str, ...], plan: ContextPlan, node_count: int) -> list[Edge]:
    """Sparsify dense rendered edge fans from observed subgraph shape.

    The node set is the recall surface; very dense packets usually become noisy
    because repetitive relations such as imports/explains dominate the edge
    section. This keeps start-adjacent evidence, preserves every present
    relation with a sqrt-sized floor, then fills the remaining edge budget by
    traversal priority.
    """
    if plan.query_class not in {"blast_radius", "subsystem_summary"}:
        return edges
    if node_count <= 0 or not edges:
        return edges

    density = len(edges) / max(1, node_count)
    if density <= 2.0:
        return edges

    target_density = 1.0 + (1.0 / math.sqrt(density))
    target_edges = max(node_count, int(round(node_count * target_density)))
    if target_edges >= len(edges):
        return edges

    start_set = set(starts)
    relation_counts: dict[str, int] = {}
    for edge in edges:
        relation_counts[edge.type] = relation_counts.get(edge.type, 0) + 1

    relation_floors = {
        relation: max(1, int(math.sqrt(count)))
        for relation, count in relation_counts.items()
    }
    relation_kept = {relation: 0 for relation in relation_counts}
    kept: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(edge: Edge) -> None:
        key = (edge.source, edge.target, edge.type)
        if key in seen:
            return
        kept.append(edge)
        seen.add(key)
        relation_kept[edge.type] = relation_kept.get(edge.type, 0) + 1

    ranked = sorted(edges, key=lambda edge: _edge_shape_rank(edge, start_set, plan))

    for edge in ranked:
        if edge.source in start_set or edge.target in start_set:
            add(edge)
            if len(kept) >= target_edges:
                return kept

    for edge in ranked:
        if relation_kept.get(edge.type, 0) < relation_floors.get(edge.type, 0):
            add(edge)
            if len(kept) >= target_edges:
                return kept

    for edge in ranked:
        add(edge)
        if len(kept) >= target_edges:
            break
    return kept


def _edge_shape_rank(edge: Edge, starts: set[str], plan: ContextPlan) -> tuple[int, int, int, str, str, str]:
    start_priority = 0 if edge.source in starts or edge.target in starts else 1
    relation = relation_rank(edge.type, traversal_policy(plan.query_class))
    return (start_priority, *relation, edge.source, edge.target, edge.type)


def reserve_start_evidence(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    plan: ContextPlan,
    max_nodes: int | None,
    reserve_limit: int = 16,
) -> tuple[set[str], list[Edge]]:
    """Keep first-order structural evidence for selected anchors.

    Dense blast-radius neighborhoods can fill the node budget with high-degree
    callers before keeping a selected file's children, a symbol's parent file,
    or an immediate callee. Those neighbors are load-bearing context for the
    selected anchor, so reserve a small deterministic slice for them.
    """
    if plan.query_class != "blast_radius" or plan.hops <= 0:
        return nodes, edges

    start_set = set(starts)
    candidates: list[tuple[tuple[int, int, str], str, Edge]] = []
    for edge in graph.edges:
        if not edge.active:
            continue
        neighbor: str | None = None
        if edge.type == "contains" and edge.source in start_set:
            neighbor = edge.target
        elif edge.type == "contains" and edge.target in start_set:
            neighbor = edge.source
        elif edge.type in STRUCTURAL_RELATIONS and edge.source in start_set:
            neighbor = edge.target
        if not neighbor or neighbor not in graph.nodes or not graph.nodes[neighbor].active:
            continue
        candidates.append((relation_rank(edge.type, traversal_policy(plan.query_class)), neighbor, edge))

    test_support_nodes = reserve_test_support_files(graph, starts)

    if not candidates and not test_support_nodes:
        return nodes, edges

    out_nodes = set(nodes)
    ranked_candidates = sorted(
        candidates,
        key=lambda item: (
            _start_evidence_priority(item[2], start_set),
            *item[0],
            item[1],
            item[2].source,
            item[2].target,
            item[2].type,
        ),
    )
    protected = start_set | set(test_support_nodes) | {neighbor for _rank, neighbor, _edge in ranked_candidates[:reserve_limit]}
    for _rank, neighbor, _edge in ranked_candidates[:reserve_limit]:
        if neighbor in out_nodes:
            continue
        if max_nodes is not None and len(out_nodes) >= max_nodes:
            removable = _least_valuable_context_node(graph, out_nodes, protected=protected)
            if removable is None:
                break
            out_nodes.remove(removable)
        out_nodes.add(neighbor)
    for node_id in test_support_nodes:
        if node_id in out_nodes:
            continue
        if max_nodes is not None and len(out_nodes) >= max_nodes:
            removable = _least_valuable_context_node(graph, out_nodes, protected=protected)
            if removable is None:
                break
            out_nodes.remove(removable)
        out_nodes.add(node_id)

    seen = {(edge.source, edge.target, edge.type) for edge in edges}
    out_edges = [edge for edge in edges if edge.source in out_nodes and edge.target in out_nodes]
    for _rank, _neighbor, edge in ranked_candidates[:reserve_limit]:
        key = (edge.source, edge.target, edge.type)
        if key not in seen and edge.source in out_nodes and edge.target in out_nodes:
            out_edges.append(edge)
            seen.add(key)
    return out_nodes, out_edges


def _start_evidence_priority(edge: Edge, starts: set[str]) -> int:
    if edge.type == "contains" and edge.target in starts:
        return 0
    if edge.type != "contains" and edge.source in starts:
        return 1
    if edge.type == "contains" and edge.source in starts:
        return 2
    return 3


def reserve_test_support_files(graph: Graph, starts: tuple[str, ...], limit: int = 4) -> tuple[str, ...]:
    support_names = {"__init__.py", "compat.py", "conftest.py"}
    start_dirs = {
        node.path.replace("\\", "/").rsplit("/", 1)[0]
        for start in starts
        if (node := graph.nodes.get(start)) is not None
        and node.path
        and (node.path.replace("\\", "/").startswith("tests/") or "/tests/" in node.path.replace("\\", "/"))
    }
    if not start_dirs:
        return ()
    out: list[str] = []
    for node_id, node in sorted(graph.nodes.items()):
        if not node.active or not node.path:
            continue
        path = node.path.replace("\\", "/")
        if path.rsplit("/", 1)[0] in start_dirs and path.rsplit("/", 1)[-1] in support_names:
            out.append(node_id)
            if len(out) >= limit:
                break
    return tuple(out)


def prune_doc_concept_noise(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    plan: ContextPlan,
    max_nodes: int | None,
) -> tuple[set[str], list[Edge]]:
    """Trim doc/concept spillover for broad non-document summaries.

    The scanner should retain documentation and concepts because doc queries need
    them. Broad status/subsystem packets are different: pathless concepts and
    weak doc relation fans can crowd out implementation evidence.
    """
    if plan.query_class != "subsystem_summary":
        return nodes, edges
    if plan.packet == "doc_summary":
        return nodes, edges

    start_set = set(starts)
    structural: set[str] = set()
    doc_like: list[tuple[float, str]] = []
    concepts: list[tuple[float, str]] = []
    node_edge_scores = _node_edge_scores(edges)

    budget = max_nodes or plan.node_budget or len(nodes)
    doc_limit = max(6, min(18, budget // 5))
    concept_limit = max(1, min(4, budget // 30))

    for node_id in nodes:
        node = graph.nodes.get(node_id)
        if not node:
            continue
        if node_id in start_set:
            structural.add(node_id)
            continue
        if node.kind == "concept":
            concepts.append((_context_node_score(node_id, node_edge_scores, node.path), node_id))
            continue
        if node.kind in NON_STRUCTURAL_KINDS:
            doc_like.append((_context_node_score(node_id, node_edge_scores, node.path), node_id))
            continue
        structural.add(node_id)

    keep = set(structural)
    keep.update(node_id for _score, node_id in sorted(doc_like, reverse=True)[:doc_limit])
    keep.update(node_id for _score, node_id in sorted(concepts, reverse=True)[:concept_limit])
    keep = reserve_structural_neighbors(graph, keep, structural, max_nodes or plan.node_budget, protected=start_set)
    pruned_edges = [edge for edge in edges if edge.source in keep and edge.target in keep]
    pruned_edges = include_reserved_structural_edges(graph, keep, pruned_edges)
    return keep, pruned_edges


def reserve_structural_neighbors(
    graph: Graph,
    keep: set[str],
    structural: set[str],
    max_nodes: int | None,
    reserve_limit: int = 12,
    protected: set[str] | None = None,
) -> set[str]:
    if not structural:
        return keep

    reserved: list[str] = []
    seen = set(keep)
    for edge in sorted(graph.edges, key=lambda e: (e.source, e.target, e.type)):
        if edge.type not in STRUCTURAL_RELATIONS or not edge.active:
            continue
        if edge.source in structural and _is_structural_node(graph, edge.target) and edge.target not in seen:
            reserved.append(edge.target)
            seen.add(edge.target)
        elif edge.target in structural and _is_structural_node(graph, edge.source) and edge.source not in seen:
            reserved.append(edge.source)
            seen.add(edge.source)
        if len(reserved) >= reserve_limit:
            break

    if not reserved:
        return keep

    out = set(keep)
    protected_nodes = protected or set()
    for node_id in reserved:
        if max_nodes is not None and len(out) >= max_nodes:
            removable = _least_valuable_doc_node(graph, out, protected=protected_nodes)
            if removable is None:
                break
            out.remove(removable)
        out.add(node_id)
    return out


def include_reserved_structural_edges(graph: Graph, keep: set[str], edges: list[Edge]) -> list[Edge]:
    seen = {(edge.source, edge.target, edge.type) for edge in edges}
    out = list(edges)
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.type)
        if key in seen or edge.type not in STRUCTURAL_RELATIONS:
            continue
        if edge.source in keep and edge.target in keep:
            out.append(edge)
            seen.add(key)
    return out


def _is_structural_node(graph: Graph, node_id: str) -> bool:
    node = graph.nodes.get(node_id)
    return bool(node and node.active and node.kind not in NON_STRUCTURAL_KINDS)


def _least_valuable_doc_node(graph: Graph, nodes: set[str], *, protected: set[str] | None = None) -> str | None:
    protected_nodes = protected or set()
    for node_id in sorted(nodes):
        if node_id in protected_nodes:
            continue
        node = graph.nodes.get(node_id)
        if node and node.kind == "concept":
            return node_id
    for node_id in sorted(nodes):
        if node_id in protected_nodes:
            continue
        node = graph.nodes.get(node_id)
        if node and node.kind in NON_STRUCTURAL_KINDS:
            return node_id
    return None


def _least_valuable_context_node(graph: Graph, nodes: set[str], *, protected: set[str] | None = None) -> str | None:
    protected_nodes = protected or set()
    for kind_group in (
        {"concept"},
        NON_STRUCTURAL_KINDS,
        {"field"},
        {"function", "method"},
    ):
        for node_id in sorted(nodes):
            if node_id in protected_nodes:
                continue
            node = graph.nodes.get(node_id)
            if node and node.kind in kind_group:
                return node_id
    for node_id in sorted(nodes):
        if node_id not in protected_nodes:
            return node_id
    return None


def _node_edge_scores(edges: list[Edge]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for edge in edges:
        relation_bonus = {
            "explains": 3.0,
            "contains": 2.5,
            "section_of": 1.5,
            "mentions": 0.5,
            "discusses": 0.5,
        }.get(edge.type, 1.0)
        score = relation_bonus * edge.confidence * provenance_confidence(edge.provenance)
        scores[edge.source] = max(scores.get(edge.source, 0.0), score)
        scores[edge.target] = max(scores.get(edge.target, 0.0), score)
    return scores


def _context_node_score(node_id: str, edge_scores: dict[str, float], path: str) -> float:
    score = edge_scores.get(node_id, 0.0)
    if path:
        score += 2.0
    return score


def retrieve_context(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
) -> RetrievalResult:
    query = sanitize_query(query)
    doc_intensity = doc_intensity_score(query_class, query)
    graph_bias = doc_code_bias(graph)
    doc_intensity *= 0.75 + graph_bias * 0.5
    plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops)
    if max_nodes is None:
        plan = apply_shape_budget(graph, plan, query)
    candidate_limit = max(plan.anchor_limit, plan.anchor_limit * 3 if query_class in STRUCTURAL_QUERY_CLASSES else plan.anchor_limit)
    if query_class == "direct_lookup" and len(plan_terms(query)) == 1:
        candidate_limit = max(candidate_limit, 24)
    matches = search_nodes(
        graph,
        query,
        limit=max(candidate_limit, 1),
        doc_intensity=doc_intensity,
        personalize=True,
        scopes=scopes,
    )
    effective_anchor_limit = (
        _adaptive_anchor_limit(matches, plan, query)
        if query_class in STRUCTURAL_QUERY_CLASSES or query_class == "direct_lookup"
        else plan.anchor_limit
    )
    selected_matches = select_anchor_matches(matches, effective_anchor_limit, query_class, doc_intensity >= 0.35)
    starts_list = list(match.node.id for match in selected_matches)

    # Discover git-modified files (active session context / Ephemeral Session Layer).
    # Skipped for recent_changes: that query class already targets committed
    # git-history evidence for one deliberately chosen anchor. Unconditionally
    # injecting every currently-dirty file here defeats its purpose -- on a
    # repo under active development (precisely when "what recently changed
    # here" is most useful), a dozen unrelated dirty files drown out the one
    # real anchor before the node budget is ever reached. Confirmed live: on
    # this repo's own history with 15 dirty files, the intended fixes/commit
    # evidence for a scoped anchor was silently dropped without this guard.
    if query_class != "recent_changes":
        from .git_utils import get_git_modified_files, resolve_modified_node_ids
        modified_paths = get_git_modified_files()
        resolved = resolve_modified_node_ids(graph, modified_paths)
        for path in modified_paths:
            for node_id in resolved.get(path, []):
                if node_id not in starts_list:
                    starts_list.append(node_id)

    starts = tuple(starts_list[:12])
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
        nodes, edges = reserve_query_named_siblings(graph, nodes, edges, starts, query, plan)
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
    """Pick anchor fanout from the continuous score shape, not threshold ladders."""
    if not matches:
        return plan.anchor_limit

    top = matches[0]
    query_terms = plan_terms(query)
    term_count = len(query_terms)
    limit = plan.anchor_limit

    if top.node.kind in {"concept", "section"}:
        return min(limit, 2)

    if term_count == 1:
        if plan.query_class == "direct_lookup":
            plateau_count = sum(
                1
                for match in matches[:24]
                if top.score > 0
                and match.score / top.score >= 0.45
                and match.node.kind in {"function", "method", "class", "struct", "field", "python", "rust", "go", "java", "typescript", "javascript"}
            )
            if plateau_count >= 4:
                return min(16, max(plan.anchor_limit, plateau_count))
            return plan.anchor_limit

        if top.node.kind in {"function", "method"}:
            shape = _anchor_score_shape(matches, window=min(8, max(3, limit)))
            if shape.same_stem_mass >= 0.72:
                return min(limit, max(2, round(1 + 3 * shape.same_stem_mass)))
            ambiguity = 0.20 * shape.entropy + 0.42 * shape.path_diversity + 0.10 * shape.plateau_mass
            confidence = 0.30 * shape.top_mass + 0.35 * shape.score_gap
            shaped = 1 + round((limit - 1) * max(0.0, ambiguity - confidence))
            if any(_is_file_like_anchor(match.node) for match in matches[:6]):
                shaped = max(shaped, min(limit, 5))
            if plan.query_class == "blast_radius":
                shaped = max(shaped, 2)
            return max(1, min(limit, shaped))

        if top.node.kind == "python":
            shape = _anchor_score_shape(matches, window=min(5, limit))
            return min(limit, 1 + round(1.5 * shape.entropy))

        if top.node.kind in {"class", "markdown", "java", "header", "source"}:
            return min(limit, 1)

    if term_count >= 2:
        if top.node.kind == "python":
            shape = _anchor_score_shape(matches, window=min(5, limit))
            return min(limit, 1 + round(1.5 * shape.entropy))
        if top.node.kind in {"markdown"}:
            return min(limit, 1)
        if top.node.kind in {"class", "java", "typescript", "javascript", "source", "header"}:
            if _is_high_confidence_exact_anchor(top):
                return min(limit, 1)
            shape = _anchor_score_shape(matches, window=min(8, limit))
            shaped = 1 + round(limit * (0.55 * shape.entropy + 0.45 * shape.plateau_mass))
            return max(2, min(limit, shaped))

    shape = _anchor_score_shape(matches, window=min(8, limit))
    shaped = 1 + round(limit * (0.55 * shape.entropy + 0.45 * shape.plateau_mass))
    return max(1, min(limit, shaped))


@dataclass(frozen=True)
class AnchorScoreShape:
    top_mass: float
    score_gap: float
    entropy: float
    plateau_mass: float
    path_diversity: float
    same_stem_mass: float


def _anchor_score_shape(matches: tuple[Match, ...], *, window: int) -> AnchorScoreShape:
    sample = tuple(match for match in matches[:max(1, window)] if match.score > 0)
    if not sample:
        return AnchorScoreShape(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    scores = [match.score for match in sample]
    total = sum(scores) or 1.0
    probs = [score / total for score in scores]
    entropy = -sum(p * math.log(p) for p in probs if p > 0) / math.log(len(probs)) if len(probs) > 1 else 0.0
    top = scores[0]
    second = scores[1] if len(scores) > 1 else 0.0
    score_gap = max(0.0, min(1.0, (top - second) / max(top, 1e-9)))
    plateau_mass = sum(score for score in scores if score / max(top, 1e-9) >= 0.75) / total
    stems = [_node_stem(match.node.path) for match in sample]
    path_diversity = len(set(stems)) / max(1, len(stems))
    top_stem = stems[0]
    same_stem_mass = sum(score for score, stem in zip(scores, stems) if stem == top_stem) / total
    return AnchorScoreShape(
        top_mass=probs[0],
        score_gap=score_gap,
        entropy=max(0.0, min(1.0, entropy)),
        plateau_mass=max(0.0, min(1.0, plateau_mass)),
        path_diversity=max(0.0, min(1.0, path_diversity)),
        same_stem_mass=max(0.0, min(1.0, same_stem_mass)),
    )


def _node_stem(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _is_file_like_anchor(node: object) -> bool:
    return getattr(node, "kind", "") in {
        "file",
        "python",
        "typescript",
        "javascript",
        "rust",
        "go",
        "java",
        "c",
        "cpp",
        "header",
        "markdown",
        "rst",
        "html",
        "text",
    }


def _is_high_confidence_exact_anchor(match: Match) -> bool:
    return any(
        reason in {"label_exact_terms", "label_all_terms", "basename_exact_terms", "basename_all_terms"}
        for reason in match.reasons
    )


def select_anchor_matches(
    matches: tuple[Match, ...],
    anchor_limit: int,
    query_class: str,
    doc_intent: bool = False,
) -> tuple[Match, ...]:
    if doc_intent:
        doc_matches = [match for match in matches if match.node.kind in NON_STRUCTURAL_KINDS]
        if doc_matches:
            selected: list[Match] = []
            seen: set[str] = set()
            for match in doc_matches + list(matches):
                if match.node.id in seen:
                    continue
                selected.append(match)
                seen.add(match.node.id)
                if len(selected) >= anchor_limit:
                    return tuple(selected)
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


def reserve_query_named_siblings(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    query: str,
    plan: ContextPlan,
    reserve_limit: int = 12,
) -> tuple[set[str], list[Edge]]:
    if plan.query_class not in {"blast_radius", "subsystem_summary"}:
        return nodes, edges
    query_terms = set(plan_terms(query))
    if not query_terms:
        return nodes, edges

    start_set = set(starts)
    start_paths = {
        node.path.replace("\\", "/")
        for start in starts
        if (node := graph.nodes.get(start)) is not None and node.path
    }
    if not start_paths:
        return nodes, edges

    start_terms: set[str] = set()
    for start in starts:
        node = graph.nodes.get(start)
        if node:
            start_terms.update(plan_terms(node.label))

    candidates: list[tuple[tuple[int, str, str], str]] = []
    for node_id, node in graph.nodes.items():
        if node_id in nodes or not node.active or not node.path:
            continue
        if node.path.replace("\\", "/") not in start_paths:
            continue
        if node.kind in NON_STRUCTURAL_KINDS or node.kind == "field":
            continue
        label_terms = set(plan_terms(node.label))
        query_hits = _loose_term_hits(query_terms, label_terms)
        sibling_hits = _loose_term_hits(start_terms, label_terms)
        if query_hits == 0 and sibling_hits == 0:
            continue
        priority = (
            0 if query_hits else 1,
            -(query_hits * 10 + sibling_hits),
            node.path,
            node.label,
        )
        candidates.append((priority, node_id))

    if not candidates:
        return nodes, edges

    out_nodes = set(nodes)
    protected = start_set | {node_id for _priority, node_id in sorted(candidates)[:reserve_limit]}
    max_nodes = plan.node_budget
    for _priority, node_id in sorted(candidates)[:reserve_limit]:
        if node_id in out_nodes:
            continue
        if max_nodes is not None and len(out_nodes) >= max_nodes:
            removable = _least_valuable_context_node(graph, out_nodes, protected=protected)
            if removable is None:
                break
            out_nodes.remove(removable)
        out_nodes.add(node_id)

    seen = {(edge.source, edge.target, edge.type) for edge in edges}
    out_edges = [edge for edge in edges if edge.source in out_nodes and edge.target in out_nodes]
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.type)
        if key in seen or not edge.active:
            continue
        if edge.source in out_nodes and edge.target in out_nodes and (
            edge.source in protected or edge.target in protected or edge.type in {"contains", "implements"}
        ):
            out_edges.append(edge)
            seen.add(key)
    return out_nodes, out_edges


def _loose_term_hits(needles: set[str], haystack: set[str]) -> int:
    hits = 0
    for needle in needles:
        for term in haystack:
            if needle == term:
                hits += 1
                break
            if len(needle) >= 8 and len(term) >= 8 and needle[:8] == term[:8]:
                hits += 1
                break
    return hits
