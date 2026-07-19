from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from ..concepts.doccode import doc_code_bias, is_code_like
from ..concepts.terms import term_key
from ..graph.core import Edge, Graph
from ..graph.ontology import provenance_confidence, relation_spec
from ..graph.traversal import (
    BLAST_IMPACT_RELATIONS,
    BLAST_IMPACT_SHARE,
    BLAST_OUTGOING_RELATIONS,
    BLAST_SUPPORT_RELATIONS,
    BLAST_SUPPORT_SHARE,
    relation_rank,
    traversal_policy,
)
from ..planning import ContextPlan, compute_subgraph_stats, plan_context
from ..planning.budgets import doc_intensity_score, explicit_query_identifiers, plan_terms
from ..planning.shape import LOCAL_EDGE_DENSITY_CAP, profile_graph_shape, recommend_node_budget
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


_AFFECTED_ANCHOR_INTENT = re.compile(
    r"\b(?:if|affected|affecting|impact|impacted|changes?|changed|changing|"
    r"which|what|tests?|test|should|run|cover|covers|exercise|validate|validates|directly)\b",
    re.I,
)


def structural_anchor_query(query: str, query_class: str) -> str:
    """Remove planner vocabulary that can collide with unrelated symbols."""
    if query_class != "affected_tests":
        return query
    cleaned = _AFFECTED_ANCHOR_INTENT.sub(" ", query)
    return " ".join(cleaned.split()) or query


STRUCTURAL_QUERY_CLASSES = {"blast_radius", "multi_hop_path", "reverse_lookup", "affected_tests"}
SESSION_CONTEXT_QUERY_CLASSES = {"subsystem_summary", "spreading_activation"}
NON_STRUCTURAL_KINDS = {"concept", "section", "paragraph", "markdown", "rst", "html", "text"}
STRUCTURAL_RELATIONS = {
    "calls", "imports", "imports_from", "reads", "writes", "uses", "implements",
    "tests", "configures", "returns", "defines", "data_flow", "control_flow",
    "formalizes", "implements_algorithm",
}
_ORDERED_DOC_QUERY = re.compile(
    r"\b(before|after|next|previous|prior|ordered|phase|phases|stage|stages|"
    r"step|steps|sequence|roadmap|backlog|milestone)\b",
    re.I,
)
_ENUMERATED_DOC_QUERY = re.compile(r"\b(stage|stages|phase|phases|step|steps|sequence)\b", re.I)
_FLOW_ORIENTATION_QUERY = re.compile(
    r"\b(flow|flows|path|pipeline|call chain|data flow|control flow)\b",
    re.I,
)


def _reverse_lookup_relations(query: str) -> set[str]:
    terms = set(plan_terms(query))
    if terms & {"call", "calls", "caller", "callers", "called"}:
        return {"calls"}
    if terms & {"test", "tests", "tested", "cover", "covers"}:
        return {"calls", "references", "tests"}
    return set(traversal_policy("reverse_lookup").preferred_relations)


def reserve_reverse_direct_neighbors(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    query: str,
    plan: ContextPlan,
    scopes: tuple[str, ...] = (),
) -> tuple[set[str], list[Edge]]:
    """Spend a reverse-lookup budget on direct answers before siblings."""
    relations = _reverse_lookup_relations(query)
    start_set = set(starts)
    candidates = sorted(
        (
            edge
            for edge in graph.edges
            if edge.active
            and edge.target in start_set
            and edge.type in relations
            and edge.confidence * provenance_confidence(edge.provenance) >= plan.min_confidence
            and (
                not scopes
                or (
                    edge.source in graph.nodes
                    and _path_in_scopes(graph.nodes[edge.source].path, scopes)
                )
            )
        ),
        key=lambda edge: (
            *relation_rank(edge.type, traversal_policy("reverse_lookup")),
            -edge.confidence,
            edge.source,
            edge.target,
        ),
    )
    out_nodes = set(nodes)
    direct_nodes = {
        edge.source
        for edge in candidates
        if edge.source in out_nodes
    }
    max_nodes = plan.node_budget
    for edge in candidates:
        if edge.source in out_nodes:
            continue
        if max_nodes is not None and len(out_nodes) >= max_nodes:
            removable = _least_valuable_context_node(
                graph,
                out_nodes,
                protected=start_set | direct_nodes | {edge.source},
            )
            if removable is None:
                break
            out_nodes.remove(removable)
        out_nodes.add(edge.source)
        direct_nodes.add(edge.source)
    out_edges = [
        edge
        for edge in edges
        if edge.source in out_nodes and edge.target in out_nodes
    ]
    seen = {(edge.source, edge.target, edge.type) for edge in out_edges}
    for edge in candidates:
        key = (edge.source, edge.target, edge.type)
        if edge.source in out_nodes and edge.target in out_nodes and key not in seen:
            out_edges.append(edge)
            seen.add(key)
    return out_nodes, out_edges


def reverse_lookup_truncation(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    query: str,
    plan: ContextPlan,
    scopes: tuple[str, ...] = (),
) -> dict[str, object]:
    """Compare selected direct reverse neighbors with known graph adjacency."""
    relations = _reverse_lookup_relations(query)
    start_set = set(starts)
    known = {
        edge.source
        for edge in graph.edges
        if edge.active
        and edge.target in start_set
        and edge.type in relations
        and edge.confidence * provenance_confidence(edge.provenance) >= plan.min_confidence
        and (
            not scopes
            or (
                edge.source in graph.nodes
                and _path_in_scopes(graph.nodes[edge.source].path, scopes)
            )
        )
    }
    returned = {
        edge.source
        for edge in edges
        if edge.target in start_set
        and edge.type in relations
        and edge.source in nodes
    }
    omitted = known - returned
    return {
        "truncated": bool(omitted),
        "reason": "node_budget" if omitted and plan.node_budget is not None else "",
        "known_direct_neighbors": len(known),
        "returned_direct_neighbors": len(known & returned),
        "omitted_direct_neighbors": len(omitted),
    }


def expand_context(
    graph: Graph,
    starts: tuple[str, ...],
    plan: ContextPlan,
    scopes: tuple[str, ...] = (),
    query_terms: tuple[str, ...] = (),
) -> tuple[set[str], list[Edge]]:
    policy = traversal_policy(plan.query_class)
    if plan.query_class == "blast_radius" and plan.node_budget is not None:
        nodes, edges = _expand_blast_radius(graph, starts, plan, scopes)
    elif plan.query_class == "affected_tests":
        nodes, edges = _expand_affected_tests(graph, starts, plan, scopes)
    else:
        # `graph.expand` truncates the frontier to the node budget by edge
        # weight, which is query-blind: a document with more sections than the
        # budget loses sections by graph shape alone, so which ones survive is
        # unrelated to what was asked. For document-oriented retrieval, bias the
        # frontier ranking by each candidate section's BM25 relevance to the
        # query so the truncation keeps the sections that actually answer it.
        priority_bias: dict[str, float] = {}
        doc_oriented = bool(query_terms) and (
            plan.packet == "doc_summary" or plan.query_class == "doc_summary"
        )
        if doc_oriented:
            from .relevance import section_priority_bias
            priority_bias = section_priority_bias(graph, starts, query_terms)
        nodes, edges = graph.expand(
            list(starts),
            hops=plan.hops,
            max_nodes=plan.node_budget,
            scopes=scopes,
            direction=plan.direction,
            decay_hubs=(plan.query_class == "blast_radius"),
            allowed_relations=set(policy.preferred_relations),
            priority_bias=priority_bias or None,
        )
    if plan.query_class == "multi_hop_path" and len(starts) >= 2:
        nodes, edges = _reserve_paths_between_starts(graph, nodes, edges, starts, plan)
    if plan.query_class == "subsystem_summary":
        nodes, edges = _reserve_relation_family_evidence(graph, nodes, edges, starts, plan, limit=4)
    edges = [
        edge for edge in edges
        if edge.confidence * provenance_confidence(edge.provenance) >= plan.min_confidence
    ]
    edges = sorted(edges, key=lambda e: (*relation_rank(e.type, policy), e.source, e.target))
    
    # --- DYNAMIC EDGE DENSITY THROTTLE ---
    effective_node_budget = plan.node_budget
    if plan.node_budget is not None and len(nodes) > 10:
        density = len(edges) / max(1, len(nodes))
        if density > LOCAL_EDGE_DENSITY_CAP:
            scale = max(0.4, min(1.0, LOCAL_EDGE_DENSITY_CAP / density))
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
    nodes, edges = reserve_start_evidence(
        graph,
        nodes,
        edges,
        tuple(starts),
        plan,
        effective_node_budget,
        reserve_limit=4 if plan.query_class == "blast_radius" else 16,
    )
    nodes, edges = prune_doc_concept_noise(graph, nodes, edges, tuple(starts), plan, effective_node_budget)
    
    # Dynamic Programming Connected Tree Knapsack Context Partitioning
    if effective_node_budget is not None and len(nodes) > effective_node_budget:
        # Fast local BFS to propagate relevance scores from starts to candidates in O(nodes) time
        import collections

        from .selection import connected_greedy_context_partition, tree_knapsack_context_partition
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

        if plan.query_class == "blast_radius":
            start_set = set(starts)
            for edge in edges:
                neighbor = edge.source if edge.target in start_set else edge.target if edge.source in start_set else ""
                if not neighbor:
                    continue
                if edge.type in {"tests", "configures", "fixes"}:
                    node_values[neighbor] = max(node_values.get(neighbor, 0.0), 1.5)
                elif edge.target in start_set:
                    node_values[neighbor] = max(node_values.get(neighbor, 0.0), 1.1)

        # Query-conditioned section ranking: when a document contributes more
        # sections than the budget can hold, graph distance alone gives every
        # same-hop section the same value, so the survivors are effectively
        # arbitrary. Modulate doc/section node values by their BM25 relevance to
        # the query so the sections that actually answer it win the connected
        # selection below. Structural nodes get a 1.0 multiplier (no-op).
        if query_terms:
            from .relevance import relevance_multipliers
            candidate_nodes = [graph.nodes[nid] for nid in nodes if nid in graph.nodes]
            multipliers = relevance_multipliers(candidate_nodes, query_terms)
            start_set = set(starts)
            for node_id, factor in multipliers.items():
                if node_id not in start_set:
                    node_values[node_id] = node_values.get(node_id, 0.85) * factor

        partition_edges = list(edges)
        current_tokens = stats.estimated_tokens_by_packet.get(plan.packet, max(1, len(nodes) * 8))
        token_budget = max(
            effective_node_budget,
            int(round(current_tokens * effective_node_budget / max(1, len(nodes)))),
        )
        partition = (
            tree_knapsack_context_partition
            if plan.query_class == "multi_hop_path"
            else connected_greedy_context_partition
        )
        partitioned_nodes = partition(
            graph,
            tuple(starts),
            nodes,
            node_values,
            token_budget,
            edges=edges,
            packet=plan.packet,
            max_nodes=effective_node_budget,
            include_orphans=False,
        )
        if partitioned_nodes:
            nodes = partitioned_nodes
            edges = [e for e in edges if e.source in nodes and e.target in nodes]
        if plan.query_class == "blast_radius":
            nodes, edges = _reserve_blast_support_evidence(
                nodes,
                edges,
                partition_edges,
                starts,
                effective_node_budget,
            )

    if plan.query_class == "multi_hop_path" and len(starts) >= 2:
        nodes, edges = _reserve_paths_between_starts(graph, nodes, edges, starts, plan)
    if plan.query_class == "subsystem_summary":
        nodes, edges = _reserve_relation_family_evidence(graph, nodes, edges, starts, plan, limit=4)

    edges = shape_edge_budget(edges, tuple(starts), plan, node_count=len(nodes))
    return enrich_runtime_context(graph, nodes, edges, max_nodes=effective_node_budget)


PATH_BEAM_WIDTH = 32
# How strongly a policy-preferred relation is favoured over an unrecognized one
# when scoring a path edge. Large enough that a path made of recognized
# relations outranks a same-length path through incidental edges, but finite so
# a non-preferred edge is still usable when it is the only available route --
# the graded form of the old `recognized or candidates` hard fallback.
PATH_PREFERRED_RELATION_BONUS = 6.0


def _path_edge_strength(edge: Edge, policy) -> float:
    """Evidence strength of a single edge for path scoring (higher is better)."""
    strength = max(edge.traversal_val, 1e-6) * provenance_confidence(edge.provenance) * edge.confidence
    if edge.type in policy.preferred_relations:
        strength *= PATH_PREFERRED_RELATION_BONUS
    return strength


def _beam_best_path(
    graph: Graph,
    root: str,
    target: str,
    hops: int,
    policy,
    outgoing: dict[str, list[Edge]],
    incoming: dict[str, list[Edge]],
    beam_width: int = PATH_BEAM_WIDTH,
) -> tuple[Edge, ...]:
    """Strongest shortest path from root to target within `hops`, via beam search.

    Level-synchronous: it explores hop by hop, so the returned path is still of
    minimal length (like the previous BFS). The improvement is the tie-break --
    among equally short paths it keeps the one with the greatest cumulative edge
    strength (confidence x provenance x traversal value, with policy-preferred
    relations favoured) instead of whichever the adjacency happened to yield
    first. The beam bounds width to the top `beam_width` partial paths per level
    so cost stays linear in hops, not exponential.
    """
    # Each beam entry: (cumulative_log_strength, node, path_edges). Log-space so
    # per-edge strengths combine additively and long products stay stable.
    beam: list[tuple[float, str, tuple[Edge, ...]]] = [(0.0, root, ())]
    for _ in range(hops):
        completions: list[tuple[float, tuple[Edge, ...]]] = []
        next_best: dict[str, tuple[float, tuple[Edge, ...]]] = {}
        for score, current, path in beam:
            for edge in outgoing.get(current, []) + incoming.get(current, []):
                neighbor = edge.target if edge.source == current else edge.source
                if neighbor not in graph.nodes or not graph.nodes[neighbor].active:
                    continue
                if any(neighbor in (e.source, e.target) for e in path) or neighbor == root:
                    continue  # no cycles back through the path or root
                new_score = score + math.log(_path_edge_strength(edge, policy))
                new_path = (*path, edge)
                if neighbor == target:
                    completions.append((new_score, new_path))
                    continue
                best = next_best.get(neighbor)
                if best is None or new_score > best[0]:
                    next_best[neighbor] = (new_score, new_path)
        if completions:
            # Target reached at this (minimal) depth: return the strongest.
            return max(completions, key=lambda item: item[0])[1]
        if not next_best:
            break
        beam = sorted(
            ((score, node, path) for node, (score, path) in next_best.items()),
            key=lambda item: item[0],
            reverse=True,
        )[:beam_width]
    return ()


def _reserve_paths_between_starts(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    plan: ContextPlan,
) -> tuple[set[str], list[Edge]]:
    """Reserve the strongest bounded path from the first anchor to each other."""
    root = starts[0]
    policy = traversal_policy(plan.query_class)
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    reserved_nodes = set(starts)
    reserved_edges: list[Edge] = []

    for target in starts[1:]:
        found = _beam_best_path(graph, root, target, plan.hops, policy, outgoing, incoming)
        for edge in found:
            reserved_edges.append(edge)
            reserved_nodes.update((edge.source, edge.target))

    if not reserved_edges:
        return nodes, edges

    out_nodes = set(nodes) | reserved_nodes
    while plan.node_budget is not None and len(out_nodes) > plan.node_budget:
        removable = _least_valuable_context_node(graph, out_nodes, protected=reserved_nodes)
        if removable is None:
            break
        out_nodes.remove(removable)

    edge_by_key = {
        (edge.source, edge.target, edge.type): edge
        for edge in (*edges, *reserved_edges)
        if edge.source in out_nodes and edge.target in out_nodes
    }
    return out_nodes, list(edge_by_key.values())


def _expand_affected_tests(
    graph: Graph,
    starts: tuple[str, ...],
    plan: ContextPlan,
    scopes: tuple[str, ...],
) -> tuple[set[str], list[Edge]]:
    """Union direction-consistent implementation and test traversals.

    A single ``both`` traversal permits an in-then-out zigzag. For a method,
    that walks to its containing file and immediately fans out to every sibling
    definition. Separate incoming and outgoing traversals retain callers/tests
    and implementation dependencies without paying for that irrelevant fanout.
    The 60/40 split keeps the union within the original node budget because the
    duplicated start nodes are added back to the outgoing allocation.
    """
    policy = traversal_policy(plan.query_class)
    if plan.node_budget is None:
        incoming_budget = outgoing_budget = None
    else:
        start_count = min(len(starts), plan.node_budget)
        incoming_budget = max(start_count, math.ceil(plan.node_budget * 0.60))
        outgoing_budget = max(start_count, plan.node_budget - incoming_budget + start_count)

    incoming_nodes, incoming_edges = graph.expand(
        list(starts),
        hops=plan.hops,
        max_nodes=incoming_budget,
        scopes=scopes,
        direction="in",
        allowed_relations=set(policy.preferred_relations),
    )
    outgoing_nodes, outgoing_edges = graph.expand(
        list(starts),
        hops=plan.hops,
        max_nodes=outgoing_budget,
        scopes=scopes,
        direction="out",
        allowed_relations=set(policy.preferred_relations),
    )
    seen: set[tuple[str, str, str]] = set()
    edges: list[Edge] = []
    for edge in (*incoming_edges, *outgoing_edges):
        key = (edge.source, edge.target, edge.type)
        if key not in seen:
            edges.append(edge)
            seen.add(key)
    return incoming_nodes | outgoing_nodes, edges


def _reserve_relation_family_evidence(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    plan: ContextPlan,
    *,
    limit: int,
) -> tuple[set[str], list[Edge]]:
    """Keep one incident edge per available relation family for summaries."""
    policy = traversal_policy(plan.query_class)
    incident = []
    for start in starts:
        incident.extend(graph.outgoing().get(start, ()))
        incident.extend(graph.incoming().get(start, ()))
    recognized = [edge for edge in incident if edge.type in policy.preferred_relations]
    candidates = sorted(recognized or incident, key=lambda edge: (*relation_rank(edge.type, policy), edge.source, edge.target))

    selected: list[Edge] = []
    seen_families: set[str] = set()
    for edge in candidates:
        family = relation_spec(edge.type).family
        if family in seen_families:
            continue
        selected.append(edge)
        seen_families.add(family)
        if len(selected) >= limit:
            break

    reserved_nodes = set(starts)
    for edge in selected:
        reserved_nodes.update((edge.source, edge.target))
    out_nodes = set(nodes) | reserved_nodes
    while plan.node_budget is not None and len(out_nodes) > plan.node_budget:
        removable = _least_valuable_context_node(graph, out_nodes, protected=reserved_nodes)
        if removable is None:
            break
        out_nodes.remove(removable)

    edge_by_key = {
        (edge.source, edge.target, edge.type): edge
        for edge in (*edges, *selected)
        if edge.source in out_nodes and edge.target in out_nodes
    }
    return out_nodes, list(edge_by_key.values())


def _expand_blast_radius(
    graph: Graph,
    starts: tuple[str, ...],
    plan: ContextPlan,
    scopes: tuple[str, ...],
) -> tuple[set[str], list[Edge]]:
    total = max(len(starts), plan.node_budget or len(starts))
    impact_budget = max(len(starts), int(round(total * BLAST_IMPACT_SHARE)))
    support_budget = max(len(starts), int(round(total * BLAST_SUPPORT_SHARE)))
    outgoing_budget = max(len(starts), total - impact_budget - support_budget)

    branches = (
        graph.expand(
            list(starts),
            hops=plan.hops,
            max_nodes=impact_budget,
            scopes=scopes,
            direction="in",
            decay_hubs=False,
            allowed_relations=set(BLAST_IMPACT_RELATIONS),
        ),
        graph.expand(
            list(starts),
            hops=min(2, plan.hops),
            max_nodes=support_budget,
            scopes=scopes,
            direction="both",
            decay_hubs=False,
            allowed_relations=set(BLAST_SUPPORT_RELATIONS),
        ),
        graph.expand(
            list(starts),
            hops=min(1, plan.hops),
            max_nodes=outgoing_budget,
            scopes=scopes,
            direction="out",
            decay_hubs=True,
            allowed_relations=set(BLAST_OUTGOING_RELATIONS),
        ),
    )
    nodes: set[str] = set()
    edges_by_key: dict[tuple[str, str, str], Edge] = {}
    for branch_nodes, branch_edges in branches:
        nodes.update(branch_nodes)
        for edge in branch_edges:
            edges_by_key.setdefault((edge.source, edge.target, edge.type), edge)
    return nodes, list(edges_by_key.values())


def _reserve_blast_support_evidence(
    nodes: set[str],
    edges: list[Edge],
    candidate_edges: list[Edge],
    starts: tuple[str, ...],
    max_nodes: int,
    limit: int = 4,
) -> tuple[set[str], list[Edge]]:
    start_set = set(starts)
    support: list[tuple[str, Edge]] = []
    for edge in candidate_edges:
        if edge.type not in {"tests", "configures", "fixes"}:
            continue
        if edge.target in start_set:
            support.append((edge.source, edge))
        elif edge.source in start_set:
            support.append((edge.target, edge))

    out_nodes = set(nodes)
    protected = start_set | {node_id for node_id, _edge in support[:limit]}
    for node_id, _edge in support[:limit]:
        if node_id in out_nodes:
            continue
        if len(out_nodes) >= max_nodes:
            outgoing_context = sorted(
                edge.target
                for edge in candidate_edges
                if edge.source in start_set and edge.target in out_nodes and edge.target not in protected
            )
            removable = outgoing_context[0] if outgoing_context else next(
                (candidate for candidate in sorted(out_nodes) if candidate not in protected),
                None,
            )
            if removable is None:
                break
            out_nodes.remove(removable)
        out_nodes.add(node_id)
    out_edges = [edge for edge in candidate_edges if edge.source in out_nodes and edge.target in out_nodes]
    return out_nodes, out_edges


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
    for support_id in test_support_nodes:
        if support_id not in out_nodes:
            continue
        support = graph.nodes[support_id]
        support_dir = support.path.replace("\\", "/").rsplit("/", 1)[0]
        source_id = next(
            (
                start for start in starts
                if start in out_nodes
                and (node := graph.nodes.get(start)) is not None
                and node.path.replace("\\", "/").rsplit("/", 1)[0] == support_dir
            ),
            "",
        )
        key = (source_id, support_id, "configures")
        if source_id and key not in seen:
            out_edges.append(Edge(
                source_id,
                support_id,
                "configures",
                confidence=0.8,
                provenance="runtime_context",
                evidence="same test-directory support file",
            ))
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


def preferred_path_anchor_matches(
    graph: Graph,
    query: str,
    query_class: str,
    paths: tuple[str, ...],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[Match, ...]:
    """Compile exact edited paths into bounded per-file/per-facet anchor hints."""
    anchor_query = structural_anchor_query(query, query_class)
    # Exact-path locality is already strong evidence. Retain process terms
    # here (for example ``receipt consistency`` -> ``reconcile_*_receipt``)
    # so a relevant symbol can win without allowing those generic terms to
    # become global anchors.
    term_groups = list(facets)
    if not term_groups:
        terms = plan_terms(anchor_query)
        if terms:
            term_groups = [(anchor_query, terms)]
    named_owner_groups = tuple(
        terms
        for label, terms in facets
        if "_" in label or any(char.isupper() for char in label[1:])
    )
    named_owner_terms = tuple(dict.fromkeys(
        term for terms in named_owner_groups for term in terms
    ))
    degree: dict[str, int] = {}
    for edge in graph.edges:
        if edge.active:
            degree[edge.source] = degree.get(edge.source, 0) + 1
            degree[edge.target] = degree.get(edge.target, 0) + 1
    max_degree = max(degree.values(), default=0)

    normalized_paths = tuple(
        dict.fromkeys(path.replace("\\", "/").strip("/") for path in paths)
    )
    nodes_by_path: dict[str, list[object]] = {path: [] for path in normalized_paths}
    for node in graph.nodes.values():
        normalized = node.path.replace("\\", "/").strip("/")
        if node.active and normalized in nodes_by_path:
            nodes_by_path[normalized].append(node)

    file_node_kinds = {
        "python", "rust", "javascript", "typescript", "go", "java", "c", "cpp",
        "csharp", "ruby", "php", "kotlin", "scala", "swift",
    }
    per_path: list[list[Match]] = []
    for normalized in normalized_paths:
        path_nodes = nodes_by_path.get(normalized, ())
        file_nodes = [node for node in path_nodes if node.kind in file_node_kinds]
        eligible_nodes = [
            node
            for node in path_nodes
            if node.kind not in file_node_kinds
            if query_class == "doc_summary" or node.kind not in NON_STRUCTURAL_KINDS
            if not (query_class == "affected_tests" and _is_test_node(node))
        ]
        candidates: dict[str, Match] = {}
        query_winners: list[str] = []
        for label, terms in term_groups:
            if not terms:
                continue
            local_matches: list[Match] = []
            for node in eligible_nodes:
                hits = _facet_matched_terms(node, terms)
                if not hits:
                    continue
                label_hits = _facet_label_matched_terms(node, terms)
                owner_hits = _facet_matched_text_terms(
                    term_key(str(getattr(node, "id", ""))),
                    named_owner_terms,
                )
                owner_supported = any(
                    set(owner_terms) <= owner_hits
                    for owner_terms in named_owner_groups
                )
                required_hits = max(1, math.floor(len(terms) / 2) + 1)
                if len(hits) < required_hits:
                    # One generic word from a compound facet is not enough to
                    # make an exact-path symbol relevant (for example an
                    # `ideals_equal` helper answering "pinned corpus
                    # equality"). Fall back to the file when no symbol reaches
                    # this bounded evidence threshold.
                    continue
                if (
                    len(normalized_paths) > 1
                    and named_owner_groups
                    and not owner_supported
                    and not hits <= label_hits
                ):
                    # In a multi-slice request, a behavior word found only in
                    # a summary/fact does not bind that facet to every changed
                    # file. Require a named owner in the node identity or keep
                    # every matched behavior term in the symbol identity.
                    continue
                term_count = max(1, len(terms))
                coverage = len(hits) / term_count
                identity_coverage = len(label_hits) / term_count
                owner_coverage = max(
                    (
                        len(set(owner_terms) & owner_hits) / max(1, len(owner_terms))
                        for owner_terms in named_owner_groups
                    ),
                    default=0.0,
                )
                centrality = (
                    math.log2(degree.get(node.id, 0) + 1)
                    / math.log2(max_degree + 1)
                    if max_degree > 0
                    else 0.0
                )
                # Dimensionless evidence score: semantic coverage, identity
                # coverage, owner coherence, then a query-complexity-damped
                # topology tie-breaker. No repository-specific tuned weights.
                score = coverage + identity_coverage + owner_coverage + centrality / term_count
                local_matches.append(Match(
                    node,
                    score,
                    ("exact_changed_path_terms", f"facet:{label}"),
                ))
            if local_matches:
                winner = max(
                    local_matches,
                    key=lambda match: (
                        match.score,
                        degree.get(match.node.id, 0),
                        match.node.id,
                    ),
                )
                query_winners.append(winner.node.id)
                # A path is a hard locality constraint, not evidence that every
                # symbol in the file answers the facet. Keep one winner per
                # facet/path; traversal can recover its real neighbors.
                prior = candidates.get(winner.node.id)
                if prior is None or winner.score > prior.score:
                    candidates[winner.node.id] = winner
        if not candidates:
            fallback = max(
                file_nodes,
                key=lambda node: (degree.get(node.id, 0), node.id),
                default=None,
            )
            if fallback is not None:
                candidates[fallback.id] = Match(fallback, 0.0, ("file_fallback",))
        if not candidates:
            continue
        winner_ids = set(query_winners)
        ranked = sorted(
            candidates.values(),
            key=lambda match: (
                match.node.id not in winner_ids,
                -match.score,
                -degree.get(match.node.id, 0),
                match.node.id,
            ),
        )
        per_path.append(ranked)

    candidate_pool = {
        match.node.id: match
        for ranked in per_path
        for match in ranked
    }
    ordered: list[Match] = []
    for _label, terms in facets:
        evidence_terms = _facet_evidence_terms(terms)
        eligible = [
            match
            for match in candidate_pool.values()
            if _facet_matches_node(match.node, evidence_terms)
        ]
        if eligible:
            ordered.append(max(
                eligible,
                key=lambda match: (match.score, degree.get(match.node.id, 0), match.node.id),
            ))
    ordered.extend(ranked[0] for ranked in per_path if ranked)
    depth = 1
    max_depth = max((len(ranked) for ranked in per_path), default=0)
    while depth < max_depth:
        added = False
        for ranked in per_path:
            if depth < len(ranked):
                ordered.append(ranked[depth])
                added = True
        if not added:
            break
        depth += 1

    preferred: list[Match] = []
    seen: set[str] = set()
    for match in ordered:
        if match.node.id in seen:
            continue
        seen.add(match.node.id)
        preferred.append(Match(
            match.node,
            match.score,
            tuple(dict.fromkeys(("exact_changed_path", *match.reasons))),
        ))
        if len(preferred) >= 12:
            break
    return tuple(preferred)


def retrieve_context(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    seed_ids: tuple[str, ...] = (),
    anchor_paths: tuple[str, ...] = (),
) -> RetrievalResult:
    if scope_mode not in {"strict", "expand"}:
        raise ValueError(f"unknown scope mode: {scope_mode}")
    query = sanitize_query(query)
    if query_class == "doc_summary" and not scopes:
        explicit_doc_paths = _explicit_document_paths(graph, query)
        if len(explicit_doc_paths) == 1:
            scopes = explicit_doc_paths
            scope_mode = "strict"
    identifiers = explicit_query_identifiers(query)
    qualified_matches = (
        qualified_symbol_anchor_matches(graph, query, scopes=scopes)
        if query_class == "direct_lookup" and not anchor_paths
        else ()
    )
    facet_aware = query_class in {"affected_tests", "multi_hop_path", "negative_query", "doc_summary"} or (
        query_class in {"direct_lookup", "reverse_lookup"} and bool(identifiers)
    )
    facets = query_facets(query) if facet_aware else ()
    anchor_query = structural_anchor_query(query, query_class)
    path_matches = preferred_path_anchor_matches(
        graph,
        query,
        query_class,
        anchor_paths,
        facets,
    )
    exact_matches = (
        qualified_matches
        or
        search_nodes(
            graph,
            identifiers[0] if query_class == "reverse_lookup" and len(identifiers) == 1 else anchor_query,
            limit=1,
            scopes=scopes,
            exact_fast_path=True,
            exact_only=True,
        )
        if (
            not path_matches
            and (
                query_class == "direct_lookup"
                or (query_class == "reverse_lookup" and len(identifiers) == 1)
            )
        )
        else ()
    )
    exact_match = exact_matches[0] if exact_matches else None
    doc_intensity = 0.0
    if exact_match is None:
        doc_intensity = doc_intensity_score(query_class, query)
        graph_bias = doc_code_bias(graph)
        doc_intensity *= 0.75 + graph_bias * 0.5
    plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops)
    if max_nodes is None and exact_match is None:
        plan = apply_shape_budget(graph, plan, query)
    candidate_limit = max(plan.anchor_limit, plan.anchor_limit * 3 if query_class in STRUCTURAL_QUERY_CLASSES else plan.anchor_limit)
    if facets:
        candidate_limit = max(candidate_limit, min(36, len(facets) * 3))
    if query_class == "direct_lookup" and len(plan_terms(query)) == 1:
        candidate_limit = max(candidate_limit, 24)
    matches = (
        path_matches
        or ((exact_match,) if exact_match is not None else ())
        or search_nodes(
            graph,
            anchor_query,
            limit=max(candidate_limit, 1),
            doc_intensity=doc_intensity,
            personalize=True,
            scopes=scopes,
            exact_fast_path=query_class == "direct_lookup",
        )
    )
    source_matches = tuple(
        Match(
            graph.nodes[node_id],
            max(20.0, matches[0].score + 1.0 if matches else 20.0),
            ("source_planner",),
        )
        for node_id in dict.fromkeys(seed_ids)
        if node_id in graph.nodes and graph.nodes[node_id].active
    )
    priority_matches = (*path_matches, *source_matches)
    if priority_matches:
        priority_ids = {match.node.id for match in priority_matches}
        matches = priority_matches + tuple(
            match for match in matches if match.node.id not in priority_ids
        )
    exact_anchor_fast_path = (
        len(matches) == 1 and "exact_fast_path" in matches[0].reasons
    )
    if facets and not path_matches and not exact_anchor_fast_path:
        # A single bag-of-words search for a conjunction is dominated by nodes
        # that repeat the query's common subsystem terms. Search each facet
        # independently, then merge its best evidence into the candidate pool
        # before anchor selection. This is bounded by the twelve-facet parser
        # cap and preserves the original whole-query ranking at the front.
        merged = list(matches)
        seen_match_ids = {match.node.id for match in merged}
        for facet_label, facet_terms in facets:
            for facet_query in facet_search_queries(facet_label, facet_terms):
                facet_matches = search_nodes(
                    graph,
                    facet_query,
                    limit=12,
                    doc_intensity=0.0,
                    personalize=True,
                    scopes=scopes,
                )
                for match in facet_matches:
                    if match.node.id not in seen_match_ids:
                        merged.append(match)
                        seen_match_ids.add(match.node.id)
        matches = tuple(merged)
    inferred_scope = "" if scopes else infer_dominant_scope(matches, query)
    if inferred_scope and not facets:
        coherent = tuple(match for match in matches if _path_in_scopes(match.node.path, (inferred_scope,)))
        if coherent:
            matches = coherent
    if (
        query_class in {"blast_radius", "subsystem_summary"}
        and max_nodes is None
        and not any(_is_targeted_symbol_anchor(match) for match in matches[:3])
        and plan.node_budget is not None
    ):
        # Keep exact-symbol impact analysis recall-first, but ambiguous prose
        # should be an orientation packet. Otherwise several loose anchors can
        # each contribute a two-hop neighborhood and consume ~100 nodes.
        plan = replace(
            plan,
            node_budget=min(plan.node_budget, 48),
            reason=f"{plan.reason}; ambiguous broad-query cap",
            planner_version=f"{plan.planner_version}_broad_query_cap",
        )
    effective_anchor_limit = (
        _adaptive_anchor_limit(matches, plan, query)
        if query_class in STRUCTURAL_QUERY_CLASSES or query_class in {"direct_lookup", "subsystem_summary"}
        else plan.anchor_limit
    )
    if (
        query_class == "affected_tests"
        and identifiers
        and len(plan_terms(anchor_query)) > len(identifiers)
    ):
        # "Type method changes" names a member in prose even when the method
        # itself is not code-shaped. Keep the exact type and its matching
        # member as roots; the intent-sanitized query prevents affected/change
        # homonyms from consuming this second slot.
        effective_anchor_limit = max(2, effective_anchor_limit)
    if source_matches:
        effective_anchor_limit = max(
            effective_anchor_limit,
            min(12, len(source_matches) + plan.anchor_limit),
        )
    if path_matches:
        effective_anchor_limit = max(effective_anchor_limit, min(12, len(path_matches)))
    if facets and not path_matches and not exact_anchor_fast_path:
        effective_anchor_limit = max(effective_anchor_limit, min(12, len(facets)))
    selected_matches = select_anchor_matches(
        matches,
        effective_anchor_limit,
        query_class,
        doc_intensity >= 0.35,
        query=query,
        graph=graph,
        dominant_scope=inferred_scope,
    )
    if facets and not path_matches and not exact_anchor_fast_path:
        selected_matches = reserve_facet_matches(
            selected_matches,
            matches,
            facets,
            graph=graph,
            prefer_code=query_class == "multi_hop_path",
        )
    if path_matches:
        # Exact edited paths are an explicit ANCHOR instruction. They define
        # roots; ordinary lexical matches may still enter through structural
        # expansion, but cannot become competing roots.
        selected_matches = path_matches[:effective_anchor_limit]
    selected_matches = select_enumerated_doc_roots(
        selected_matches,
        matches,
        query=query,
        query_class=query_class,
    )
    if query_class == "negative_query" and facets:
        selected_ids = {match.node.id for match in selected_matches}
        anchor_coverage = facet_coverage(
            graph,
            {
                node_id
                for node_id in selected_ids
                if is_code_like(graph.nodes[node_id])
            },
            facets,
        )
        if not anchor_coverage["fulfilled"]:
            mention_coverage = facet_coverage(graph, selected_ids, facets)
            return RetrievalResult(
                starts=(),
                matches=selected_matches,
                nodes=set(),
                edges=[],
                metadata={
                    "facet_coverage": anchor_coverage,
                    "mention_coverage": mention_coverage,
                    "answerability": {
                        "status": "unanswerable",
                        "abstained": True,
                        "reason": "no code or structural graph evidence covers the requested entity facets",
                    },
                    "plan_reason": plan.reason,
                    "planner_version": plan.planner_version,
                },
            )
    starts_list = list(match.node.id for match in selected_matches)
    facet_roots = tuple(starts_list[:12])
    if query_class == "reverse_lookup":
        starts_list = list(reserve_reverse_contract_starts(graph, tuple(starts_list), query=query))

    # Discover git-modified files (active session context / Ephemeral Session Layer).
    # Dirty files are useful ambient context for exploratory summaries and
    # activation, but appending them as traversal starts changes the semantics
    # of exact lookup/path/impact queries. Search personalization already gives
    # modified files a ranking boost without forcing unrelated nodes into those
    # result subgraphs.
    if query_class in SESSION_CONTEXT_QUERY_CLASSES:
        from .git_utils import get_git_modified_files, select_modified_context_nodes
        modified_paths = get_git_modified_files()
        selected = select_modified_context_nodes(
            graph,
            modified_paths,
            query,
            exclude=tuple(starts_list),
        )
        if inferred_scope:
            selected = tuple(
                node_id for node_id in selected
                if _path_in_scopes(graph.nodes[node_id].path, (inferred_scope,))
            )
        starts_list.extend(node_id for node_id in selected if node_id not in starts_list)

    starts = tuple(starts_list[:12])
    if not starts:
        return RetrievalResult(
            starts=(),
            matches=matches,
            nodes=set(),
            edges=[],
            metadata={
                "answerability": {
                    "status": "unanswerable",
                    "abstained": True,
                    "reason": "no matching graph anchors",
                },
            },
        )

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
        expansion_scopes = scopes if scope_mode == "strict" else ()
        nodes, edges = expand_context(graph, starts, plan, scopes=expansion_scopes, query_terms=plan_terms(query))
        nodes, edges = reserve_query_named_siblings(graph, nodes, edges, starts, query, plan)
        nodes, edges = reserve_ordered_doc_siblings(graph, nodes, edges, starts, query, plan)
        if query_class == "reverse_lookup":
            nodes, edges = reserve_reverse_direct_neighbors(
                graph,
                nodes,
                edges,
                starts,
                query,
                plan,
                scopes=expansion_scopes,
            )
            nodes, edges = prune_concrete_contract_siblings(
                graph,
                nodes,
                edges,
                roots=facet_roots,
            )
        if query_class == "affected_tests":
            nodes, edges = reserve_affected_test_evidence(graph, nodes, edges, starts, plan)
    if (
        query_class == "direct_lookup"
        and exact_anchor_fast_path
        and set(plan_terms(query)) & {"call", "calls", "called", "calling"}
    ):
        # An exact `Type::method` call question is a direct adjacency read.
        # Containment and documentation expansion can only add siblings/noise;
        # derive the slice from the graph's outgoing call table regardless of
        # a generously supplied node budget.
        start_set = set(starts)
        edges = [
            edge
            for edge in graph.edges
            if edge.active
            and edge.source in start_set
            and edge.type == "calls"
            and edge.confidence * provenance_confidence(edge.provenance) >= plan.min_confidence
        ]
        nodes = set(starts) | {edge.target for edge in edges}
    if query_class in STRUCTURAL_QUERY_CLASSES:
        nodes, edges = prune_unexplained_structural_nodes(nodes, edges, starts)
    if inferred_scope:
        nodes, edges = cap_inferred_scope_crossings(graph, nodes, edges, inferred_scope, protected=starts)
    if scopes and scope_mode == "strict":
        nodes = {node_id for node_id in nodes if _path_in_scopes(graph.nodes[node_id].path, scopes)}
        edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]
    effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
    metadata = packet_quality_metadata(
        graph,
        nodes,
        edges,
        starts,
        effective_scope,
        query_class=query_class,
    )
    if (
        query_class == "doc_summary"
        and metadata["quality"]["grounded_doc_nodes"] == 0
    ):
        metadata["quality"]["document_warning"] = (
            "doc_summary selected zero grounded document body nodes"
        )
    metadata.update({
        "scope": list(scopes),
        "scope_mode": "auto_expand" if inferred_scope and not scopes else scope_mode,
        "inferred_scope": inferred_scope,
        "anchor_strategy": (
            "exact_fast_path"
            if selected_matches
            and all("exact_fast_path" in match.reasons for match in selected_matches)
            else "ranked"
        ),
        "plan_reason": plan.reason,
        "planner_version": plan.planner_version,
        "node_budget": plan.node_budget,
        "anchor_limit": effective_anchor_limit,
        "anchor_paths": [
            {
                "path": path,
                "role": (
                    "test_evidence_candidate"
                    if query_class == "affected_tests" and _is_test_path(path)
                    else "file_fallback"
                    if any(
                        match.node.path.replace("\\", "/").strip("/")
                        == path.replace("\\", "/").strip("/")
                        and "file_fallback" in match.reasons
                        for match in selected_matches
                    )
                    else "primary_root"
                ),
                "anchors": [
                    match.node.id
                    for match in selected_matches
                    if match.node.path.replace("\\", "/").strip("/")
                    == path.replace("\\", "/").strip("/")
                ],
            }
            for path in dict.fromkeys(anchor_paths)
        ],
    })
    if facets:
        coverage = facet_coverage(graph, nodes, facets, roots=facet_roots or starts)
        metadata["facet_coverage"] = coverage
        structural_coverage = None
        if query_class in {"multi_hop_path", "direct_lookup", "reverse_lookup"}:
            structural_coverage = facet_coverage(
                graph,
                {
                    node_id
                    for node_id in nodes
                    if is_code_like(graph.nodes[node_id])
                },
                facets,
                roots=facet_roots or starts,
            )
            metadata["structural_facet_coverage"] = structural_coverage
        incomplete = bool(coverage["unfulfilled"]) or bool(
            structural_coverage and structural_coverage["unfulfilled"]
        )
        metadata["answerability"] = {
            "status": "incomplete" if incomplete else "answerable",
            "abstained": False,
            "reason": (
                "one or more requested facets have no code or structural evidence"
                if structural_coverage and structural_coverage["unfulfilled"]
                else coverage["warning"]
            ),
        }
    else:
        metadata["answerability"] = {
            "status": "answerable",
            "abstained": False,
            "reason": "",
        }
    document_warning = str(metadata["quality"].get("document_warning", ""))
    if query_class == "doc_summary" and document_warning:
        metadata["answerability"] = {
            "status": "incomplete",
            "abstained": True,
            "reason": document_warning,
        }
    if query_class == "reverse_lookup":
        truncation = reverse_lookup_truncation(
            graph,
            nodes,
            edges,
            starts,
            query,
            plan,
            scopes=scopes if scope_mode == "strict" else (),
        )
        metadata["truncation"] = truncation
        if truncation["truncated"]:
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": (
                    f"node budget omitted {truncation['omitted_direct_neighbors']} "
                    "known direct reverse neighbor(s)"
                ),
            }
    changed_path_tests = changed_path_test_recommendations(graph, anchor_paths)
    if query_class == "affected_tests":
        affected = affected_test_recommendations(graph, starts, nodes)
        if changed_path_tests["commands"]:
            affected["commands"] = list(dict.fromkeys((
                *affected["commands"],
                *changed_path_tests["commands"],
            )))
            affected["commands_by_role"]["changed_path_regression"] = changed_path_tests["commands"]
            affected["command_provenance"] = [
                *affected["command_provenance"],
                *changed_path_tests["command_provenance"],
            ]
            affected["changed_path_candidates"] = changed_path_tests["candidates"]
        metadata["affected_tests"] = affected
        metadata["hybrid_intents"] = ["multi_hop_path", "affected_tests"]
    elif changed_path_tests["commands"]:
        metadata["affected_tests"] = {
            "direct": [],
            "transitive": [],
            "commands": changed_path_tests["commands"],
            "commands_by_role": {
                "direct_behavior_or_contract": [],
                "transitive_regression": [],
                "changed_path_regression": changed_path_tests["commands"],
            },
            "command_provenance": changed_path_tests["command_provenance"],
            "changed_path_candidates": changed_path_tests["candidates"],
            "omitted_transitive": 0,
        }
    if query_class == "doc_summary" and not any(
        node.kind in {"section", "paragraph"} for node in graph.nodes.values()
    ):
        # Documentation query against a graph that carries no grounded doc-body
        # nodes -- it was built without document extraction, so retrieval can
        # only return file pointers. Say so with the fix, rather than silently
        # degrading (a graph built with docs=true grounds paragraph prose fine).
        metadata["document_extraction"] = {
            "grounded": False,
            "hint": (
                "This graph has no document section/paragraph nodes, so documentation "
                "queries return only file pointers. Rebuild with document extraction for "
                "grounded prose: build_graph with docs=true (or `graphgraph scan --docs`)."
            ),
        }
    return RetrievalResult(starts=starts, matches=selected_matches, nodes=nodes, edges=edges, metadata=metadata)


def qualified_symbol_anchor_matches(
    graph: Graph,
    query: str,
    *,
    scopes: tuple[str, ...] = (),
) -> tuple[Match, ...]:
    """Resolve one explicit ``Type::member`` to its owner-qualified definition."""
    qualified = _qualified_query_symbols(query)
    if len(qualified) != 1:
        return ()
    owner, member = qualified[0]
    owner_terms = set(term_key(owner).split())
    candidates = search_nodes(
        graph,
        member,
        limit=24,
        scopes=scopes,
        exact_fast_path=False,
    )
    matched: list[Match] = []
    for candidate in candidates:
        node = candidate.node
        if term_key(node.label) != term_key(member):
            continue
        context_terms = set(term_key(" ".join((
            node.id,
            node.summary,
            graph.nodes[node.parent].label
            if node.parent and node.parent in graph.nodes
            else "",
        ))).split())
        if owner_terms and owner_terms <= context_terms:
            matched.append(Match(
                node,
                candidate.score + 25.0,
                tuple(dict.fromkeys((
                    "exact_fast_path",
                    "qualified_owner_exact",
                    *candidate.reasons,
                ))),
            ))
    if len(matched) != 1:
        return ()
    return (matched[0],)


def _path_in_scopes(path: str, scopes: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return any(
        normalized == scope.replace("\\", "/").strip("/")
        or normalized.startswith(scope.replace("\\", "/").strip("/") + "/")
        for scope in scopes
    )


def _explicit_document_paths(graph: Graph, query: str) -> tuple[str, ...]:
    """Resolve graph-known document paths embedded in natural-language input."""
    normalized_query = query.replace("\\", "/").casefold()
    return tuple(sorted({
        node.path.replace("\\", "/").strip("/")
        for node in graph.nodes.values()
        if node.active
        and node.path
        and Path(node.path).suffix.casefold() in {".md", ".mdx", ".rst", ".txt", ".html", ".htm"}
        and node.path.replace("\\", "/").strip("/").casefold() in normalized_query
    }))


def _package_scope(path: str) -> str:
    parts = path.replace("\\", "/").strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"crates", "packages", "apps", "libs", "modules"}:
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "src":
        return "/".join(parts[:2]) if len(parts) >= 3 else "src"
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


def infer_dominant_scope(matches: tuple[Match, ...], query: str) -> str:
    """Infer scope only from high-confidence symbol anchors, never generic words."""
    exact = [match for match in matches[:8] if _is_targeted_symbol_anchor(match)]
    if not exact:
        return ""
    mass: dict[str, float] = {}
    for match in exact:
        scope = _package_scope(match.node.path)
        if scope:
            mass[scope] = mass.get(scope, 0.0) + max(0.0, match.score)
    if not mass:
        return ""
    winner, winner_mass = max(mass.items(), key=lambda item: item[1])
    total = sum(mass.values()) or 1.0
    return winner if winner_mass / total >= 0.67 else ""


def packet_quality_metadata(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    scope: str,
    *,
    query_class: str = "",
) -> dict[str, object]:
    covered = {endpoint for edge in edges for endpoint in (edge.source, edge.target)}
    isolated = nodes - covered - set(starts)
    cross_scope = {
        node_id for node_id in nodes
        if scope and not _path_in_scopes(graph.nodes[node_id].path, (scope,))
    }
    contribution = {
        start: sum(1 for edge in edges if edge.source == start or edge.target == start)
        for start in starts
    }
    doc_nodes = [graph.nodes[node_id] for node_id in nodes if graph.nodes[node_id].kind in NON_STRUCTURAL_KINDS]
    grounded_doc_nodes = sum(1 for node in doc_nodes if node.facts)
    topology_trust = query_topology_trust(
        edges,
        metadata=graph.metadata,
        query_class=query_class,
    )
    concept_eligible = int(graph.metadata.get("source_concepts_eligible", "0") or 0)
    concept_linked = int(graph.metadata.get("source_concepts_linked_nodes", "0") or 0)
    concept_coverage = concept_linked / max(1, concept_eligible)
    semantic_support = {
        "status": (
            "unavailable"
            if concept_eligible == 0
            else "sparse"
            if concept_coverage < 0.2
            else "partial"
            if concept_coverage < 0.8
            else "strong"
        ),
        "linked_nodes": concept_linked,
        "eligible_nodes": concept_eligible,
        "coverage_ratio": round(concept_coverage, 4),
        "scope": graph.metadata.get("source_concepts_scope", "unavailable"),
        "retrieval_mode": (
            "lexical_document_fallback"
            if query_class == "doc_summary" and concept_coverage < 0.2
            else "lexical_structural_fallback"
            if query_class == "subsystem_summary" and concept_coverage < 0.2
            else "graph_supported"
        ),
    }
    return {
        "quality": {
            "nodes": len(nodes),
            "edges": len(edges),
            "isolated_nodes": len(isolated),
            "edge_covered_node_ratio": round(len(covered & nodes) / max(1, len(nodes)), 4),
            "lexical_only_nodes": len(isolated),
            "cross_scope_nodes": len(cross_scope),
            "anchor_contribution": contribution,
            "grounded_doc_nodes": grounded_doc_nodes,
            "ungrounded_doc_nodes": len(doc_nodes) - grounded_doc_nodes,
            "document_warning": "no grounded document body content" if doc_nodes and grounded_doc_nodes == 0 else "",
            "topology_trust": topology_trust,
            "semantic_support": semantic_support,
        }
    }


def query_topology_trust(
    edges: list[Edge],
    *,
    metadata: dict[str, str] | None = None,
    query_class: str = "",
) -> dict[str, object]:
    """Combine selected-edge trust with global call-extraction coverage."""
    call_edges = [edge for edge in edges if edge.type == "calls"]
    ambiguous_calls = [
        edge for edge in call_edges
        if "ambiguous" in edge.provenance.casefold() or edge.confidence < 0.6
    ]
    trusted_calls = [
        edge for edge in call_edges
        if edge not in ambiguous_calls
        and edge.confidence * provenance_confidence(edge.provenance) >= 0.7
    ]
    topology_status = (
        "not_applicable"
        if not call_edges
        else "low"
        if ambiguous_calls and len(ambiguous_calls) > len(trusted_calls)
        else "mixed"
        if ambiguous_calls
        else "high"
    )
    result: dict[str, object] = {
        "status": topology_status,
        "call_edges": len(call_edges),
        "trusted_call_edges": len(trusted_calls),
        "ambiguous_call_edges": len(ambiguous_calls),
        "scope": "selected_packet",
    }
    if query_class not in {
        "affected_tests",
        "blast_radius",
        "multi_hop_path",
        "reverse_lookup",
    }:
        return result
    graph_metadata = metadata or {}
    global_counts = {
        name: int(graph_metadata.get(f"member_calls_global_{name}", "0") or 0)
        for name in ("resolved", "ambiguous", "unknown_receiver", "unresolved")
    }
    total = sum(global_counts.values())
    if total == 0:
        return result
    usable = global_counts["resolved"]
    coverage = usable / total
    global_status = "high" if coverage >= 0.8 else "partial" if coverage >= 0.2 else "low"
    result.update({
        "local_status": topology_status,
        "global_status": global_status,
        "global_call_coverage_ratio": round(coverage, 4),
        "global_counts": global_counts,
        "scope": "selected_packet+global_extraction",
    })
    if global_status != "high":
        result["status"] = global_status
    return result


def cap_inferred_scope_crossings(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    scope: str,
    *,
    protected: tuple[str, ...] = (),
) -> tuple[set[str], list[Edge]]:
    """Keep automatic scope porous but bound its cross-package token spend."""
    in_scope = {node_id for node_id in nodes if _path_in_scopes(graph.nodes[node_id].path, (scope,))}
    outside = nodes - in_scope
    if not outside:
        return nodes, edges
    protected_outside = set(protected) & outside
    connector_budget = max(2, min(6, math.ceil(math.log2(len(in_scope) + 1))))
    limit = min(12, len(protected_outside) + connector_budget)
    boundary_score: dict[str, float] = {node_id: 0.0 for node_id in outside}
    for edge in edges:
        if edge.source in outside and edge.target in in_scope:
            boundary_score[edge.source] += 2.0 * edge.traversal_val
        elif edge.target in outside and edge.source in in_scope:
            boundary_score[edge.target] += 2.0 * edge.traversal_val
        elif edge.source in outside and edge.target in outside:
            boundary_score[edge.source] += 0.25 * edge.traversal_val
            boundary_score[edge.target] += 0.25 * edge.traversal_val
    ranked_outside = sorted(outside - protected_outside, key=lambda node_id: (-boundary_score[node_id], node_id))
    kept_outside = protected_outside | set(ranked_outside[:max(0, limit - len(protected_outside))])
    kept = in_scope | kept_outside
    return kept, [edge for edge in edges if edge.source in kept and edge.target in kept]


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    name = normalized.rsplit("/", 1)[-1]
    return "/tests/" in f"/{normalized}" or name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".spec.ts"))


def _is_test_node(node: object) -> bool:
    facts = {
        str(fact).casefold()
        for fact in (getattr(node, "facts", ()) or ())
    }
    if facts & {"role:test", "rust_attribute:test"}:
        return True
    if _is_test_path(str(getattr(node, "path", ""))) and str(
        getattr(node, "kind", "")
    ) in {"function", "method"}:
        return True
    source = str(getattr(node, "source", ""))
    line = getattr(node, "line", None)
    return bool(
        source
        and isinstance(line, int)
        and _source_declares_rust_test(source, line)
    )


@lru_cache(maxsize=8192)
def _source_declares_rust_test(source: str, line: int) -> bool:
    """Recover inline-test identity for graphs built before test-role IR facts."""
    path = Path(source)
    if path.suffix.casefold() != ".rs" or not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    start = max(0, line - 5)
    end = min(len(lines), line + 1)
    declaration_prefix = "\n".join(lines[start:end])
    return bool(re.search(
        r"#\s*\[\s*(?:tokio::)?test(?:\s*\([^]]*\))?\s*\]",
        declaration_prefix,
    ))


def query_facets(query: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    facets: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    facet_query = re.sub(
        r"\b(?:the\s+)?(?:exact\s+)?changed[-\s]+(?:file[-\s]+)?paths\b",
        " ",
        query,
        flags=re.I,
    )
    qualified = _qualified_query_symbols(query)
    qualified_owners = {owner.casefold() for owner, _member in qualified}
    raw_identifiers = {
        raw.casefold(): raw
        for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)
    }
    for owner, member in qualified:
        terms = tuple(term_key(f"{owner} {member}").split())
        if terms and terms not in seen:
            facets.append((f"{owner}::{member}", terms))
            seen.add(terms)
    for identifier in explicit_query_identifiers(query):
        if identifier.casefold() in qualified_owners:
            continue
        display = raw_identifiers.get(identifier.casefold(), identifier)
        terms = tuple(part for part in term_key(display).split() if len(part) >= 2)
        if terms and terms not in seen:
            facets.append((display, terms))
            seen.add(terms)
    identifiers = explicit_query_identifiers(query)
    identifier_terms = {
        part
        for identifier in identifiers
        for part in term_key(identifier.replace("-", "_")).split()
        if len(part) >= 2
    }
    intent_terms = {
        "and", "which", "tests", "test", "cover", "covers", "covered", "coverage",
        "run", "how", "does", "do", "measure", "measures", "measured", "report",
        "reports", "show", "shows", "including", "include", "through", "chain",
        "every", "each", "all", "part", "parts", "entire", "whole", "requested", "above",
        "positive", "negative",
        "documentation", "documents", "document", "docs", "doc",
        "say", "says", "said", "under",
        "roadmap", "row", "now", "claim", "claims", "claimed",
        "capability", "capabilities", "remain", "remains",
        "affected", "affecting", "impact", "impacted",
        "call", "calls", "called", "caller", "callers", "calling",
        "consume", "consumes", "consumed", "consumer", "use", "uses", "used",
        "should", "if", "change", "changes", "changed", "changing", "behavior", "behaviour",
        "evaluate", "evaluates", "evaluated", "evaluating",
        "assess", "assesses", "assessed", "assessing",
        "gate", "gates", "gated", "gating",
        "direct", "directly", "transitive",
        "validate", "validates", "validated", "validating", "validation",
        "identify", "identifies", "identified", "identifying",
        "exact", "command", "commands",
        "add", "adds", "added", "adding", "after", "before",
        "behavioral", "focus", "focused", "minimal", "runnable", "return", "returns",
        "own", "step", "steps", "according", "md",
        "then",
        "it", "its", "them", "their", "these", "those",
        "cargo",
        "where", "what", "why", "who", "when", "is", "are", "was", "were",
        "the", "a", "an", "from", "into", "flow", "flows",
        "nonexistent", "missing", "implemented", "implements",
    }
    for clause in re.split(
        r"\s*(?:,|;|\band\b|\bplus\b|\bwhich\b)\s*",
        facet_query,
        flags=re.I,
    ):
        for identifier in identifiers:
            clause = re.sub(rf"\b{re.escape(identifier)}\b", " ", clause, flags=re.I)
        for owner, member in qualified:
            clause = re.sub(
                rf"\b{re.escape(owner)}\s*::\s*{re.escape(member)}\b",
                " ",
                clause,
                flags=re.I,
            )
        terms = tuple(
            term for term in plan_terms(clause)
            if term not in intent_terms and term not in identifier_terms
        )
        meaningful_single = len(terms) == 1 and len(terms[0]) >= 4
        if (meaningful_single or 2 <= len(terms) <= 6) and terms not in seen:
            facets.append((" ".join(terms), terms))
            seen.add(terms)
    return tuple(facets[:12])


def facet_search_queries(label: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Bounded relaxed searches let prose facets reach compound code symbols."""
    queries = [label]
    if len(terms) >= 3:
        queries.extend(
            " ".join(terms[index : index + 2])
            for index in range(len(terms) - 1)
        )
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def _facet_node_text(node: object) -> str:
    return term_key(" ".join((
        str(getattr(node, "label", "")),
        str(getattr(node, "path", "")),
        str(getattr(node, "summary", "")),
        " ".join(getattr(node, "facts", ()) or ()),
    )))


def _symbol_identity_terms(node: object) -> set[str]:
    """Owner-aware terms for same-file candidate coherence."""
    return set(term_key(" ".join((
        str(getattr(node, "id", "")),
        str(getattr(node, "label", "")),
        str(getattr(node, "summary", "")),
    ))).split())


def facet_coverage(
    graph: Graph,
    nodes: set[str],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    roots: tuple[str, ...] = (),
) -> dict[str, object]:
    fulfilled: list[dict[str, object]] = []
    unfulfilled: list[str] = []
    for label, terms in facets:
        evidence = [
            node_id for node_id in sorted(nodes)
            if _facet_matches_node(graph.nodes[node_id], terms)
        ]
        if not evidence:
            evidence = _facet_structural_evidence(
                graph,
                nodes,
                terms,
                roots=roots,
            )
        if not evidence and len(_facet_evidence_terms(terms)) >= 3:
            needed = set(_facet_evidence_terms(terms))
            distributed = sorted(
                (
                    (-len(hits), node_id, hits)
                    for node_id in nodes
                    if len(hits := _facet_matched_terms(graph.nodes[node_id], tuple(needed))) >= 2
                ),
            )
            covered: set[str] = set()
            selected: list[str] = []
            for _negative_hits, node_id, hits in distributed:
                if not (hits - covered):
                    continue
                selected.append(node_id)
                covered.update(hits)
                if covered >= needed or len(selected) >= 3:
                    break
            if covered >= needed:
                evidence = selected
        if evidence:
            fulfilled.append({"facet": label, "evidence": evidence[:5]})
        else:
            unfulfilled.append(label)
    return {
        "fulfilled": fulfilled,
        "unfulfilled": unfulfilled,
        "coverage_ratio": round(len(fulfilled) / max(1, len(facets)), 4),
        "warning": "unfulfilled query facets" if unfulfilled else "",
    }


def _facet_structural_evidence(
    graph: Graph,
    nodes: set[str],
    terms: tuple[str, ...],
    *,
    roots: tuple[str, ...],
) -> list[str]:
    """Credit relationship facets from selected topology, not only node text."""
    if not roots:
        return []
    targets = set(roots)
    targets.update(
        node_id
        for node_id in nodes
        if graph.nodes[node_id].parent in targets
    )
    targets.update(
        edge.target
        for edge in graph.edges
        if edge.active
        and edge.type == "contains"
        and edge.source in targets
        and edge.target in nodes
    )
    relation_edges = [
        edge
        for edge in graph.edges
        if edge.active
        and edge.source in nodes
        and edge.target in targets
        and edge.type in {"calls", "references", "tests", "registers"}
    ]
    forms = {
        form
        for term in terms
        for form in _facet_term_forms(term)
    }
    if forms & {"exercise", "exercises", "exercised"}:
        return sorted({
            edge.source
            for edge in relation_edges
            if _is_test_node(graph.nodes[edge.source])
        })
    if forms & {"register", "registers", "registered", "registration", "registry"}:
        return sorted({
            edge.source
            for edge in relation_edges
            if edge.type == "registers"
            or set(_facet_node_text(graph.nodes[edge.source]).split())
            & {"default", "domain", "register", "registered", "registry"}
        })
    return []


def reserve_facet_matches(
    selected: tuple[Match, ...],
    candidates: tuple[Match, ...],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    graph: Graph | None = None,
    prefer_code: bool = False,
    limit: int = 12,
) -> tuple[Match, ...]:
    """Reserve one independently retrieved anchor for every requested facet."""
    reserved = list(selected)
    seen = {match.node.id for match in reserved}
    for _label, terms in facets:
        matching_reserved = [
            match for match in reserved if _facet_matches_node(match.node, terms)
        ]
        if matching_reserved and (
            not prefer_code
            or graph is None
            or any(is_code_like(match.node) for match in matching_reserved)
        ):
            continue
        eligible = [
            match
            for match in candidates
            if match.node.id not in seen and _facet_matches_node(match.node, terms)
        ]
        code_eligible = [match for match in eligible if is_code_like(match.node)]
        needs_distributed_code = prefer_code and not code_eligible
        if (not eligible or needs_distributed_code) and len(_facet_evidence_terms(terms)) >= 3:
            needed = set(_facet_evidence_terms(terms))
            covered: set[str] = set()
            distributed = sorted(
                (
                    (
                        0 if not prefer_code or is_code_like(match.node) else 1,
                        -len(hits),
                        -match.score,
                        match.node.id,
                        match,
                        hits,
                    )
                    for match in candidates
                    if match.node.id not in seen
                    if len(hits := _facet_matched_terms(match.node, tuple(needed))) >= 2
                ),
                key=lambda item: item[:4],
            )
            for _kind_rank, _hit_rank, _score_rank, _node_id, match, hits in distributed:
                if not (hits - covered):
                    continue
                reserved.append(match)
                seen.add(match.node.id)
                covered.update(hits)
                if covered >= needed or len(reserved) >= limit:
                    break
            if covered >= needed:
                continue
        candidate = next(
            iter(code_eligible if prefer_code else eligible),
            eligible[0] if eligible else None,
        )
        if candidate is not None:
            reserved.append(candidate)
            seen.add(candidate.node.id)
        if len(reserved) >= limit:
            break
    return tuple(reserved[:limit])


_FACET_PROCESS_TERMS = {
    "discovery", "equivalence", "rationalization", "implementation", "implementations",
    "measurement", "measurements",
    "anchoring", "calibrated", "calibration", "consistency", "query", "readiness",
    "reconciliation", "selection", "specific",
}


def _facet_evidence_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Keep a facet's domain terms while treating process nouns as intent."""
    reduced = tuple(term for term in terms if term not in _FACET_PROCESS_TERMS)
    return reduced or terms


def _facet_term_forms(term: str) -> set[str]:
    forms = {term_key(term)}
    aliases = {
        "sync": {"synchronization", "synchronize", "synchronized", "syncing"},
        "synchronization": {"sync", "synchronize", "synchronized", "syncing"},
        "synchronize": {"sync", "synchronization", "synchronized", "syncing"},
        "synchronized": {"sync", "synchronization", "synchronize", "syncing"},
        "anchoring": {"anchor", "anchored"},
        "consistency": {"consistent"},
        "deduplication": {
            "dedup", "deduplicate", "deduplicated", "duplicate", "duplicates",
            "unique", "once",
        },
        "equality": {"equal", "equals", "exact", "exactly"},
        "readiness": {"ready"},
        "reconciliation": {"reconcile", "reconciled"},
        "unproved": {"unproven", "prove", "proved", "proof"},
    }
    forms.update(aliases.get(term, ()))
    if term.endswith("ies") and len(term) > 4:
        forms.add(term[:-3] + "y")
    elif term.endswith("ing") and len(term) > 5:
        stem = term[:-3]
        forms.add(stem)
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
        forms.add(stem + "e")
    elif term.endswith("ed") and len(term) > 4:
        stem = term[:-2]
        forms.update((stem, stem + "e"))
    elif term.endswith("s") and not term.endswith("ss") and len(term) > 3:
        forms.add(term[:-1])
    else:
        forms.add(term + "s")
    return {form for form in forms if form}


def _facet_evidence_queries(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    base = _facet_evidence_terms(terms)
    queries = [base]
    term_set = set(base)
    if "verified" in term_set and term_set & {"source", "application", "applications"}:
        queries.extend((
            ("preview", "fixes"),
            ("is", "fixable"),
            ("successful", "verified", "application"),
            ("verified", "application"),
        ))
    if "rejection" in term_set and term_set & {"diagnostic", "diagnostics"}:
        queries.extend((("refactor", "rejection"), ("rejection",), ("diagnostic",)))
    if "yield" in term_set:
        queries.extend((("promotable", "candidate"), ("promotable", "candidates")))
    if term_set & {"metric", "metrics"} and term_set & {"enforce", "enforces", "enforced"}:
        queries.extend((("min",), ("max",), ("threshold",), ("evaluate",)))
    if "unsafe" in term_set and "path" in term_set:
        queries.extend((("unsafe", "path"), ("parent", "traversal"), ("rejects", "parent", "traversal")))
    if term_set & {"running", "run"} and term_set & {"loaded", "load", "cases", "case"}:
        queries.extend((("load", "run"), ("loaded", "case"), ("loads", "cases")))
    return tuple(dict.fromkeys(queries))


def _facet_matches_node(node: object, terms: tuple[str, ...]) -> bool:
    token_list = re.findall(r"[a-z0-9]+", _facet_node_text(node))
    tokens = set(token_list)
    compact = "".join(token_list)
    return any(
        all(
            tokens & (forms := _facet_term_forms(term))
            or any(len(form) >= 5 and form in compact for form in forms)
            for term in query_terms
        )
        for query_terms in _facet_evidence_queries(terms)
    )


def _facet_matched_terms(node: object, terms: tuple[str, ...]) -> set[str]:
    return _facet_matched_text_terms(_facet_node_text(node), terms)


def _facet_label_matched_terms(node: object, terms: tuple[str, ...]) -> set[str]:
    """Return facet hits from symbol identity, excluding summary/body context."""
    return _facet_matched_text_terms(
        term_key(str(getattr(node, "label", ""))),
        terms,
    )


def _facet_matched_text_terms(text: str, terms: tuple[str, ...]) -> set[str]:
    token_list = re.findall(r"[a-z0-9]+", text)
    tokens = set(token_list)
    compact = "".join(token_list)
    return {
        term
        for term in terms
        if (
            tokens & (forms := _facet_term_forms(term))
            or any(len(form) >= 5 and form in compact for form in forms)
        )
    }


def _qualified_query_symbols(query: str) -> tuple[tuple[str, str], ...]:
    return tuple(dict.fromkeys(
        (owner, member)
        for owner, member in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\b", query)
    ))


def _cargo_source_context(source: str) -> tuple[str, Path, Path] | None:
    """Return package, manifest directory, and source-relative path."""
    if not source:
        return None
    source_path = Path(source)
    if not source_path.exists():
        return None
    manifest = next(
        (parent / "Cargo.toml" for parent in (source_path.parent, *source_path.parents) if (parent / "Cargo.toml").is_file()),
        None,
    )
    if manifest is None:
        return None
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        package = str(data.get("package", {}).get("name", "")).strip()
        relative = source_path.resolve().relative_to(manifest.parent.resolve())
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return None
    if not package or not relative.parts or source_path.suffix != ".rs":
        return None
    return package, manifest.parent, relative


def _cargo_test_target(source: str) -> tuple[str, str, str] | None:
    """Return (package, integration target, optional module filter)."""
    context = _cargo_source_context(source)
    if context is None:
        return None
    package, manifest_dir, relative = context
    if relative.parts[0] != "tests":
        return None
    source_path = manifest_dir / relative
    try:
        data = tomllib.loads((manifest_dir / "Cargo.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None

    # Explicit [[test]] targets are authoritative. A consolidated harness may
    # include module files beneath the harness directory, so map descendants
    # back to that declared target and use the module stem as a Cargo filter.
    for target in data.get("test", ()):
        target_name = str(target.get("name", "")).strip()
        target_path = str(target.get("path", "")).strip()
        if not target_name or not target_path:
            continue
        harness = (manifest_dir / target_path).resolve()
        if source_path.resolve() == harness:
            return package, target_name, ""
        if harness.name in {"main.rs", "lib.rs"} and harness.parent in source_path.resolve().parents:
            return package, target_name, source_path.stem

    tests_root = manifest_dir / "tests"
    nested = relative.parts[1:]
    if len(nested) == 1:
        return package, source_path.stem, ""
    # Cargo auto-discovers tests/<target>/main.rs as one integration binary.
    for parent in (source_path.parent, *source_path.parents):
        if parent == tests_root or tests_root not in parent.parents:
            break
        if (parent / "main.rs").is_file():
            target_name = parent.relative_to(tests_root).parts[0]
            return package, target_name, "" if source_path.name == "main.rs" else source_path.stem
    return None


def _cargo_inline_rust_test_target(source: str) -> tuple[str, str, str] | None:
    """Return package, module filter, and Cargo target for an inline Rust test."""
    context = _cargo_source_context(source)
    if context is None:
        return None
    package, manifest_dir, relative = context
    if relative.parts[0] != "src":
        return None
    if (manifest_dir / "src" / "lib.rs").is_file():
        target = "--lib"
    else:
        return None
    module_parts = list(relative.parts[1:])
    filename = module_parts.pop() if module_parts else ""
    stem = Path(filename).stem
    if stem not in {"lib", "main", "mod"}:
        module_parts.append(stem)
    module_filter = "::".join((*module_parts, "tests"))
    return package, module_filter, target


def _test_command(
    path: str,
    source: str = "",
    *,
    inline_test: bool = False,
    test_label: str = "",
) -> str:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if inline_test and normalized.endswith(".rs"):
        cargo_target = _cargo_inline_rust_test_target(source)
        if cargo_target is not None:
            package, module_filter, target = cargo_target
            # The graph already carries the exact test function label. Cargo
            # accepts it as a filter regardless of whether the containing
            # module is named `tests`, `normalize_tests`, or something else.
            # Retain the module fallback only for legacy nodes without labels.
            test_filter = test_label.strip() or module_filter
            return f"cargo test -p {package} {test_filter} {target}"
    if len(parts) >= 4 and parts[0] == "crates" and "tests" in parts and normalized.endswith(".rs"):
        cargo_target = _cargo_test_target(source)
        if cargo_target is not None:
            package, target, module_filter = cargo_target
            suffix = f" {module_filter}" if module_filter else ""
            return f"cargo test -p {package} --test {target}{suffix}"
        test_name = normalized.rsplit("/", 1)[-1][:-3]
        return f"cargo test -p {parts[1]} --test {test_name}"
    if len(parts) >= 2 and parts[0] == "crates" and normalized.endswith(".rs"):
        return f"cargo test -p {parts[1]}"
    if normalized.endswith(".py"):
        return f"python -m pytest {normalized}"
    if normalized.endswith((".ts", ".tsx", ".js", ".jsx")):
        return f"npm test -- {normalized}"
    return ""


def changed_path_test_recommendations(
    graph: Graph,
    paths: tuple[str, ...],
) -> dict[str, object]:
    """Derive deterministic regression commands from explicit changed test paths."""
    normalized_paths = tuple(
        dict.fromkeys(path.replace("\\", "/").strip("/") for path in paths)
    )
    candidates: list[dict[str, object]] = []
    commands: list[str] = []
    provenance: list[dict[str, object]] = []
    for path in normalized_paths:
        path_nodes = [
            node
            for node in graph.nodes.values()
            if node.active and node.path.replace("\\", "/").strip("/") == path
        ]
        test_nodes = [node for node in path_nodes if _is_test_node(node)]
        command_tests: dict[str, list[dict[str, object]]] = {}
        for node in test_nodes:
            command = _test_command(
                path,
                node.source,
                inline_test=not _is_test_path(path),
            )
            if not command:
                continue
            candidate = {
                "id": node.id,
                "label": node.label,
                "path": path,
                "role": "changed_path_regression",
            }
            candidates.append(candidate)
            command_tests.setdefault(command, []).append(candidate)
        if not command_tests and _is_test_path(path):
            source = next(
                (node.source for node in path_nodes if node.source),
                "",
            )
            command = _test_command(path, source)
            if command:
                file_candidate = {
                    "id": next((node.id for node in path_nodes), ""),
                    "label": Path(path).name,
                    "path": path,
                    "role": "changed_path_regression",
                }
                candidates.append(file_candidate)
                command_tests[command] = [file_candidate]
        for command, tests in command_tests.items():
            if command not in commands:
                commands.append(command)
                provenance.append({
                    "command": command,
                    "role": "changed_path_regression",
                    "tests": tests,
                })
    return {
        "candidates": candidates,
        "commands": commands,
        "command_provenance": provenance,
    }


_AFFECTED_OUTPUT_TERMS = {
    "affected", "behavioral", "cargo", "command", "commands", "direct", "exact",
    "focused", "minimal", "return", "runnable", "run", "runs", "test", "tests",
    "transitive",
}


def reconcile_affected_output_facets(metadata: dict[str, object]) -> tuple[str, ...]:
    """Fulfill output-contract facets from the affected-test receipt itself."""
    coverage = metadata.get("facet_coverage")
    affected = metadata.get("affected_tests")
    if not isinstance(coverage, dict) or not isinstance(affected, dict):
        return ()
    direct = [item for item in affected.get("direct", ()) if isinstance(item, dict)]
    transitive = [item for item in affected.get("transitive", ()) if isinstance(item, dict)]
    commands = [str(item) for item in affected.get("commands", ()) if item]
    fulfilled = list(coverage.get("fulfilled", ()))
    remaining: list[str] = []
    repaired: list[str] = []
    for raw_label in coverage.get("unfulfilled", ()):
        label = str(raw_label)
        terms = set(term_key(label).split())
        if not terms or terms - _AFFECTED_OUTPUT_TERMS:
            remaining.append(label)
            continue
        evidence: list[str] = []
        if "direct" in terms and direct:
            evidence = [f"affected_tests.direct:{item.get('id', '')}" for item in direct[:5]]
        elif "transitive" in terms and transitive:
            evidence = [f"affected_tests.transitive:{item.get('id', '')}" for item in transitive[:5]]
        elif terms & {"cargo", "command", "commands", "runnable", "run", "runs"} and commands:
            evidence = [f"affected_tests.command:{command}" for command in commands[:5]]
        elif terms & {"affected", "behavioral", "test", "tests"} and (direct or transitive):
            evidence = [
                f"affected_tests.test:{item.get('id', '')}"
                for item in (*direct, *transitive)[:5]
            ]
        if evidence:
            fulfilled.append({
                "facet": label,
                "evidence": evidence,
                "source": "affected_tests_receipt",
            })
            repaired.append(label)
        else:
            remaining.append(label)
    total = len(fulfilled) + len(remaining)
    coverage.update({
        "fulfilled": fulfilled,
        "unfulfilled": remaining,
        "coverage_ratio": round(len(fulfilled) / max(1, total), 4),
        "warning": "unfulfilled query facets" if remaining else "",
    })
    return tuple(repaired)


def affected_test_recommendations(graph: Graph, starts: tuple[str, ...], selected_nodes: set[str]) -> dict[str, object]:
    incoming: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        if edge.active and edge.type in {"calls", "references", "tests"}:
            incoming.setdefault(edge.target, []).append(edge)
    distances = {start: 0 for start in starts}
    covered_starts: dict[str, set[str]] = {start: {start} for start in starts}
    evidence_by_node: dict[str, list[Edge]] = {}
    paths_by_node: dict[str, dict[str, tuple[tuple[str, ...], tuple[Edge, ...]]]] = {}
    # Track each requested anchor independently. A merged frontier makes
    # coverage order-dependent when one anchor is itself upstream of another:
    # whichever set element is visited first can miss the later-propagated
    # anchor. The product is bounded by <=12 starts and two hops.
    for start in starts:
        owned_edges = [
            edge
            for edge in graph.edges
            if edge.active
            and edge.type == "contains"
            and edge.source == start
            and edge.target in graph.nodes
        ]
        owned_targets = {
            node_id
            for node_id, node in graph.nodes.items()
            if node.active and node.parent == start
        } | {edge.target for edge in owned_edges}
        frontier = {start, *owned_targets}
        seen = set(frontier)
        root_paths: dict[str, tuple[tuple[str, ...], tuple[Edge, ...]]] = {
            start: ((start,), ())
        }
        for target in owned_targets:
            containment = next(
                (edge for edge in owned_edges if edge.target == target),
                None,
            )
            root_paths[target] = (
                (target, start),
                (containment,) if containment is not None else (),
            )
        for distance in (1, 2):
            next_frontier: set[str] = set()
            for target in frontier:
                for edge in incoming.get(target, ()):
                    covered_starts.setdefault(edge.source, set()).add(start)
                    if edge not in evidence_by_node.setdefault(edge.source, []):
                        evidence_by_node[edge.source].append(edge)
                    distances[edge.source] = min(distance, distances.get(edge.source, distance))
                    target_nodes, target_edges = root_paths[target]
                    candidate_path = ((edge.source, *target_nodes), (edge, *target_edges))
                    prior_path = root_paths.get(edge.source)
                    if prior_path is None or len(candidate_path[1]) < len(prior_path[1]):
                        root_paths[edge.source] = candidate_path
                        paths_by_node.setdefault(edge.source, {})[start] = candidate_path
                    if edge.source not in seen:
                        seen.add(edge.source)
                        next_frontier.add(edge.source)
            frontier = next_frontier
    direct: list[dict[str, object]] = []
    transitive: list[dict[str, object]] = []
    for node_id, distance in sorted(distances.items(), key=lambda item: (item[1], item[0])):
        node = graph.nodes.get(node_id)
        if distance == 0 or node is None or not _is_test_node(node):
            continue
        evidence_edges = evidence_by_node.get(node_id, ())
        item = {
            "id": node.id,
            "label": node.label,
            "path": node.path,
            "distance": distance,
            "in_packet": node_id in selected_nodes,
            "evidence": [
                {
                    "type": edge.type,
                    "confidence": edge.confidence,
                    "provenance": edge.provenance,
                }
                for edge in evidence_edges[:3]
            ],
            "covers": [
                {"id": start, "label": graph.nodes[start].label}
                for start in sorted(covered_starts.get(node_id, ()))
                if start in graph.nodes
            ],
            "root_paths": [
                {
                    "root": {"id": start, "label": graph.nodes[start].label},
                    "nodes": [
                        {"id": path_node, "label": graph.nodes[path_node].label}
                        for path_node in path_nodes
                        if path_node in graph.nodes
                    ],
                    "edges": [
                        {
                            "source": edge.source,
                            "target": edge.target,
                            "type": edge.type,
                            "confidence": edge.confidence,
                            "provenance": edge.provenance,
                        }
                        for edge in path_edges
                    ],
                }
                for start, (path_nodes, path_edges) in sorted(paths_by_node.get(node_id, {}).items())
                if start in graph.nodes
            ],
        }
        (direct if distance == 1 else transitive).append(item)
    def recommendation_rank(item: dict[str, object]) -> tuple[object, ...]:
        evidence = item.get("evidence", [])
        max_confidence = max(
            (float(edge.get("confidence", 0.0)) for edge in evidence if isinstance(edge, dict)),
            default=0.0,
        )
        return (
            -len(item.get("covers", [])),
            -max_confidence,
            str(item.get("path", "")),
            str(item.get("label", "")),
        )

    direct.sort(key=recommendation_rank)
    transitive.sort(key=recommendation_rank)
    omitted_direct = max(0, len(direct) - 12)
    omitted_transitive = max(0, len(transitive) - 12)
    direct = direct[:12]
    transitive = transitive[:12]

    def commands_for(items: list[dict[str, object]]) -> list[str]:
        return list(dict.fromkeys(
            command
            for item in items
            if (
                command := _test_command(
                    str(item["path"]),
                    graph.nodes[str(item["id"])].source,
                    inline_test=not _is_test_path(str(item["path"])),
                    test_label=str(item.get("label", "")),
                )
            )
        ))

    direct_commands = commands_for(direct)
    transitive_commands = commands_for(transitive)
    all_items = [*direct, *transitive]
    candidate_command_provenance = [
        {
            "command": command,
            "tests": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "root_paths": item["root_paths"],
                }
                for item in all_items
                if _test_command(
                    str(item["path"]),
                    graph.nodes[str(item["id"])].source,
                    inline_test=not _is_test_path(str(item["path"])),
                    test_label=str(item.get("label", "")),
                ) == command
            ],
        }
        for command in dict.fromkeys((*direct_commands, *transitive_commands))
    ]
    root_ids = set(starts)
    uncovered = set(root_ids)
    command_budget = max(1, math.ceil(math.log2(len(root_ids) + 1)))
    selected_command_provenance: list[dict[str, object]] = []
    remaining = list(candidate_command_provenance)
    while remaining and uncovered and len(selected_command_provenance) < command_budget:
        ranked = sorted(
            enumerate(remaining),
            key=lambda pair: (
                -len(
                    {
                        str(path.get("root", {}).get("id", ""))
                        for test in pair[1].get("tests", [])
                        for path in test.get("root_paths", [])
                    }
                    & uncovered
                ),
                pair[0],
            ),
        )
        index, winner = ranked[0]
        covered = {
            str(path.get("root", {}).get("id", ""))
            for test in winner.get("tests", [])
            for path in test.get("root_paths", [])
        } & uncovered
        if not covered:
            break
        selected_command_provenance.append(winner)
        uncovered -= covered
        remaining.pop(index)
    if not selected_command_provenance and candidate_command_provenance:
        selected_command_provenance.append(candidate_command_provenance[0])
        uncovered -= {
            str(path.get("root", {}).get("id", ""))
            for test in candidate_command_provenance[0].get("tests", [])
            for path in test.get("root_paths", [])
        }
    selected_commands = [
        str(entry["command"])
        for entry in selected_command_provenance
    ]
    return {
        "direct": direct,
        "transitive": transitive,
        "commands": selected_commands,
        "commands_by_role": {
            "direct_behavior_or_contract": [
                command for command in selected_commands if command in direct_commands
            ],
            "transitive_regression": [
                command for command in selected_commands if command in transitive_commands
            ],
        },
        "command_provenance": selected_command_provenance,
        "command_selection": {
            "algorithm": "greedy_root_cover_v1",
            "candidate_count": len(candidate_command_provenance),
            "selected_count": len(selected_commands),
            "root_count": len(root_ids),
            "covered_roots": sorted(root_ids - uncovered),
            "uncovered_roots": sorted(uncovered),
        },
        "omitted_direct": omitted_direct,
        "omitted_transitive": omitted_transitive,
    }


def reconcile_semantic_retrieval_receipt(
    graph: Graph,
    result: RetrievalResult,
    *,
    route: object,
    automatic_route: bool,
) -> tuple[str, ...]:
    """Type-check and calibrate the agent-facing retrieval receipt."""
    metadata = result.metadata
    answerability = dict(metadata.get("answerability", {}))
    status = str(answerability.get("status", "unknown"))
    abstained = bool(answerability.get("abstained", False))
    original_reason = str(answerability.get("reason", "")).strip()
    repaired_facets = reconcile_affected_output_facets(metadata)
    reasons = [original_reason]

    facet_coverage = metadata.get("facet_coverage", {})
    structural_coverage = metadata.get("structural_facet_coverage", {})
    unfulfilled = [
        *(
            str(item)
            for item in (
                facet_coverage.get("unfulfilled", ())
                if isinstance(facet_coverage, dict)
                else ()
            )
        ),
        *(
            str(item)
            for item in (
                structural_coverage.get("unfulfilled", ())
                if isinstance(structural_coverage, dict)
                else ()
            )
        ),
    ]
    if (
        repaired_facets
        and not unfulfilled
        and status == "incomplete"
        and original_reason == "unfulfilled query facets"
    ):
        status = "answerable"
        abstained = False
        reasons = []
    if unfulfilled:
        if status != "unanswerable":
            status = "incomplete"
        abstained = True
        reasons.append("unfulfilled requested facets: " + ", ".join(dict.fromkeys(unfulfilled)))

    query_class = str(getattr(route, "query_class", ""))
    route_confidence = float(getattr(route, "confidence", 1.0))
    if automatic_route and route_confidence < 0.25:
        status = "incomplete"
        abstained = True
        reasons.append(f"automatic routing confidence is low ({route_confidence:.3f})")
        metadata["routing_recovery"] = {
            "strategy": "calibrated_abstention",
            "confidence": route_confidence,
            "suggestions": [
                "add an exact symbol or path",
                f"retry with an explicit query_class instead of {query_class or 'auto'}",
                "split compound requests into one bounded facet per query",
            ],
        }

    affected = metadata.get("affected_tests")
    if query_class == "affected_tests" and isinstance(affected, dict):
        recommendations = [
            *affected.get("direct", ()),
            *affected.get("transitive", ()),
        ]
        commands = [str(item) for item in affected.get("commands", ())]
        affected["evidence_status"] = (
            "attributed"
            if recommendations
            else ("candidate_only" if commands else "no_evidence")
        )
        if not recommendations:
            status = "incomplete"
            abstained = True
            reasons.append("no affected-test evidence was found")
        omitted_direct = int(affected.get("omitted_direct", 0) or 0)
        omitted_transitive = int(affected.get("omitted_transitive", 0) or 0)
        if omitted_direct or omitted_transitive:
            status = "incomplete"
            abstained = True
            reasons.append(
                "affected-test recommendation cap omitted "
                f"{omitted_direct} direct and {omitted_transitive} transitive candidate(s)"
            )

    quality = metadata.get("quality", {})
    document_warning = str(quality.get("document_warning", "")) if isinstance(quality, dict) else ""
    if document_warning:
        if status != "unanswerable":
            status = "incomplete"
        abstained = True
        reasons.append(document_warning)

    answerability = {
        "status": status,
        "abstained": abstained,
        "reason": "; ".join(dict.fromkeys(reason for reason in reasons if reason)),
    }
    metadata["answerability"] = answerability

    errors: list[str] = []
    if status == "answerable" and unfulfilled:
        errors.append("answerable receipt has unfulfilled facets")
    if status in {"incomplete", "unanswerable"} and not abstained:
        errors.append(f"{status} receipt must set abstained=true")
    if document_warning and status == "answerable":
        errors.append("document warning cannot coexist with answerable status")

    if query_class == "affected_tests" and isinstance(affected, dict):
        recommended_ids = {
            str(item.get("id"))
            for role in ("direct", "transitive")
            for item in affected.get(role, ())
            if isinstance(item, dict) and item.get("id")
        }
        packet_direct_tests = {
            edge.source
            for edge in graph.edges
            if edge.active
            and edge.type in {"calls", "references", "tests"}
            and edge.source in result.nodes
            and edge.target in result.starts
            and edge.source in graph.nodes
            and _is_test_node(graph.nodes[edge.source])
        }
        missing = sorted(packet_direct_tests - recommended_ids)
        if missing:
            errors.append(
                "packet contains direct test evidence omitted from affected_tests: "
                + ", ".join(missing)
            )
        commands = [str(item) for item in affected.get("commands", ())]
        if commands and not recommended_ids:
            errors.append(
                "affected-test commands were emitted without attributed direct or "
                "transitive test evidence"
            )
        provenance_commands = {
            str(item.get("command"))
            for item in affected.get("command_provenance", ())
            if isinstance(item, dict) and item.get("command")
        }
        missing_provenance = sorted(set(commands) - provenance_commands)
        if missing_provenance:
            errors.append(
                "affected-test commands lack provenance: " + ", ".join(missing_provenance)
            )
        remaining_output_facets: list[str] = []
        for raw_label in (
            facet_coverage.get("unfulfilled", ())
            if isinstance(facet_coverage, dict)
            else ()
        ):
            label = str(raw_label)
            terms = set(term_key(label).split())
            if not terms or terms - _AFFECTED_OUTPUT_TERMS:
                continue
            contradicted = (
                ("direct" in terms and bool(affected.get("direct")))
                or ("transitive" in terms and bool(affected.get("transitive")))
                or (
                    bool(terms & {"cargo", "command", "commands", "runnable", "run", "runs"})
                    and bool(commands)
                )
                or (
                    bool(terms & {"affected", "behavioral", "test", "tests"})
                    and bool(recommended_ids)
                )
            )
            if contradicted:
                remaining_output_facets.append(label)
        if remaining_output_facets:
            errors.append(
                "affected-test evidence contradicts unfulfilled output facets: "
                + ", ".join(remaining_output_facets)
            )

    metadata["semantic_validation"] = {
        "ok": not errors,
        "status": "semantic_pass" if not errors else "semantic_fail",
        "scope": "packet_receipt_consistency",
        "evidence_status": (
            affected.get("evidence_status")
            if query_class == "affected_tests" and isinstance(affected, dict)
            else "not_applicable"
        ),
        "errors": errors,
    }
    return tuple(errors)


# Compatibility name for callers that adopted the first public spelling.
reconcile_retrieval_receipt = reconcile_semantic_retrieval_receipt


def reserve_affected_test_evidence(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    plan: ContextPlan,
    *,
    direct_limit: int = 8,
) -> tuple[set[str], list[Edge]]:
    """Keep strongest direct test assertions in the rendered packet."""
    recommendations = affected_test_recommendations(graph, starts, nodes)
    direct_ids = [
        str(item["id"])
        for item in recommendations["direct"][:direct_limit]
        if str(item["id"]) in graph.nodes
    ]
    if not direct_ids:
        return nodes, edges

    secondary_ids = {
        str(item["id"])
        for item in recommendations["transitive"][:6]
        if str(item["id"]) in graph.nodes
    }
    retained_tests = set(direct_ids) | secondary_ids | set(starts)
    out_nodes = {
        node_id
        for node_id in nodes
        if not _is_test_node(graph.nodes[node_id]) or node_id in retained_tests
    }
    protected = set(starts) | set(direct_ids)
    for node_id in direct_ids:
        if node_id in out_nodes:
            continue
        if plan.node_budget is not None and len(out_nodes) >= plan.node_budget:
            removable = _least_valuable_context_node(graph, out_nodes, protected=protected)
            if removable is None:
                continue
            out_nodes.remove(removable)
        out_nodes.add(node_id)

    edge_by_key = {
        (edge.source, edge.target, edge.type): edge
        for edge in edges
        if edge.source in out_nodes and edge.target in out_nodes
    }
    direct_set = set(direct_ids)
    for edge in graph.edges:
        if not edge.active or edge.source not in direct_set:
            continue
        if edge.target not in out_nodes or edge.type not in {"calls", "references", "tests"}:
            continue
        edge_by_key.setdefault((edge.source, edge.target, edge.type), edge)
    return out_nodes, list(edge_by_key.values())


def apply_shape_budget(graph: Graph, plan: ContextPlan, query: str) -> ContextPlan:
    recommendation = recommend_node_budget(plan.query_class, query, profile_graph_shape(graph))
    recommended_budget = recommendation.recommended_budget
    if recommended_budget == plan.node_budget:
        return plan
    return replace(
        plan,
        node_budget=recommended_budget,
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

    identifiers = explicit_query_identifiers(query)
    if len(identifiers) >= 2 and plan.query_class in STRUCTURAL_QUERY_CLASSES:
        return min(limit, max(len(identifiers), min(8, len(identifiers) * 2)))

    if top.node.kind in {"concept", "section"}:
        return min(limit, 2)

    if plan.query_class == "subsystem_summary":
        # Summary queries often contain several implementation nouns. The old
        # term_count*3 default could turn each loose lexical hit into a start,
        # mixing unrelated same-word functions before traversal even began.
        # Let the score distribution choose a small evidence set instead.
        threshold_count = sum(
            1 for match in matches[: min(12, len(matches))]
            if top.score > 0 and match.score / top.score >= 0.55
        )
        shaped = max(2, min(6, threshold_count))
        if _is_high_confidence_exact_anchor(top):
            shaped = min(shaped, 3)
        return min(limit, shaped)

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


def _is_targeted_symbol_anchor(match: Match) -> bool:
    if match.node.kind not in {"function", "method", "class", "struct", "trait", "enum", "field"}:
        return False
    return _is_high_confidence_exact_anchor(match) or any(
        reason.startswith(("id:", "label_exact:")) or reason == "basename_stem_exact"
        for reason in match.reasons
    )


def select_anchor_matches(
    matches: tuple[Match, ...],
    anchor_limit: int,
    query_class: str,
    doc_intent: bool = False,
    query: str = "",
    graph: Graph | None = None,
    dominant_scope: str = "",
) -> tuple[Match, ...]:
    # Preserve explicit multi-entity intent before generic score ordering.
    # Reserve up to two exact matches per snake_case identifier (declaration
    # and implementation commonly share a label) and one per CamelCase type.
    explicit = explicit_query_identifiers(query)
    qualified = _qualified_query_symbols(query)
    resolved_qualified_owners: set[str] = set()
    if explicit or qualified:
        reserved: list[Match] = []
        seen_reserved: set[str] = set()
        for owner, member in qualified:
            owner_key = term_key(owner)
            candidate = next(
                (
                    match for match in matches
                    if match.node.id not in seen_reserved
                    and match.node.label.casefold() == member.casefold()
                    and owner_key in _facet_node_text(match.node)
                ),
                None,
            )
            if candidate is None and graph is not None:
                # Exact qualified symbols are stronger than a bounded lexical
                # candidate list. Same-named methods can otherwise be crowded
                # out by fields and the owner type before selection runs.
                node = next(
                    (
                        node for node in graph.nodes.values()
                        if node.label.casefold() == member.casefold()
                        and owner_key in _facet_node_text(node)
                    ),
                    None,
                )
                if node is not None:
                    candidate = Match(
                        node=node,
                        score=(matches[0].score if matches else 0.0) + 40.0,
                        reasons=(f"qualified_exact:{owner}::{member}",),
                    )
            if candidate is not None:
                reserved.append(candidate)
                seen_reserved.add(candidate.node.id)
                resolved_qualified_owners.add(owner.casefold())
        for identifier in explicit:
            # Once Type::member resolved exactly, the owner type is redundant.
            # Reserving it would let a two-hop traversal fan through the source
            # file's contains edges and pull unrelated sibling definitions.
            if identifier.casefold() in resolved_qualified_owners:
                continue
            per_identifier = 2 if "_" in identifier else 1
            found = 0
            for match in matches:
                if match.node.label.casefold() != identifier or match.node.id in seen_reserved:
                    continue
                reserved.append(match)
                seen_reserved.add(match.node.id)
                found += 1
                if len(reserved) >= anchor_limit or found >= per_identifier:
                    break
            if len(reserved) >= anchor_limit:
                return tuple(reserved)
        if reserved:
            matches = tuple(reserved + [match for match in matches if match.node.id not in seen_reserved])
    if query_class == "subsystem_summary" and _FLOW_ORIENTATION_QUERY.search(query):
        # Compile architecture-flow prose to executable/type roots. A prose
        # paragraph or test name can repeat the whole question verbatim, but
        # production symbols are the nodes whose typed edges prove the flow.
        production_kinds = {
            "function", "method", "class", "struct", "trait", "enum",
            "python", "rust", "javascript", "typescript", "go", "java",
            "c", "cpp", "csharp", "ruby", "php", "kotlin", "scala", "swift",
        }
        production = [
            match
            for match in matches
            if match.node.kind in production_kinds
            and match.node.kind not in NON_STRUCTURAL_KINDS
            and not _is_test_node(match.node)
        ]
        if production:
            return tuple(production[:anchor_limit])
    if doc_intent:
        doc_matches = [match for match in matches if match.node.kind in NON_STRUCTURAL_KINDS]
        if doc_matches:
            selected: list[Match] = []
            seen: set[str] = set()
            seen_content: set[str] = set()
            candidates = doc_matches if query_class == "doc_summary" else doc_matches + list(matches)
            for match in candidates:
                if match.node.id in seen:
                    continue
                content_key = _document_content_key(match.node)
                if content_key and content_key in seen_content:
                    continue
                selected.append(match)
                seen.add(match.node.id)
                if content_key:
                    seen_content.add(content_key)
                if len(selected) >= anchor_limit:
                    return tuple(selected)
            return tuple(selected)
    if query_class == "affected_tests":
        implementation = [
            match for match in matches
            if not _is_test_node(match.node)
            and match.node.kind not in NON_STRUCTURAL_KINDS
            and not _unrequested_identifier_sibling(match.node.label, explicit)
        ]
        if implementation:
            selected = [
                match
                for match in implementation
                if "exact_changed_path" in match.reasons
            ][:anchor_limit]
            seen = {match.node.id for match in selected}
            adjacency: dict[str, set[str]] = {}
            if graph is not None:
                for edge in graph.edges:
                    if not edge.active or edge.type not in STRUCTURAL_RELATIONS:
                        continue
                    adjacency.setdefault(edge.source, set()).add(edge.target)
                    adjacency.setdefault(edge.target, set()).add(edge.source)
            for identifier in explicit:
                if identifier.casefold() in resolved_qualified_owners:
                    continue
                for match in implementation:
                    if match.node.id not in seen and match.node.label.casefold() == identifier:
                        selected.append(match)
                        seen.add(match.node.id)
                        break
            for _label, terms in query_facets(query):
                candidates = [
                    match for match in implementation
                    if match.node.id not in seen
                    and _facet_matches_node(match.node, terms)
                ]
                selected_ids = {match.node.id for match in selected}
                selected_term_sets = [_symbol_identity_terms(match.node) for match in selected]

                def anchor_coherence(match: Match) -> float:
                    candidate_terms = _symbol_identity_terms(match.node)
                    return max(
                        (
                            len(candidate_terms & anchor_terms)
                            / math.sqrt(max(1, len(candidate_terms) * len(anchor_terms)))
                            for anchor_terms in selected_term_sets
                        ),
                        default=0.0,
                    )

                candidate = max(
                    candidates,
                    key=lambda match: (
                        any(node_id in adjacency.get(match.node.id, ()) for node_id in selected_ids),
                        anchor_coherence(match),
                        bool(dominant_scope and _path_in_scopes(match.node.path, (dominant_scope,))),
                        match.node.kind in {"struct", "class", "trait", "enum"},
                        match.node.kind in {"function", "method"},
                        match.score,
                        match.node.id,
                    ),
                    default=None,
                )
                if candidate is not None:
                    selected.append(candidate)
                    seen.add(candidate.node.id)
                if len(selected) >= anchor_limit:
                    return tuple(selected)
            if qualified and selected:
                return tuple(selected)
            for match in implementation:
                if match.node.id not in seen:
                    selected.append(match)
                    seen.add(match.node.id)
                if len(selected) >= anchor_limit:
                    break
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


def select_enumerated_doc_roots(
    selected: tuple[Match, ...],
    candidates: tuple[Match, ...],
    *,
    query: str,
    query_class: str,
) -> tuple[Match, ...]:
    """Compile list-shaped document questions to one document root per path.

    Paragraphs repeat the query vocabulary and can consume every anchor slot.
    An enumeration is lower-level as ``document -> ordered section siblings``:
    root the document once, then let ``reserve_ordered_doc_siblings`` spend the
    node budget on the requested stages/phases/steps.
    """
    if (
        query_class != "doc_summary"
        or not _ORDERED_DOC_QUERY.search(query)
        or not _ENUMERATED_DOC_QUERY.search(query)
    ):
        return selected

    limit = max(1, len(selected))
    document_kinds = {"file", "markdown", "rst", "html", "text"}
    roots: list[Match] = []
    seen_paths: set[str] = set()
    for match in candidates:
        path = match.node.path.replace("\\", "/").strip("/")
        if (
            not path
            or path in seen_paths
            or match.node.kind not in document_kinds
        ):
            continue
        roots.append(match)
        seen_paths.add(path)
        if len(roots) >= limit:
            return tuple(roots)
    if roots:
        return tuple(roots)

    # Graphs produced by external frontends may have sections but no file node.
    # Keep one strongest section/paragraph root per document path.
    for match in selected:
        path = match.node.path.replace("\\", "/").strip("/")
        if not path or path in seen_paths:
            continue
        roots.append(match)
        seen_paths.add(path)
        if len(roots) >= limit:
            break
    return tuple(roots) or selected


def _document_content_key(node: object) -> str:
    facts = " ".join(getattr(node, "facts", ()) or ())
    normalized = term_key(facts)
    if len(normalized) < 24:
        return ""
    return f"{getattr(node, 'kind', '')}:{normalized}"


def _unrequested_identifier_sibling(label: str, explicit: tuple[str, ...]) -> bool:
    folded = label.casefold()
    if folded in explicit or "_" not in folded:
        return False
    parts = set(part for part in folded.split("_") if len(part) >= 2)
    for identifier in explicit:
        other = set(part for part in identifier.split("_") if len(part) >= 2)
        if len(other) < 3:
            continue
        overlap = len(parts & other) / max(1, min(len(parts), len(other)))
        if overlap >= 0.75 and parts != other:
            return True
    return False


def reserve_reverse_contract_starts(
    graph: Graph,
    starts: tuple[str, ...],
    *,
    query: str = "",
) -> tuple[str, ...]:
    """Promote both sides of a named contract before one-hop reverse lookup.

    A trait's implementor is one hop away and tests importing that implementor
    are another. Promote implementors when the requested root is the contract;
    do not promote a concrete type's trait, which would fan back out through
    every sibling implementor.
    """
    out = list(starts)
    seen = set(starts)
    initial = set(starts)
    for edge in graph.edges:
        if not edge.active or edge.type != "implements":
            continue
        counterpart = None
        if edge.target in initial:
            counterpart = edge.source
        if counterpart and counterpart in graph.nodes and counterpart not in seen:
            out.append(counterpart)
            seen.add(counterpart)
        if len(out) >= 12:
            break
    consumer_query = bool(
        re.search(
            r"\b(?:test|tests)\b.{0,40}\b"
            r"(?:uses?|consumes?|calls?|exercises?|verifies?)\b",
            query,
            re.I,
        )
    )
    if consumer_query:
        explicit = set(explicit_query_identifiers(query))
        exact_parents = {
            node_id
            for node_id in out
            if node_id in graph.nodes
            and "".join(term_key(graph.nodes[node_id].label).split()) in explicit
        }
        parent_ids = exact_parents or set(out)
        members = [
            graph.nodes[edge.target]
            for edge in graph.edges
            if edge.active
            and edge.type in {"defines", "contains"}
            and edge.source in parent_ids
            and edge.target in graph.nodes
            and graph.nodes[edge.target].kind in {"method", "function", "field"}
        ]
        members.extend(
            node
            for node in graph.nodes.values()
            if node.parent in parent_ids
            and node.kind in {"method", "function", "field"}
            and node not in members
        )
        members.sort(
            key=lambda node: (
                0
                if node.label.casefold()
                in {"check", "enforce", "evaluate", "examine", "validate", "verify"}
                else 1,
                0 if node.kind == "field" else 1,
                node.label,
            )
        )
        for node in members:
            if node.id not in seen:
                out.append(node.id)
                seen.add(node.id)
            if len(out) >= 12:
                break
    return tuple(out)


def prune_concrete_contract_siblings(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    *,
    roots: tuple[str, ...],
) -> tuple[set[str], list[Edge]]:
    """Do not turn a concrete-type reverse lookup into all trait implementors."""
    root_set = {
        node_id
        for node_id in roots
        if node_id in graph.nodes
        and graph.nodes[node_id].kind not in {"interface", "trait"}
    }
    contract_ids = {
        edge.target
        for edge in graph.edges
        if edge.active
        and edge.type == "implements"
        and edge.source in root_set
        and edge.target not in root_set
    }
    if not contract_ids:
        return nodes, edges
    siblings = {
        edge.source
        for edge in graph.edges
        if edge.active
        and edge.type == "implements"
        and edge.target in contract_ids
        and edge.source not in root_set
    }
    if not siblings:
        return nodes, edges
    kept = nodes - siblings
    return kept, [
        edge
        for edge in edges
        if edge.source in kept and edge.target in kept
    ]


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


def reserve_ordered_doc_siblings(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    query: str,
    plan: ContextPlan,
) -> tuple[set[str], list[Edge]]:
    """Keep adjacent roadmap/phase sections needed for ordering questions."""
    if plan.query_class != "doc_summary" or not _ORDERED_DOC_QUERY.search(query):
        return nodes, edges
    out_nodes = set(nodes)
    protected = set(starts)
    for start in starts:
        anchor = graph.nodes.get(start)
        if anchor is None or not anchor.path:
            continue
        siblings = sorted(
            (
                node_id for node_id, node in graph.nodes.items()
                if node.active and node.kind == "section" and node.path == anchor.path
            ),
            key=lambda node_id: (graph.nodes[node_id].line or 10**9, graph.nodes[node_id].label, node_id),
        )
        enumerated = bool(_ENUMERATED_DOC_QUERY.search(query))
        if enumerated:
            terms = set(plan_terms(query))
            if terms & {"stage", "stages"}:
                siblings = [
                    node_id
                    for node_id in siblings
                    if re.search(r"\bstage\s+\d+\b", graph.nodes[node_id].label, re.I)
                ]
            elif terms & {"phase", "phases"}:
                siblings = [
                    node_id
                    for node_id in siblings
                    if re.search(r"\bphase\s+\d+\b", graph.nodes[node_id].label, re.I)
                ]
            elif terms & {"step", "steps"}:
                siblings = [
                    node_id
                    for node_id in siblings
                    if re.search(r"\bstep\s+\d+\b", graph.nodes[node_id].label, re.I)
                ]
            candidates = siblings
        elif anchor.kind != "section":
            continue
        else:
            try:
                index = siblings.index(start)
            except ValueError:
                continue
            candidates = []
            if index > 0:
                candidates.append(siblings[index - 1])
            if index + 1 < len(siblings):
                candidates.append(siblings[index + 1])
        for node_id in candidates:
            if plan.node_budget is not None and len(out_nodes) >= plan.node_budget:
                removable = _least_valuable_context_node(graph, out_nodes, protected=protected | {node_id})
                if removable is None:
                    continue
                out_nodes.remove(removable)
            out_nodes.add(node_id)
            protected.add(node_id)

    out_edges = [edge for edge in edges if edge.source in out_nodes and edge.target in out_nodes]
    seen = {(edge.source, edge.target, edge.type) for edge in out_edges}
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.type)
        if key in seen or not edge.active:
            continue
        if edge.type == "section_of" and edge.source in protected and edge.target in out_nodes:
            out_edges.append(edge)
            seen.add(key)
    return out_nodes, out_edges


def prune_unexplained_structural_nodes(
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
) -> tuple[set[str], list[Edge]]:
    """Structural packets keep anchors and edge endpoints, never lexical orphans."""
    explained = set(starts)
    for edge in edges:
        explained.add(edge.source)
        explained.add(edge.target)
    kept = nodes & explained
    return kept, [edge for edge in edges if edge.source in kept and edge.target in kept]


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
