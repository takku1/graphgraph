from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 4

#: path -> ((mtime_ns, size), parsed payload). The manifest is whole-repo
#: state, so it grows with the corpus and is re-read on every incremental
#: update; `clear_manifest_cache` exists so tests and long-lived servers can
#: drop it explicitly.
_MANIFEST_CACHE: dict[str, tuple[tuple[int, int], Any]] = {}


def clear_manifest_cache() -> None:
    """Forget every parsed manifest. Mirrors `clear_graph_cache`."""
    _MANIFEST_CACHE.clear()


def _isolated(data: dict[str, Any]) -> dict[str, Any]:
    """Give a caller its own view of the two mappings `Manifest` exposes.

    `deepcopy` is not an option: on a 33.5 MB manifest it costs 1,067 ms
    against 449 ms to simply re-read and re-parse, so it would make the cache
    slower than no cache at all. A shallow copy is ~0 ms and is sufficient
    here, because every writer replaces whole entries -- `files[rel] = {...}`,
    `del files[rel]`, `manifest.type_index = ...` -- and none mutates an entry
    in place. Sharing the entry objects is therefore safe; sharing the two
    containers would not be.
    """
    isolated = dict(data)
    files = data.get("files")
    if isinstance(files, dict):
        isolated["files"] = dict(files)
    type_index = data.get("type_index")
    if isinstance(type_index, dict):
        isolated["type_index"] = dict(type_index)
    return isolated


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
        # files: rel_path -> {hash, depth, frontend, docs, nodes, edges,
        #                     type_facts: finite per-file fact contribution}
        self.files = data.get("files", {}) if data else {}
        self.version = int(data.get("version", 0)) if data is not None else MANIFEST_VERSION
        self.source_root = str(data.get("source_root", "")) if data else ""
        self.extractor_fingerprint = (
            str(data.get("extractor_fingerprint", "")) if data
            else extractor_fingerprint()
        )
        self.updated_at = str(data.get("updated_at", "")) if data else ""
        self.type_index = data.get("type_index", {}) if data else {}

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
            _MANIFEST_CACHE.pop(str(path), None)
            return cls()
        # 35 MB of JSON on a 1,574-file checkout, re-parsed in full on every
        # single-file update: measured at 537 ms, 55% of that update's wall
        # time and the largest term in its failure to stay invariant to repo
        # size. A resident process re-paid it on every call, so process
        # residency alone could not remove it.
        #
        # Keyed on the same stat identity the packet cache uses, so an external
        # rewrite changes size or mtime and is re-read. Only the parsed payload
        # is shared; each caller gets its own copy to mutate, because `save`
        # writes back whatever the caller mutated.
        key = str(path)
        try:
            stat = path.stat()
            identity = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            identity = None
        if identity is not None:
            cached = _MANIFEST_CACHE.get(key)
            if cached is not None and cached[0] == identity:
                return cls(_isolated(cached[1]))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls({"version": 0})
        if identity is not None:
            _MANIFEST_CACHE[key] = (identity, data)
            return cls(_isolated(data))
        return cls(data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.extractor_fingerprint = extractor_fingerprint()
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data = {
            "version": MANIFEST_VERSION,
            "source_root": self.source_root,
            "extractor_fingerprint": self.extractor_fingerprint,
            "updated_at": self.updated_at,
            "type_index": self.type_index,
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
        # Seed the cache with what we just wrote. Writing changes the file's
        # stat, so the next `load` would otherwise always miss -- and an
        # incremental update writes the manifest on every call, which made the
        # read cache useless in exactly the edit loop it exists to serve.
        # `data` holds this instance's own `files`/`type_index` mappings, so it
        # is copied out rather than shared with the caller that keeps mutating.
        try:
            stat = path.stat()
        except OSError:
            return
        _MANIFEST_CACHE[str(path)] = ((stat.st_mtime_ns, stat.st_size), _isolated(data))

    def update_file(
        self,
        rel_path: str,
        file_hash: str,
        depth: str,
        frontend: str,
        docs: bool,
        nodes: list[str],
        edges: list[tuple[str, str, str]],
        type_facts: dict[str, Any] | None = None,
    ) -> None:
        self.files[rel_path] = {
            "hash": file_hash,
            "depth": depth,
            "frontend": frontend,
            "docs": docs,
            "nodes": nodes,
            "edges": edges,
            "type_facts": type_facts or {},
        }

    def get_file_info(self, rel_path: str) -> dict[str, Any] | None:
        return self.files.get(rel_path)
