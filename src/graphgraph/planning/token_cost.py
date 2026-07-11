from __future__ import annotations

PACKET_TOKEN_SURFACE = {
    "gg_max": (11.74, 1.496, 6.215),
    "semantic_arrow": (-0.27, 3.029, 11.273),
    "sql": (25.60, 14.471, 10.797),
    "lowlevel": (24.67, 3.086, 9.296),
    "gg_max_hybrid": (-7.46, 9.103, 6.665),
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
