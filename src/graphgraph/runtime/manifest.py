from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 3


@lru_cache(maxsize=1)
def extractor_fingerprint() -> str:
    """Hash scanner implementation files so semantic edits invalidate restores."""
    scanner_root = Path(__file__).resolve().parents[1] / "scanner"
    hasher = hashlib.sha256()
    for path in sorted(scanner_root.rglob("*.py")):
        hasher.update(path.relative_to(scanner_root).as_posix().encode("utf-8"))
        try:
            hasher.update(path.read_bytes())
        except OSError:
            return ""
    return hasher.hexdigest()


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
        self.source_root = str(data.get("source_root", "")) if data else ""
        self.extractor_fingerprint = (
            str(data.get("extractor_fingerprint", "")) if data
            else extractor_fingerprint()
        )
        self.updated_at = str(data.get("updated_at", "")) if data else ""

    @property
    def compatible(self) -> bool:
        current = extractor_fingerprint()
        return (
            self.version == MANIFEST_VERSION
            and bool(current)
            and self.extractor_fingerprint == current
        )

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
        self.extractor_fingerprint = extractor_fingerprint()
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data = {
            "version": MANIFEST_VERSION,
            "source_root": self.source_root,
            "extractor_fingerprint": self.extractor_fingerprint,
            "updated_at": self.updated_at,
            "files": self.files,
        }
        # Atomic write: a manifest half-written by an interrupted save used to
        # leave a corrupt file that the next restore could not parse. Write to a
        # sibling temp file and replace, so a crash leaves either the old
        # manifest or the complete new one -- never a torn one.
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        tmp = tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
            mode="w", encoding="utf-8", delete=False,
        )
        try:
            with tmp:
                tmp.write(serialized)
            os.replace(tmp.name, path)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise

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
