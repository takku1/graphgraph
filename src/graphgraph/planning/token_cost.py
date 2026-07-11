from __future__ import annotations

# Per-packet token surface: (intercept, node_cost, edge_cost). A packet's
# planning token proxy is intercept + node_cost*nodes + edge_cost*edges;
# gg_max_hybrid adds a separate fact-token term at runtime, so its surface is
# fit on the residual actual - fact_token_proxy. Coefficients are an ordinary
# least-squares fit over 270 subgraphs across 15 real projects, validated by
# leave-one-project-out (benchmarks/context_graph/token_surface_refit.py):
# out-of-sample packet-winner agreement 90.4% -> 98.5%, mean abs error
# 186.8 -> 143.2, with the runtime-critical zero-edge semantic/gg decision
# preserved at 100%. Refit here whenever new project graphs are added.
PACKET_TOKEN_SURFACE = {
    "gg_max": (14.5022, 1.6839, 5.2418),
    "semantic_arrow": (7.2784, 3.3447, 11.2080),
    "sql": (17.9379, 15.2861, 10.1090),
    "lowlevel": (31.7781, 3.3877, 9.2161),
    "gg_max_hybrid": (15.3985, 4.7098, 5.1553),
}


def packet_token_surface(packet: str) -> tuple[float, float, float]:
    return PACKET_TOKEN_SURFACE.get(packet, PACKET_TOKEN_SURFACE["gg_max"])


def packet_marginal_costs(packet: str) -> tuple[float, float]:
    _intercept, node_cost, edge_cost = packet_token_surface(packet)
    return max(0.1, node_cost), max(0.1, edge_cost)


def estimate_surface_tokens(packet: str, nodes: int, edges: int) -> int:
    intercept, node_cost, edge_cost = packet_token_surface(packet)
    return max(0, int(round(intercept + node_cost * nodes + edge_cost * edges)))


def nodes_for_surface_budget(packet: str, target_tokens: int, edges_per_node: float) -> int:
    intercept, node_cost, edge_cost = packet_token_surface(packet)
    marginal_cost = max(1.0, node_cost + edge_cost * max(0.0, edges_per_node))
    return max(1, int((target_tokens - intercept) / marginal_cost))
