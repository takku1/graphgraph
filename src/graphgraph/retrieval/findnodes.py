"""Node-suggestion helpers for user-facing diagnostics.

The final-packet path uses this module when a requested start handle does not
match any graph node. Keeping this separate from retrieval avoids importing the
full service layer from search code.
"""
from __future__ import annotations

from ..graph.core import Graph
from .models import Match
from .search import search_nodes


def suggest_node_ids(graph: Graph, hints: list[str], limit: int = 6) -> list[Match]:
    """Return the best node suggestions across all non-empty hints."""
    seen: set[str] = set()
    all_matches: list[Match] = []
    for hint in hints:
        if not hint.strip():
            continue
        for match in search_nodes(graph, hint, limit=limit * 2):
            if match.node.id not in seen:
                seen.add(match.node.id)
                all_matches.append(match)
    all_matches.sort(key=lambda m: -m.score)
    return all_matches[:limit]
