"""Backwards-compatible thin wrappers over the single graph cache.

Graph caching used to live in two layers -- an unbounded dict inside
``load_any`` and a bounded LRU here -- with coupled invalidation. They are now
one bounded, locked LRU in :mod:`graphgraph.io.core`; these functions remain as
the public entry points callers already import.
"""

from __future__ import annotations

from pathlib import Path

from ..graph.core import Graph
from .core import clear_graph_load_cache, load_any, remember_loaded_graph


def clear_graph_cache() -> int:
    """Clear the process graph cache and return the number of entries removed."""
    return clear_graph_load_cache()


def load_any_cached(path: Path) -> Graph:
    """Load a graph once per process, invalidated by base + sidecar fingerprint.

    ``load_any`` already memoizes against the same bounded LRU, so this is now a
    thin, stable alias rather than a second cache layer.
    """
    return load_any(path)


def remember_graph(path: Path, graph: Graph) -> None:
    """Seed the process cache with a graph persisted by the current process."""
    remember_loaded_graph(path, graph)
