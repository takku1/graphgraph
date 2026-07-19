from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock

from ..graph.core import Graph
from . import core as _core
from .core import load_any

_CACHE_LIMIT = 8
_CACHE: OrderedDict[Path, tuple[int, int, Graph]] = OrderedDict()
_LOCK = RLock()


def clear_graph_cache() -> int:
    """Clear both graph-load cache layers and return removed entries."""
    with _LOCK:
        removed = len(_CACHE)
        _CACHE.clear()
        removed += len(_core._graph_load_cache)
        _core._graph_load_cache.clear()
    return removed


def load_any_cached(path: Path) -> Graph:
    """Load a graph once per process and invalidate it by mtime and size."""
    resolved = path.resolve()
    stat = resolved.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        cached = _CACHE.get(resolved)
        if cached is not None and cached[:2] == fingerprint:
            _CACHE.move_to_end(resolved)
            return cached[2]
    graph = load_any(resolved)
    remember_graph(resolved, graph)
    return graph


def remember_graph(path: Path, graph: Graph) -> None:
    """Seed the process cache with a graph persisted by the current process."""
    resolved = path.resolve()
    stat = resolved.stat()
    with _LOCK:
        _CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, graph)
        _CACHE.move_to_end(resolved)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
