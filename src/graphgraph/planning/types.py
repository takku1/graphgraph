from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PacketChoice:
    hops: int
    packet: str
    reason: str


@dataclass(frozen=True)
class ContextPlan:
    query_class: str
    hops: int
    direction: str
    packet: str
    node_budget: int | None
    anchor_limit: int
    weak_edge_limit: int
    min_confidence: float
    reason: str
    planner_version: str = "context_plan_v2_budget_directional"


@dataclass(frozen=True)
class SubgraphStats:
    nodes: int
    edges: int
    density: float
    factful_node_ratio: float
    relation_entropy: float
    weak_edge_ratio: float
    estimated_tokens_by_packet: dict[str, int]
