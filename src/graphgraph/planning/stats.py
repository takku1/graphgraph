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
    """Fast packet token proxy used for planning, not reporting."""
    label_tokens = max(1.0, avg_label_len / 4.0)
    
    # gg_max prints: "IDX LABEL" (overhead ~1.5 tokens per node)
    gg_max_node_tokens = 1.5 + label_tokens
    # gg_max edge prints: "SRC TGT REL" (overhead ~3 tokens per edge)
    gg_max_edge_tokens = 3.0
    
    # semantic_arrow prints: "SRC -REL-> TGT" (two labels + relation overhead ~3.5 tokens)
    arrow_edge_tokens = (label_tokens * 2.0) + 3.5
    
    return {
        "gg_max": PACKET_ESTIMATE_OVERHEAD["gg_max"] + int(nodes * gg_max_node_tokens + edges * gg_max_edge_tokens),
        "semantic_arrow": PACKET_ESTIMATE_OVERHEAD["semantic_arrow"] + int(nodes * label_tokens + edges * arrow_edge_tokens),
        "sql": PACKET_ESTIMATE_OVERHEAD["sql"] + int(nodes * (label_tokens + 4.0) + edges * 8.5),
        "lowlevel": PACKET_ESTIMATE_OVERHEAD["lowlevel"] + int(nodes * 4.0 + edges * 5.0),
        "gg_max_hybrid": PACKET_ESTIMATE_OVERHEAD["gg_max_hybrid"] + int(nodes * gg_max_node_tokens + edges * gg_max_edge_tokens + fact_token_proxy),
    }
