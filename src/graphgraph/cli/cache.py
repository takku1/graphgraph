"""CLI commands for GraphGraph's persisted packet cache."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..io import find_graph_path, load_any, save_validated_graph
from ..runtime.cache import TopologicalKVCache


def cmd_cache(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if getattr(args, "graph", None) else None
    cache_file = (
        graph_path.parent / "kv_cache.json"
        if graph_path
        else Path(".graphgraph") / "kv_cache.json"
    )
    cache = TopologicalKVCache(cache_file)
    if getattr(args, "recompute_centrality", False):
        resolved_graph_path = graph_path or find_graph_path()
        graph = load_any(resolved_graph_path)
        scores = graph.recompute_centrality()
        validation = save_validated_graph(graph, resolved_graph_path)
        count = cache.clear()
        activation_file = resolved_graph_path.parent / "activation_state.json"
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
