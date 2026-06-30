from __future__ import annotations

from ..traversal import traversal_policy
from .budgets import default_anchor_limit, retrieval_node_budget
from .packet import choose_packet, choose_packet_for_subgraph
from .types import ContextPlan, PacketChoice, SubgraphStats


def plan_context(
    query_class: str,
    query: str = "",
    *,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    hops: int | None = None,
    packet: str | None = None,
) -> ContextPlan:
    """Build the measured production retrieval/rendering plan."""
    choice = choose_packet(query_class, query)
    traversal = traversal_policy(query_class)
    effective_hops = choice.hops if hops is None else hops
    effective_packet = choice.packet if packet is None else packet
    effective_anchor_limit = default_anchor_limit(query, query_class) if anchor_limit is None else anchor_limit
    node_budget = retrieval_node_budget(query, query_class, max_nodes)
    return ContextPlan(
        query_class=query_class,
        hops=effective_hops,
        direction=traversal.direction,
        packet=effective_packet,
        node_budget=node_budget,
        anchor_limit=effective_anchor_limit,
        weak_edge_limit=traversal.weak_edge_limit,
        min_confidence=traversal.min_confidence,
        reason=choice.reason,
    )


def refine_plan_for_subgraph(plan: ContextPlan, stats: SubgraphStats) -> ContextPlan:
    refined = choose_packet_for_subgraph(PacketChoice(plan.hops, plan.packet, plan.reason), stats, query_class=plan.query_class)
    if refined.packet == plan.packet and refined.reason == plan.reason:
        return plan
    return ContextPlan(
        query_class=plan.query_class,
        hops=plan.hops,
        direction=plan.direction,
        packet=refined.packet,
        node_budget=plan.node_budget,
        anchor_limit=plan.anchor_limit,
        weak_edge_limit=plan.weak_edge_limit,
        min_confidence=plan.min_confidence,
        reason=refined.reason,
        planner_version=plan.planner_version,
    )
