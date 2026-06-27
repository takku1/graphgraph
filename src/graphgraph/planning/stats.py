from __future__ import annotations

from ..core import Edge, Graph

from .types import SubgraphStats


WEAK_RELATIONS = {"references", "links", "mentions", "discusses", "section_of"}
PACKET_ESTIMATE_OVERHEAD = {
    "gg_max": 8,
    "semantic_arrow": 3,
    "sql": 9,
    "lowlevel": 12,
    "gg_max_hybrid": 8,
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
    for node_id in nodes:
        node = graph.nodes.get(node_id)
        if not node:
            continue
        if node.summary or node.facts:
            factful_nodes += 1
        fact_token_proxy += max(0, len(node.summary) // 4)
        fact_token_proxy += sum(max(1, len(fact) // 4) for fact in node.facts[:2])

    return SubgraphStats(
        nodes=node_count,
        edges=edge_count,
        density=edge_count / max(1, node_count),
        factful_node_ratio=factful_nodes / max(1, node_count),
        relation_entropy=len(relation_counts) / max(1, edge_count),
        weak_edge_ratio=weak_edges / max(1, edge_count),
        estimated_tokens_by_packet=estimate_packet_tokens(node_count, edge_count, fact_token_proxy),
    )


def estimate_packet_tokens(nodes: int, edges: int, fact_token_proxy: int = 0) -> dict[str, int]:
    """Fast packet token proxy used for planning, not reporting."""
    return {
        "gg_max": PACKET_ESTIMATE_OVERHEAD["gg_max"] + int(nodes * 2.5 + edges * 4.0),
        "semantic_arrow": PACKET_ESTIMATE_OVERHEAD["semantic_arrow"] + int(nodes * 3.0 + edges * 7.0),
        "sql": PACKET_ESTIMATE_OVERHEAD["sql"] + int(nodes * 5.0 + edges * 8.5),
        "lowlevel": PACKET_ESTIMATE_OVERHEAD["lowlevel"] + int(nodes * 4.0 + edges * 5.0),
        "gg_max_hybrid": PACKET_ESTIMATE_OVERHEAD["gg_max_hybrid"] + int(nodes * 2.5 + edges * 4.0 + fact_token_proxy),
    }
