from __future__ import annotations

from dataclasses import dataclass, field

from ..graph.core import Edge, Node


@dataclass(frozen=True)
class Match:
    node: Node
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    starts: tuple[str, ...]
    matches: tuple[Match, ...]
    nodes: set[str]
    edges: list[Edge]
    metadata: dict[str, object] = field(default_factory=dict)
