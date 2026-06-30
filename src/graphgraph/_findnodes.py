"""_findnodes — lightweight node-suggestion helper.

Used by render_final_packet to build a diagnostic when ``resolve_start_nodes``
finds no matches.  Intentionally kept separate from the main retrieval module
to avoid circular imports.
"""
from __future__ import annotations

from .core import Graph
from .retrieval.models import Match
from .retrieval.search import search_nodes


def suggest_node_ids(graph: Graph, hints: list[str], limit: int = 6) -> list[Match]:
    """Return the top *limit* graph nodes most similar to any of *hints*.

    Each hint is searched independently; results are de-duplicated and
    re-ranked by score so the caller gets the best candidates across all hints.
    """
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
