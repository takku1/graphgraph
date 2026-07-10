from __future__ import annotations

from ..graph.core import Edge, Graph
from .shape import recommend_facts_per_node
from .types import SubgraphStats

WEAK_RELATIONS = {"references", "links", "mentions", "discusses", "section_of"}

# Calibrated by benchmarks/context_graph/planner_fit_benchmark.py on the saved
# real-project packet balance rows. These are planning estimates only; final
# reporting still uses rendered packet token counts.
PACKET_TOKEN_SURFACE = {
    "gg_max": (11.74, 1.496, 6.215),
    "semantic_arrow": (-0.27, 3.029, 11.273),
    "sql": (25.60, 14.471, 10.797),
    "lowlevel": (24.67, 3.086, 9.296),
    "gg_max_hybrid": (-7.46, 9.103, 6.665),
}


def compute_subgraph_stats(graph: Graph, nodes: set[str], edges: list[Edge]) -> SubgraphStats:
    node_count = len(nodes)
    edge_count = len(edges)
    relation_counts: dict[str, int] = {}
    weak_edges = 0
    for edge in edges:
        relation_counts[edge.type] = relation_counts.get(edge.type, 0) + 1
        if edge.type in WEAK_RELATIONS:
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

    return SubgraphStats(
        nodes=node_count,
        edges=edge_count,
        density=edge_count / max(1, node_count),
        factful_node_ratio=factful_nodes / max(1, node_count),
        relation_entropy=len(relation_counts) / max(1, edge_count),
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
    for packet, (intercept, node_coef, edge_coef) in PACKET_TOKEN_SURFACE.items():
        estimate = intercept + node_coef * nodes + edge_coef * edges
        if packet == "gg_max_hybrid":
            estimate += fact_token_proxy
        estimates[packet] = max(0, int(round(estimate)))
    return estimates
