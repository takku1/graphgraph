"""Compatibility facade for the modular planning package.

New code should import from ``graphgraph.planning``. This module preserves the
original public API used by existing callers and benchmarks.
"""

from .planning import (
    ContextPlan,
    PacketChoice,
    SubgraphStats,
    choose_packet,
    choose_packet_for_subgraph,
    compute_subgraph_stats,
    default_anchor_limit,
    default_node_budget,
    estimate_packet_tokens,
    plan_context,
    refine_packet_for_subgraph,
    refine_plan_for_subgraph,
    retrieval_node_budget,
)

__all__ = [
    "ContextPlan",
    "PacketChoice",
    "SubgraphStats",
    "choose_packet",
    "choose_packet_for_subgraph",
    "compute_subgraph_stats",
    "default_anchor_limit",
    "default_node_budget",
    "estimate_packet_tokens",
    "plan_context",
    "refine_packet_for_subgraph",
    "refine_plan_for_subgraph",
    "retrieval_node_budget",
]
