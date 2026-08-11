from __future__ import annotations

from ..packet_targets import TARGET_SPECS, target_spec

# Per-packet token surface: (intercept, node_cost, edge_cost). A packet's
# planning token proxy is intercept + node_cost*nodes + edge_cost*edges;
# gg_hybrid adds a separate fact-token term at runtime, so its surface is
# fit on the residual actual - fact_token_proxy. Coefficients are an ordinary
# least-squares fit over 270 subgraphs across 15 real projects, validated by
# leave-one-project-out (benchmarks/context_graph/token_surface_refit.py):
# After compact packets gained source paths, lines, and definition signatures,
# the prior surface materially undercounted per-node cost. The current refit
# improves out-of-sample packet-winner agreement 61.1% -> 93.7% and mean
# absolute error 280.9 -> 147.5, while preserving the runtime-critical
# zero-edge semantic/gg decision at 100%. Refit whenever packet syntax or the
# real-project calibration corpus changes.
PACKET_TOKEN_SURFACE = {
    spec.name: spec.cost.coefficients
    for spec in TARGET_SPECS
    if spec.cost.calibrated
}


def packet_token_surface(packet: str) -> tuple[float, float, float]:
    try:
        return target_spec(packet).cost.coefficients
    except ValueError:
        return target_spec("gg").cost.coefficients


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
