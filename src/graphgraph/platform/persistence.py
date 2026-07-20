from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..runtime.state import (
    STATE_VERSION,
    append_jsonl,
    append_jsonl_many,
    atomic_write_json,
    atomic_write_text,
    file_lock,
)

PLATFORM_STATE_VERSION = STATE_VERSION
__all__ = [
    "PLATFORM_STATE_VERSION",
    "append_jsonl",
    "append_jsonl_many",
    "atomic_write_json",
    "atomic_write_text",
    "file_lock",
    "migrate_platform_state",
]


def migrate_platform_state(directory: Path) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    migrated: list[str] = []
    unchanged: list[str] = []
    warnings: list[str] = []
    for name, migrate in (
        ("memory.json", _migrate_memory),
        ("semantic.json", _migrate_semantic),
        ("projects.json", _migrate_projects),
        ("evidence.json", _migrate_evidence),
        ("kv_cache.json", _migrate_cache),
        ("episodes.jsonl", _migrate_episodes),
    ):
        path = directory / name
        if not path.exists():
            continue
        try:
            with file_lock(path):
                changed = migrate(path)
            (migrated if changed else unchanged).append(name)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            warnings.append(f"{name}:{type(exc).__name__}:{exc}")
    if (directory / "evidence.json").exists() or (directory / "evidence.db").exists():
        try:
            from .evidence_store import EvidenceStore

            evidence = EvidenceStore(directory / "evidence.db")
            evidence.migrate_legacy()
        except (OSError, ValueError, sqlite3.Error) as exc:
            warnings.append(f"evidence.db:{type(exc).__name__}:{exc}")
    return {
        "version": PLATFORM_STATE_VERSION,
        "directory": str(directory.resolve()),
        "migrated": migrated,
        "unchanged": unchanged,
        "warnings": warnings,
        "evidence_backend": "sqlite" if (directory / "evidence.db").exists() else "json",
        "ok": not warnings,
    }


def _migrate_memory(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and int(data.get("version", 0)) >= PLATFORM_STATE_VERSION:
        return False
    records = data.get("records", []) if isinstance(data, dict) else data
    atomic_write_json(path, {"version": PLATFORM_STATE_VERSION, "records": records}, lock=False)
    return True


def _migrate_semantic(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(data.get("version", 0)) >= PLATFORM_STATE_VERSION:
        return False
    data["version"] = PLATFORM_STATE_VERSION
    data.setdefault("signature", "")
    atomic_write_json(path, data, indent=None, lock=False)
    return True


def _migrate_projects(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(data.get("version", 0)) >= PLATFORM_STATE_VERSION:
        return False
    data["version"] = PLATFORM_STATE_VERSION
    atomic_write_json(path, data, lock=False)
    return True


def _migrate_evidence(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(data.get("version", 0)) >= PLATFORM_STATE_VERSION:
        return False
    data["version"] = PLATFORM_STATE_VERSION
    atomic_write_json(path, data, indent=None, lock=False)
    return True


def _migrate_cache(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and int(data.get("version", 0)) >= PLATFORM_STATE_VERSION:
        return False
    entries = data.get("entries", data) if isinstance(data, dict) else {}
    atomic_write_json(
        path,
        {"version": PLATFORM_STATE_VERSION, "entries": entries},
        lock=False,
    )
    return True


def _migrate_episodes(path: Path) -> bool:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if rows and all(int(row.get("version", 0)) >= PLATFORM_STATE_VERSION for row in rows):
        return False
    for row in rows:
        row["version"] = PLATFORM_STATE_VERSION
    atomic_write_text(
        path,
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        lock=False,
    )
    return True
