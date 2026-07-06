from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..manifest import compute_file_hash


def compute_cache_key(anchors: list[str] | set[str], query_class: str, hops: int, packet_format: str) -> str:
    sorted_anchors = sorted(anchors)
    raw_str = f"{','.join(sorted_anchors)}|{query_class}|{hops}|{packet_format}"
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()


class TopologicalKVCache:
    """LRU-evicting packet cache keyed by graph mtime + query fingerprint.

    A graph rescan bumps the saved graph file's mtime even when the rescan is
    incremental and touched files unrelated to a given cached packet. Rather
    than evict every entry on every rescan, entries also record a content hash
    per dependency path (from ``node.path`` on the nodes that made it into the
    packet). When the graph mtime advances, an entry survives if every one of
    its dependency paths still hashes the same on disk -- only entries whose
    actual source files changed are evicted. Entries with no recorded paths
    (or when a dependency path can't be resolved/hashed) fall back to the
    original blanket mtime check.

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
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps({"entries": dict(self.cache_data)}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, graph_path: Path, key: str) -> str | None:
        if key not in self.cache_data:
            self._misses += 1
            return None

        entry = self.cache_data[key]
        if graph_path.exists() and graph_path.stat().st_mtime > entry.get("graph_mtime", 0.0):
            if self._dependencies_unchanged(graph_path, entry):
                entry["graph_mtime"] = graph_path.stat().st_mtime
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

    def _dependencies_unchanged(self, graph_path: Path, entry: dict[str, Any]) -> bool:
        path_hashes: dict[str, str] = entry.get("path_hashes") or {}
        if not path_hashes:
            return False
        project_root = graph_path.parent.parent
        for rel_path, stored_hash in path_hashes.items():
            current_hash = compute_file_hash(project_root / rel_path)
            if not current_hash or current_hash != stored_hash:
                return False
        return True

    def set(
        self,
        graph_path: Path,
        key: str,
        packet: str,
        *,
        node_ids: list[str] | set[str] | tuple[str, ...] = (),
        paths: list[str] | set[str] | tuple[str, ...] = (),
    ) -> None:
        mtime = graph_path.stat().st_mtime if graph_path.exists() else 0.0
        unique_paths = sorted(path for path in set(paths) if path)
        project_root = graph_path.parent.parent
        path_hashes = {
            rel_path: file_hash
            for rel_path in unique_paths
            if (file_hash := compute_file_hash(project_root / rel_path))
        }
        self.cache_data[key] = {
            "graph_mtime": mtime,
            "packet": packet,
            "node_ids": sorted(set(node_ids)),
            "paths": unique_paths,
            "path_hashes": path_hashes,
        }
        self.cache_data.move_to_end(key)
        while len(self.cache_data) > self.max_entries:
            self.cache_data.popitem(last=False)
        self.save()

    def clear(self) -> int:
        count = len(self.cache_data)
        self.cache_data.clear()
        self.save()
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
