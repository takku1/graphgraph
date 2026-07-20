"""Reverse-lookup, sibling, and contract-start reservations on the packet keep-set."""

from __future__ import annotations

import re

from ..concepts.terms import term_key
from ..graph.core import Edge, Graph
from ..graph.ontology import provenance_confidence
from ..graph.traversal import (
    relation_rank,
    traversal_policy,
)
from ..planning import ContextPlan
from ..planning.budgets import explicit_query_identifiers, plan_terms
from .pruning import (
    _least_valuable_context_node,
    _loose_term_hits,
)
from .scoping import (
    _ENUMERATED_DOC_QUERY,
    _ORDERED_DOC_QUERY,
    NON_STRUCTURAL_KINDS,
    _path_in_scopes,
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
