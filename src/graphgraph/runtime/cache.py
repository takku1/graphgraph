from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .manifest import compute_file_hash
from .state import STATE_VERSION, atomic_write_json, file_lock

PLATFORM_STATE_VERSION = STATE_VERSION


def compute_cache_key(anchors: list[str] | set[str], query_class: str, hops: int, packet_format: str) -> str:
    sorted_anchors = sorted(anchors)
    raw_str = f"{','.join(sorted_anchors)}|{query_class}|{hops}|{packet_format}"
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()


class TopologicalKVCache:
    """LRU packet cache keyed by query fingerprint and exact graph state.

    A packet is a derived value of the whole graph, including relationships
    that were absent when the packet was created. Positive dependency paths
    therefore cannot prove cache validity: a new file can add an incoming edge
    to a cached node without changing any path already in the packet.

    Entries record the graph file's SHA-256 content identity. Normal hits pay
    only for a filesystem stat; if size/timestamps/file identity change, the
    graph is hashed once. Byte-identical rewrites stay warm, while any actual
    graph-state change invalidates the packet.

    The cache is bounded by max_entries (default 256); LRU eviction keeps
    frequently reused prompts warm while preventing unbounded growth.
    """

    def __init__(self, cache_file_path: Path | None = None, max_entries: int = 256):
        self.cache_file = cache_file_path or Path(".graphgraph") / "kv_cache.json"
        self.max_entries = max_entries
        self.cache_data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self.load()

    def load(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.cache_data = OrderedDict(raw.get("entries", raw))
        except Exception:
            self.cache_data = OrderedDict()

    def save(self) -> None:
        try:
            atomic_write_json(
                self.cache_file,
                {"version": PLATFORM_STATE_VERSION, "entries": dict(self.cache_data)},
            )
        except Exception:
            pass

    def get(self, graph_path: Path, key: str) -> str | None:
        if key not in self.cache_data:
            self._misses += 1
            return None

        entry = self.cache_data[key]
        if not graph_path.exists():
            del self.cache_data[key]
            self.save()
            self._misses += 1
            return None

        current_stat = self._graph_stat(graph_path)
        stored_stat = tuple(entry.get("graph_stat") or ())
        if current_stat != stored_stat:
            current_hash = compute_file_hash(graph_path)
            if current_hash and current_hash == entry.get("graph_hash", ""):
                entry["graph_stat"] = list(current_stat)
                self.save()
            else:
                del self.cache_data[key]
                self.save()
                self._misses += 1
                return None

        # Move to end (most-recently-used)
        self.cache_data.move_to_end(key)
        self._hits += 1
        return entry.get("packet")

    @staticmethod
    def _graph_stat(graph_path: Path) -> tuple[int, int, int, int]:
        stat = graph_path.stat()
        return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino

    def set(
        self,
        graph_path: Path,
        key: str,
        packet: str,
        *,
        node_ids: list[str] | set[str] | tuple[str, ...] = (),
        paths: list[str] | set[str] | tuple[str, ...] = (),
    ) -> None:
        with file_lock(self.cache_file):
            self.load()
            unique_paths = sorted(path for path in set(paths) if path)
            graph_stat = self._graph_stat(graph_path) if graph_path.exists() else ()
            graph_hash = compute_file_hash(graph_path) if graph_path.exists() else ""
            self.cache_data[key] = {
                "graph_stat": list(graph_stat),
                "graph_hash": graph_hash,
                "packet": packet,
                "node_ids": sorted(set(node_ids)),
                "paths": unique_paths,
            }
            self.cache_data.move_to_end(key)
            while len(self.cache_data) > self.max_entries:
                self.cache_data.popitem(last=False)
            atomic_write_json(
                self.cache_file,
                {"version": PLATFORM_STATE_VERSION, "entries": dict(self.cache_data)},
                lock=False,
            )

    def clear(self) -> int:
        with file_lock(self.cache_file):
            self.load()
            count = len(self.cache_data)
            self.cache_data.clear()
            atomic_write_json(
                self.cache_file,
                {"version": PLATFORM_STATE_VERSION, "entries": {}},
                lock=False,
            )
        return count

    def stats(self) -> dict[str, int]:
        total = self._hits + self._misses
        return {
            "entries": len(self.cache_data),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_pct": round(100 * self._hits / total) if total else 0,
        }
