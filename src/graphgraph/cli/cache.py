"""CLI commands for GraphGraph's persisted packet cache."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..io import find_graph_path, load_any, save_validated_graph
from ..runtime.cache import (
    TopologicalKVCache,
    activation_state_file_for_graph,
    cache_file_for_graph,
)


def cmd_cache(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if getattr(args, "graph", None) else None
    # Resolve through the same rule the query paths use, so `cache --clear`
    # and `cache` stats always report the file those paths actually read.
    # Discovery raises when no graph exists yet; reporting an empty cache at
    # the default location is friendlier than failing a read-only status call.
    if graph_path is None:
        try:
            graph_path = find_graph_path()
        except (FileNotFoundError, RuntimeError):
            graph_path = Path(".graphgraph") / "graph.gg"
    cache_file = cache_file_for_graph(graph_path)
    cache = TopologicalKVCache(cache_file)
    if getattr(args, "recompute_centrality", False):
        resolved_graph_path = graph_path or find_graph_path()
        graph = load_any(resolved_graph_path)
        scores = graph.recompute_centrality()
        validation = save_validated_graph(graph, resolved_graph_path)
        count = cache.clear()
        activation_file = activation_state_file_for_graph(resolved_graph_path)
        if activation_file.exists():
            activation_file.unlink()
        print(
            f"Recomputed PageRank for {len(scores)} active nodes in {resolved_graph_path}; "
            f"cleared {count} packet cache entries (validation PASS {validation.format})"
        )
    elif getattr(args, "clear", False):
        count = cache.clear()
        print(f"Cleared {count} cache entries from {cache_file}")
    else:
        stats = cache.stats()
        print(
            f"Cache: {stats['entries']}/{stats['max_entries']} entries  "
            f"hits={stats['hits']}  misses={stats['misses']}  "
            f"hit_rate={stats['hit_rate_pct']}%"
        )
        print(f"File: {cache_file}")
