"""Node-value scoring helpers used when pruning low-value context nodes."""

from __future__ import annotations

from ..graph.core import Edge, Graph
from ..graph.ontology import provenance_confidence
from .scoping import (
    NON_STRUCTURAL_KINDS,
)


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
