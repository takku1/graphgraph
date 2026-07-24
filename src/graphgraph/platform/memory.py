from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
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
    anchor_receipt: dict[str, object] = field(default_factory=dict)


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
        graph: Graph | None = None,
        anchor_limit: int = 8,
    ) -> MemoryRecord:
        timestamp = datetime.now(timezone.utc).isoformat()
        record_id = hashlib.sha256(f"{scope}\0{kind}\0{content}".encode("utf-8")).hexdigest()[:16]
        resolved_nodes, anchor_receipt = resolve_memory_anchors(
            graph,
            content,
            explicit=related_nodes,
            limit=anchor_limit,
        )
        record = MemoryRecord(
            record_id,
            scope,
            content,
            kind,
            timestamp,
            source,
            resolved_nodes,
            anchor_receipt,
        )
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
            anchor_receipt=dict(row.get("anchor_receipt") or {}),
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


_NON_SYMBOL_KINDS = frozenset({
    "file",
    "python",
    "javascript",
    "typescript",
    "tsx",
    "rust",
    "java",
    "c",
    "cpp",
    "csharp",
    "ruby",
    "php",
    "swift",
    "kotlin",
    "scala",
    "package",
    "directory",
    "concept",
    "section",
    "paragraph",
    "markdown",
    "text",
    "html",
    "unknown",
})
_MEMORY_MENTION_STOPWORDS = frozenset({
    "add",
    "build",
    "call",
    "class",
    "code",
    "data",
    "file",
    "function",
    "memory",
    "method",
    "project",
    "query",
    "return",
    "test",
})
_QUALIFIED_MENTION_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:::|\.)\s*([A-Za-z_][A-Za-z0-9_]*)\b"
)
_BACKTICK_IDENTIFIER_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def resolve_memory_anchors(
    graph: Graph | None,
    content: str,
    *,
    explicit: tuple[str, ...] = (),
    limit: int = 8,
) -> tuple[tuple[str, ...], dict[str, object]]:
    """Resolve strong code-symbol mentions and return a persistent trust receipt."""
    bounded_limit = max(0, min(int(limit), 100))
    if graph is None:
        accepted = tuple(dict.fromkeys(explicit))[:bounded_limit]
        return accepted, {
            "mode": "explicit_unvalidated" if explicit else "no_graph",
            "accepted": list(accepted),
            "ambiguous": [],
            "rejected_explicit": [],
            "truncated": len(tuple(dict.fromkeys(explicit))) > len(accepted),
            "limit": bounded_limit,
        }

    symbol_nodes = {
        node_id: node
        for node_id, node in graph.nodes.items()
        if node.active and node.path and node.kind not in _NON_SYMBOL_KINDS
    }
    accepted: list[str] = []
    rejected_explicit: list[str] = []
    for value in dict.fromkeys(explicit):
        if value in symbol_nodes:
            accepted.append(value)
        else:
            rejected_explicit.append(value)

    by_label: dict[str, list[str]] = {}
    for node_id, node in symbol_nodes.items():
        by_label.setdefault(node.label, []).append(node_id)

    qualified_hits: list[tuple[str, list[str]]] = []
    for owner, member in _QUALIFIED_MENTION_RE.findall(content):
        candidates = [
            node_id
            for node_id in by_label.get(member, ())
            if _node_has_owner(graph, node_id, owner)
        ]
        if candidates:
            qualified_hits.append((f"{owner}::{member}", sorted(candidates)))

    explicit_identifiers = set(_BACKTICK_IDENTIFIER_RE.findall(content))
    exact_tokens = {
        token
        for token in _TOKEN_RE.findall(content)
        if len(token) >= 3 and token.casefold() not in _MEMORY_MENTION_STOPWORDS
        and (
            token in explicit_identifiers
            or "_" in token
            or any(character.isdigit() for character in token)
            or token.isupper()
            or any(character.isupper() for character in token[1:])
        )
    }
    exact_hits = [
        (token, sorted(by_label[token]))
        for token in sorted(exact_tokens)
        if token in by_label
    ]

    ambiguous: list[dict[str, object]] = []
    candidates: list[str] = list(accepted)
    for mention, ids in (*qualified_hits, *exact_hits):
        if len(ids) > 1:
            ambiguous.append({
                "mention": mention,
                "candidate_ids": ids[:8],
                "candidate_count": len(ids),
            })
        candidates.extend(ids)
    candidates = list(dict.fromkeys(candidates))
    truncated = len(candidates) > bounded_limit
    accepted = candidates[:bounded_limit]
    return tuple(accepted), {
        "mode": "explicit+exact_symbol",
        "accepted": list(accepted),
        "ambiguous": ambiguous,
        "rejected_explicit": rejected_explicit,
        "truncated": truncated,
        "limit": bounded_limit,
    }


def _node_has_owner(graph: Graph, node_id: str, owner: str) -> bool:
    node = graph.nodes[node_id]
    if any(
        fact == f"javascript_owner:{owner}"
        or fact.endswith(f":{owner}")
        for fact in node.facts
    ):
        return True
    if node.parent and node.parent in graph.nodes:
        return graph.nodes[node.parent].label == owner
    return f"[{owner}::{node.label}]" in node.summary
