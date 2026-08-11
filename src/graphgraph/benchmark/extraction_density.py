"""Deterministic graph-serialization density measurement."""

from __future__ import annotations

import json
from dataclasses import asdict

from ..graph.core import Graph


def graph_serialization_words(graph: Graph) -> int:
    """Count whitespace units in the canonical dataclass-field projection.

    This intentionally measures graph/source representation density, not LLM
    tokens. Packet token costs belong to ``graphgraph.packets.metrics``.
    ``asdict`` excludes memoized attributes attached to frozen nodes/edges, so
    prior property access cannot change the measurement.
    """
    payload = json.dumps({
        "nodes": [asdict(node) for node in graph.nodes.values()],
        "edges": [asdict(edge) for edge in graph.edges],
    })
    return len(payload.split())


__all__ = ["graph_serialization_words"]
