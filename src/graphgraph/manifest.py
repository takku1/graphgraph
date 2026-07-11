from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 2


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""

class Manifest:
    def __init__(self, data: dict[str, Any] | None = None):
        # files: rel_path -> {hash, depth, frontend, docs, nodes: list[str], edges: list[tuple[str, str, str]]}
        self.files = data.get("files", {}) if data else {}
        self.version = int(data.get("version", 0)) if data is not None else MANIFEST_VERSION

    @property
    def compatible(self) -> bool:
        return self.version == MANIFEST_VERSION

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data)
        except Exception:
            return cls({"version": 0})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": MANIFEST_VERSION, "files": self.files}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update_file(
        self,
        rel_path: str,
        file_hash: str,
        depth: str,
        frontend: str,
        docs: bool,
        nodes: list[str],
        edges: list[tuple[str, str, str]],
    ) -> None:
        self.files[rel_path] = {
            "hash": file_hash,
            "depth": depth,
            "frontend": frontend,
            "docs": docs,
            "nodes": nodes,
            "edges": edges,
        }

    def get_file_info(self, rel_path: str) -> dict[str, Any] | None:
        return self.files.get(rel_path)
