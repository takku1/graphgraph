from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from .persistence import PLATFORM_STATE_VERSION, atomic_write_json, file_lock

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    scope: str
    content: str
    kind: str = "fact"
    created_at: str = ""
    source: str = ""
    related_nodes: tuple[str, ...] = ()


class MemoryStore:
    """Project/user/session memory as a small append-only local graph."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def remember(
        self,
        content: str,
        *,
        scope: str = "project",
        kind: str = "fact",
        source: str = "",
        related_nodes: tuple[str, ...] = (),
    ) -> MemoryRecord:
        timestamp = datetime.now(timezone.utc).isoformat()
        record_id = hashlib.sha256(f"{scope}\0{kind}\0{content}".encode("utf-8")).hexdigest()[:16]
        record = MemoryRecord(record_id, scope, content, kind, timestamp, source, related_nodes)
        with file_lock(self.path):
            existing = {item.id: item for item in self._read_unlocked()}
            existing[record.id] = record
            self._write(existing.values(), lock=False)
        return record

    def read(self, *, scopes: tuple[str, ...] = ()) -> list[MemoryRecord]:
        records = self._read_unlocked()
        return [record for record in records if not scopes or record.scope in scopes]

    def _read_unlocked(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("records", [])
        records = [MemoryRecord(
            id=str(row["id"]),
            scope=str(row["scope"]),
            content=str(row["content"]),
            kind=str(row.get("kind", "fact")),
            created_at=str(row.get("created_at", "")),
            source=str(row.get("source", "")),
            related_nodes=tuple(str(value) for value in row.get("related_nodes", [])),
        ) for row in rows]
        return records

    def search(self, query: str, *, scopes: tuple[str, ...] = (), limit: int = 10) -> list[MemoryRecord]:
        query_terms = set(_tokens(query))
        scored = []
        for record in self.read(scopes=scopes):
            terms = set(_tokens(f"{record.kind} {record.content}"))
            score = len(query_terms & terms) / max(1, len(query_terms | terms))
            if score:
                scored.append((score, record.created_at, record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:max(0, limit)]]

    def project(self, graph: Graph, *, scopes: tuple[str, ...] = ()) -> Graph:
        nodes = dict(graph.nodes)
        edges = list(graph.edges)
        for record in self.read(scopes=scopes):
            node_id = f"memory:{record.id}"
            nodes[node_id] = Node(
                id=node_id,
                label=record.content[:80],
                kind=f"memory_{record.kind}",
                summary=record.content,
                scope=record.scope,
                source=record.source,
                created_at=record.created_at,
                updated_at=record.created_at,
            )
            for related in record.related_nodes:
                if related in nodes:
                    edges.append(Edge(node_id, related, "remembers", provenance="memory", valid_from=record.created_at))
        return Graph(nodes=nodes, edges=edges, metadata=dict(graph.metadata))

    def _write(self, records, *, lock: bool = True) -> None:
        data = [asdict(record) for record in sorted(records, key=lambda item: item.created_at)]
        atomic_write_json(
            self.path,
            {"version": PLATFORM_STATE_VERSION, "records": data},
            lock=lock,
        )


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value)]
