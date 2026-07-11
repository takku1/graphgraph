from __future__ import annotations

import math

from ..graph.core import Edge, Graph
from ..graph.ontology import is_weak_relation
from .shape import recommend_facts_per_node
from .token_cost import PACKET_TOKEN_SURFACE, estimate_surface_tokens
from .types import SubgraphStats


def compute_subgraph_stats(graph: Graph, nodes: set[str], edges: list[Edge]) -> SubgraphStats:
    node_count = len(nodes)
    edge_count = len(edges)
    relation_counts: dict[str, int] = {}
    weak_edges = 0
    for edge in edges:
        relation_counts[edge.type] = relation_counts.get(edge.type, 0) + 1
        if is_weak_relation(edge.type):
            weak_edges += 1

    factful_nodes = 0
    fact_token_proxy = 0
    facts_per_node = recommend_facts_per_node(node_count)
    for node_id in nodes:
        node = graph.nodes.get(node_id)
        if not node:
            continue
        if node.summary or node.facts:
            factful_nodes += 1
        fact_token_proxy += max(0, len(node.summary) // 4)
        fact_token_proxy += sum(max(1, len(fact) // 4) for fact in node.facts[:facts_per_node])

    total_label_len = 0
    for node_id in nodes:
        node = graph.nodes.get(node_id)
        if node:
            total_label_len += len(node.label)
    avg_label_len = total_label_len / max(1, node_count)

    relation_entropy = 0.0
    if edge_count and len(relation_counts) > 1:
        relation_entropy = -sum(
            (count / edge_count) * math.log(count / edge_count)
            for count in relation_counts.values()
        ) / math.log(len(relation_counts))

    return SubgraphStats(
        nodes=node_count,
        edges=edge_count,
        density=edge_count / max(1, node_count),
        factful_node_ratio=factful_nodes / max(1, node_count),
        relation_entropy=relation_entropy,
        weak_edge_ratio=weak_edges / max(1, edge_count),
        estimated_tokens_by_packet=estimate_packet_tokens(node_count, edge_count, avg_label_len, fact_token_proxy),
    )


def estimate_packet_tokens(nodes: int, edges: int, avg_label_len: float = 10.0, fact_token_proxy: int = 0) -> dict[str, int]:
    """Fast packet token proxy used for planning, not reporting.

    ``avg_label_len`` is accepted for API compatibility and future calibration,
    but the current measured surface is intentionally node/edge based because
    it preserved packet-winner decisions on the saved real-project rows.
    """
    estimates: dict[str, int] = {}
    for packet in PACKET_TOKEN_SURFACE:
        estimate = estimate_surface_tokens(packet, nodes, edges)
        if packet == "gg_max_hybrid":
            estimate += fact_token_proxy
        estimates[packet] = estimate
    return estimates
