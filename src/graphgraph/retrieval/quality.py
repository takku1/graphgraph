"""Packet quality metadata and query/topology trust scoring."""

from __future__ import annotations

import math

from ..concepts import (
    concept_link_health,
)
from ..graph.core import Edge, Graph
from ..graph.ontology import provenance_confidence
from .scoping import (
    NON_STRUCTURAL_KINDS,
    _path_in_scopes,
)


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
    concept_health = concept_link_health(concept_eligible, concept_linked)
    semantic_support = {
        **concept_health,
        "linked_nodes": concept_linked,
        "eligible_nodes": concept_eligible,
        "links": int(graph.metadata.get("source_concepts_links", "0") or 0),
        "typed_fact_links": int(graph.metadata.get("source_concepts_typed_fact_links", "0") or 0),
        "exact_alias_links": int(graph.metadata.get("source_concepts_exact_alias_links", "0") or 0),
        "linked_concepts": int(graph.metadata.get("source_concepts_linked_concepts", "0") or 0),
        "scope": graph.metadata.get("source_concepts_scope", "unavailable"),
        "retrieval_mode": (
            "lexical_document_fallback"
            if query_class == "doc_summary" and not concept_health["supported"]
            else "lexical_structural_fallback"
            if query_class == "subsystem_summary" and not concept_health["supported"]
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
