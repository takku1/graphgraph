from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

def compute_cache_key(anchors: list[str] | set[str], query_class: str, hops: int, packet_format: str) -> str:
    """Calculate a unique md5 hash key for a specific graph query subset."""
    sorted_anchors = sorted(list(anchors))
    raw_str = f"{','.join(sorted_anchors)}|{query_class}|{hops}|{packet_format}"
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()


class TopologicalKVCache:
    def __init__(self, cache_file_path: Path | None = None):
        if cache_file_path is None:
            # Default location
            self.cache_file = Path(".graphgraph") / "kv_cache.json"
        else:
            self.cache_file = cache_file_path
            
        self.cache_data: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if self.cache_file.exists():
            try:
                with self.cache_file.open("r", encoding="utf-8") as f:
                    self.cache_data = json.load(f)
            except Exception:
                self.cache_data = {}

    def save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(self.cache_data, f, indent=2)
        except Exception:
            pass

    def get(self, graph_path: Path, key: str) -> str | None:
        """Retrieve a cached packet if valid, otherwise return None."""
        if key not in self.cache_data:
            return None

        entry = self.cache_data[key]
        cached_graph_mtime = entry.get("graph_mtime", 0.0)

        # Invalidation check: check if the actual graph file was updated since the cache entry
        if graph_path.exists():
            current_mtime = graph_path.stat().st_mtime
            if current_mtime > cached_graph_mtime:
                # Evict/invalidate cache entry
                del self.cache_data[key]
                self.save()
                return None

        return entry.get("packet")

    def set(self, graph_path: Path, key: str, packet: str) -> None:
        """Cache a rendered packet with the base graph file's modification time."""
        mtime = graph_path.stat().st_mtime if graph_path.exists() else 0.0
        self.cache_data[key] = {
            "graph_mtime": mtime,
            "packet": packet
        }
        self.save()
