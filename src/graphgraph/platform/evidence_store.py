from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from ..graph.core import Edge, Graph, Node
from ..runtime.manifest import Manifest, compute_file_hash
from .contracts import CapabilityReceipt, EvidenceBatch, EvidenceProvider
from .persistence import atomic_write_json, file_lock

EVIDENCE_STORE_VERSION = 2
_GLOBAL_KEY = "__global__"


class EvidenceStore:
    """Versioned provider IR cache partitioned by provider and source path."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def refresh_batches(
        self,
        graph: Graph,
        providers: Iterable[EvidenceProvider],
        *,
        changed_paths: tuple[str, ...] = (),
        force: bool = False,
        preferred_paths: tuple[str, ...] = (),
        max_nodes: int | None = None,
        max_edges: int | None = None,
    ) -> tuple[EvidenceBatch, ...]:
        if self.path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            return self._refresh_sqlite(
                graph,
                providers,
                changed_paths=changed_paths,
                force=force,
                preferred_paths=preferred_paths,
                max_nodes=max_nodes,
                max_edges=max_edges,
            )
        with file_lock(self.path):
            return self._refresh_batches_locked(
                graph,
                providers,
                changed_paths=changed_paths,
                force=force,
                preferred_paths=preferred_paths,
                max_nodes=max_nodes,
                max_edges=max_edges,
            )

    def _refresh_batches_locked(
        self,
        graph: Graph,
        providers: Iterable[EvidenceProvider],
        *,
        changed_paths: tuple[str, ...] = (),
        force: bool = False,
        preferred_paths: tuple[str, ...] = (),
        max_nodes: int | None = None,
        max_edges: int | None = None,
    ) -> tuple[EvidenceBatch, ...]:
        data = self._load()
        provider_data = data.setdefault("providers", {})
        batches: list[EvidenceBatch] = []
        normalized_changed = {path.replace("\\", "/") for path in changed_paths}
        for provider in providers:
            current = provider_data.get(provider.name)
            if (
                not isinstance(current, dict)
                or str(current.get("version")) != provider.version
                or force
            ):
                current = {
                    "version": provider.version,
                    "capabilities": list(provider.capabilities),
                    "files": {},
                }
                provider_data[provider.name] = current
            files = current.setdefault("files", {})
            if provider.incremental:
                batch = self._refresh_incremental(
                    graph,
                    provider,
                    files,
                    normalized_changed,
                    force=force,
                    preferred_paths=preferred_paths,
                    max_nodes=max_nodes,
                    max_edges=max_edges,
                )
            else:
                batch = self._refresh_global(
                    graph,
                    provider,
                    files,
                    force=force,
                    preferred_paths=preferred_paths,
                    max_nodes=max_nodes,
                    max_edges=max_edges,
                )
            batches.append(batch)
        active_names = {provider.name for provider in providers}
        for stale_name in set(provider_data) - active_names:
            del provider_data[stale_name]
        self._save(data)
        return tuple(batches)

    def _refresh_incremental(
        self,
        graph: Graph,
        provider: EvidenceProvider,
        files: dict[str, object],
        changed_paths: set[str],
        *,
        force: bool,
        preferred_paths: tuple[str, ...],
        max_nodes: int | None,
        max_edges: int | None,
    ) -> EvidenceBatch:
        source_hashes = self._source_hashes(graph, provider)
        for removed in set(files) - set(source_hashes):
            del files[removed]
        stale_paths = [
            path
            for path, file_hash in source_hashes.items()
            if force
            or path in changed_paths
            or not isinstance(files.get(path), dict)
            or str(files[path].get("hash", "")) != file_hash
        ]
        for path in stale_paths:
            batch = provider.collect(graph, (path,))
            files[path] = _batch_to_data(batch, source_hashes[path])
        restored = max(0, len(source_hashes) - len(stale_paths))
        return _aggregate_batch(
            provider,
            (
                {**files[path], "_path": path}
                for path in source_hashes
                if isinstance(files.get(path), dict)
            ),
            paths_processed=len(stale_paths),
            paths_restored=restored,
            preferred_paths=preferred_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

    def _refresh_global(
        self,
        graph: Graph,
        provider: EvidenceProvider,
        files: dict[str, object],
        *,
        force: bool,
        preferred_paths: tuple[str, ...],
        max_nodes: int | None,
        max_edges: int | None,
    ) -> EvidenceBatch:
        signature = _graph_signature(graph)
        cached = files.get(_GLOBAL_KEY)
        processed = 0
        if force or not isinstance(cached, dict) or str(cached.get("hash", "")) != signature:
            cached = _batch_to_data(provider.collect(graph), signature)
            files.clear()
            files[_GLOBAL_KEY] = cached
            processed = 1
        return _aggregate_batch(
            provider,
            (cached,),
            paths_processed=processed,
            paths_restored=0 if processed else 1,
            preferred_paths=preferred_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

    def _refresh_sqlite(
        self,
        graph: Graph,
        providers: Iterable[EvidenceProvider],
        *,
        changed_paths: tuple[str, ...],
        force: bool,
        preferred_paths: tuple[str, ...],
        max_nodes: int | None,
        max_edges: int | None,
    ) -> tuple[EvidenceBatch, ...]:
        connection = self._connect()
        try:
            self._import_legacy(connection)
            batches: list[EvidenceBatch] = []
            normalized_changed = {path.replace("\\", "/") for path in changed_paths}
            active_names: set[str] = set()
            with connection:
                for provider in providers:
                    active_names.add(provider.name)
                    current = connection.execute(
                        "SELECT version FROM providers WHERE provider = ?",
                        (provider.name,),
                    ).fetchone()
                    invalidated = (
                        current is None
                        or str(current[0]) != provider.version
                        or force
                    )
                    if invalidated:
                        connection.execute(
                            "DELETE FROM batches WHERE provider = ?",
                            (provider.name,),
                        )
                    connection.execute(
                        """
                        INSERT INTO providers(provider, version, capabilities, incremental)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(provider) DO UPDATE SET
                            version=excluded.version,
                            capabilities=excluded.capabilities,
                            incremental=excluded.incremental
                        """,
                        (
                            provider.name,
                            provider.version,
                            json.dumps(provider.capabilities, separators=(",", ":")),
                            int(provider.incremental),
                        ),
                    )
                    if provider.incremental:
                        source_hashes = self._source_hashes(graph, provider)
                        existing = {
                            str(path): str(file_hash)
                            for path, file_hash in connection.execute(
                                "SELECT path, source_hash FROM batches WHERE provider = ?",
                                (provider.name,),
                            )
                        }
                        removed = set(existing) - set(source_hashes)
                        if removed:
                            connection.executemany(
                                "DELETE FROM batches WHERE provider = ? AND path = ?",
                                ((provider.name, path) for path in removed),
                            )
                        stale_paths = [
                            path
                            for path, file_hash in source_hashes.items()
                            if invalidated
                            or path in normalized_changed
                            or existing.get(path) != file_hash
                        ]
                        for path in stale_paths:
                            self._upsert_sqlite_batch(
                                connection,
                                provider.name,
                                path,
                                source_hashes[path],
                                provider.collect(graph, (path,)),
                            )
                        batches.append(self._aggregate_sqlite(
                            connection,
                            provider,
                            paths_processed=len(stale_paths),
                            paths_restored=max(0, len(source_hashes) - len(stale_paths)),
                            preferred_paths=preferred_paths,
                            max_nodes=max_nodes,
                            max_edges=max_edges,
                        ))
                    else:
                        signature = _graph_signature(graph)
                        current_hash = connection.execute(
                            "SELECT source_hash FROM batches WHERE provider = ? AND path = ?",
                            (provider.name, _GLOBAL_KEY),
                        ).fetchone()
                        processed = 0
                        if invalidated or current_hash is None or str(current_hash[0]) != signature:
                            self._upsert_sqlite_batch(
                                connection,
                                provider.name,
                                _GLOBAL_KEY,
                                signature,
                                provider.collect(graph),
                            )
                            processed = 1
                        batches.append(self._aggregate_sqlite(
                            connection,
                            provider,
                            paths_processed=processed,
                            paths_restored=0 if processed else 1,
                            preferred_paths=preferred_paths,
                            max_nodes=max_nodes,
                            max_edges=max_edges,
                        ))
                stale_providers = [
                    str(row[0])
                    for row in connection.execute("SELECT provider FROM providers")
                    if str(row[0]) not in active_names
                ]
                for name in stale_providers:
                    connection.execute("DELETE FROM batches WHERE provider = ?", (name,))
                    connection.execute("DELETE FROM providers WHERE provider = ?", (name,))
            return tuple(batches)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS providers (
                provider TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                incremental INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batches (
                provider TEXT NOT NULL,
                path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                nodes TEXT NOT NULL,
                edges TEXT NOT NULL,
                receipt TEXT NOT NULL,
                nodes_count INTEGER NOT NULL,
                edges_count INTEGER NOT NULL,
                PRIMARY KEY(provider, path),
                FOREIGN KEY(provider) REFERENCES providers(provider) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS batches_provider_path
                ON batches(provider, path);
            """
        )
        return connection

    def _upsert_sqlite_batch(
        self,
        connection: sqlite3.Connection,
        provider: str,
        path: str,
        source_hash: str,
        batch: EvidenceBatch,
    ) -> None:
        nodes = [_node_to_data(node) for node in batch.nodes]
        edges = [_edge_to_data(edge) for edge in batch.edges]
        connection.execute(
            """
            INSERT INTO batches(
                provider, path, source_hash, nodes, edges, receipt,
                nodes_count, edges_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, path) DO UPDATE SET
                source_hash=excluded.source_hash,
                nodes=excluded.nodes,
                edges=excluded.edges,
                receipt=excluded.receipt,
                nodes_count=excluded.nodes_count,
                edges_count=excluded.edges_count
            """,
            (
                provider,
                path,
                source_hash,
                json.dumps(nodes, ensure_ascii=False, separators=(",", ":")),
                json.dumps(edges, ensure_ascii=False, separators=(",", ":")),
                json.dumps(asdict(batch.receipt), ensure_ascii=False, separators=(",", ":")),
                len(nodes),
                len(edges),
            ),
        )

    def _aggregate_sqlite(
        self,
        connection: sqlite3.Connection,
        provider: EvidenceProvider,
        *,
        paths_processed: int,
        paths_restored: int,
        preferred_paths: tuple[str, ...],
        max_nodes: int | None,
        max_edges: int | None,
    ) -> EvidenceBatch:
        metadata = list(connection.execute(
            """
            SELECT path, receipt, nodes_count, edges_count
            FROM batches WHERE provider = ?
            """,
            (provider.name,),
        ))
        ordered = _order_paths(
            (str(row[0]) for row in metadata),
            preferred_paths,
        )
        by_path = {str(row[0]): row for row in metadata}
        node_limit = _effective_limit(provider, "max_nodes", max_nodes)
        edge_limit = _effective_limit(provider, "max_edges", max_edges)
        selected_nodes = 0
        selected_edges = 0
        entries: list[dict[str, object]] = []
        for path in ordered:
            row = by_path[path]
            node_count = int(row[2])
            edge_count = int(row[3])
            materialize = (
                (node_limit is None or selected_nodes < node_limit)
                or (edge_limit is None or selected_edges < edge_limit)
            )
            if materialize:
                payload = connection.execute(
                    "SELECT nodes, edges FROM batches WHERE provider = ? AND path = ?",
                    (provider.name, path),
                ).fetchone()
                entries.append({
                    "_path": path,
                    "nodes": json.loads(str(payload[0])),
                    "edges": json.loads(str(payload[1])),
                    "receipt": json.loads(str(row[1])),
                })
                selected_nodes += node_count
                selected_edges += edge_count
            else:
                entries.append({
                    "_path": path,
                    "_materialized": False,
                    "_nodes_count": node_count,
                    "_edges_count": edge_count,
                    "receipt": json.loads(str(row[1])),
                })
        return _aggregate_batch(
            provider,
            entries,
            paths_processed=paths_processed,
            paths_restored=paths_restored,
            preferred_paths=preferred_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

    def migrate_legacy(self) -> bool:
        if self.path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
            return False
        connection = self._connect()
        try:
            return self._import_legacy(connection)
        finally:
            connection.close()

    def _import_legacy(self, connection: sqlite3.Connection) -> bool:
        if connection.execute("SELECT 1 FROM providers LIMIT 1").fetchone():
            return False
        legacy_path = self.path.with_suffix(".json")
        if not legacy_path.exists():
            return False
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if int(data.get("version", 0)) != EVIDENCE_STORE_VERSION:
            return False
        with connection:
            for name, provider_data in data.get("providers", {}).items():
                if not isinstance(provider_data, dict):
                    continue
                capabilities = tuple(str(value) for value in provider_data.get("capabilities", ()))
                connection.execute(
                    "INSERT OR REPLACE INTO providers VALUES (?, ?, ?, ?)",
                    (
                        str(name),
                        str(provider_data.get("version", "")),
                        json.dumps(capabilities, separators=(",", ":")),
                        int(_GLOBAL_KEY not in provider_data.get("files", {})),
                    ),
                )
                for path, entry in provider_data.get("files", {}).items():
                    if not isinstance(entry, dict):
                        continue
                    nodes = entry.get("nodes", [])
                    edges = entry.get("edges", [])
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO batches VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(name),
                            str(path),
                            str(entry.get("hash", "")),
                            json.dumps(nodes, ensure_ascii=False, separators=(",", ":")),
                            json.dumps(edges, ensure_ascii=False, separators=(",", ":")),
                            json.dumps(entry.get("receipt", {}), ensure_ascii=False, separators=(",", ":")),
                            len(nodes),
                            len(edges),
                        ),
                    )
        return True

    def _source_hashes(self, graph: Graph, provider: EvidenceProvider) -> dict[str, str]:
        manifest = Manifest.load(self.path.parent / "manifest.json")
        sources: dict[str, Path] = {}
        supports_path = getattr(provider, "supports_path", lambda path: True)
        for node in graph.nodes.values():
            path = node.path.replace("\\", "/")
            if not path or not node.active or not supports_path(path):
                continue
            if node.source:
                source = Path(node.source)
                if source.is_file():
                    sources.setdefault(path, source)
        hashes: dict[str, str] = {}
        for path, source in sorted(sources.items()):
            info = manifest.get_file_info(path)
            hashes[path] = str(info.get("hash", "")) if info and info.get("hash") else compute_file_hash(source)
        return hashes

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {"version": EVIDENCE_STORE_VERSION, "providers": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": EVIDENCE_STORE_VERSION, "providers": {}}
        if int(data.get("version", 0)) != EVIDENCE_STORE_VERSION:
            return {"version": EVIDENCE_STORE_VERSION, "providers": {}}
        return data

    def _save(self, data: dict[str, object]) -> None:
        data["version"] = EVIDENCE_STORE_VERSION
        atomic_write_json(self.path, data, indent=None, lock=False)


def _aggregate_batch(
    provider: EvidenceProvider,
    entries: Iterable[object],
    *,
    paths_processed: int,
    paths_restored: int,
    preferred_paths: tuple[str, ...] = (),
    max_nodes: int | None = None,
    max_edges: int | None = None,
) -> EvidenceBatch:
    cached_entries = [entry for entry in entries if isinstance(entry, dict)]
    path_order = _order_paths(
        (str(entry.get("_path", "")) for entry in cached_entries),
        preferred_paths,
    )
    order_index = {path: index for index, path in enumerate(path_order)}
    cached_entries.sort(key=lambda entry: order_index.get(str(entry.get("_path", "")), len(order_index)))
    nodes: list[Node] = []
    edges: list[Edge] = []
    receipts: list[CapabilityReceipt] = []
    node_limit = _effective_limit(provider, "max_nodes", max_nodes)
    edge_limit = _effective_limit(provider, "max_edges", max_edges)
    omitted_node_ids: set[str] = set()
    extra_nodes_truncated = 0
    extra_edges_truncated = 0
    for entry in cached_entries:
        receipt_data = entry.get("receipt") or {}
        receipts.append(_receipt_from_data(receipt_data, provider))
        if entry.get("_materialized") is False:
            extra_nodes_truncated += int(entry.get("_nodes_count", 0))
            extra_edges_truncated += int(entry.get("_edges_count", 0))
            continue
        entry_omitted = False
        for item in entry.get("nodes", []):
            if node_limit is not None and len(nodes) >= node_limit:
                omitted_node_ids.add(str(item.get("id", "")))
                extra_nodes_truncated += 1
                entry_omitted = True
            else:
                nodes.append(_node_from_data(item))
        for item in entry.get("edges", []):
            if (
                entry_omitted
                or str(item.get("source", "")) in omitted_node_ids
                or str(item.get("target", "")) in omitted_node_ids
                or (edge_limit is not None and len(edges) >= edge_limit)
            ):
                extra_edges_truncated += 1
            else:
                edges.append(_edge_from_data(item))
    return EvidenceBatch(
        nodes=tuple(nodes),
        edges=tuple(edges),
        receipt=CapabilityReceipt(
            provider=provider.name,
            version=provider.version,
            capabilities=provider.capabilities,
            nodes_emitted=sum(item.nodes_emitted for item in receipts),
            edges_emitted=sum(item.edges_emitted for item in receipts),
            nodes_truncated=sum(item.nodes_truncated for item in receipts) + extra_nodes_truncated,
            edges_truncated=sum(item.edges_truncated for item in receipts) + extra_edges_truncated,
            paths_processed=paths_processed,
            paths_restored=paths_restored,
            cache_hit=paths_processed == 0 and paths_restored > 0,
            warnings=tuple(dict.fromkeys(warning for item in receipts for warning in item.warnings)),
        ),
    )


def _order_paths(
    paths: Iterable[str],
    preferred_paths: tuple[str, ...],
) -> list[str]:
    available = tuple(dict.fromkeys(path for path in paths if path))
    preferred = {
        path.replace("\\", "/"): index
        for index, path in enumerate(preferred_paths)
    }
    return sorted(
        available,
        key=lambda path: (
            0 if path.replace("\\", "/") in preferred else 1,
            preferred.get(path.replace("\\", "/"), len(preferred)),
            path,
        ),
    )


def _effective_limit(
    provider: EvidenceProvider,
    attribute: str,
    requested: int | None,
) -> int | None:
    provider_limit = int(getattr(provider, attribute, 0)) or None
    if requested is None:
        return provider_limit
    requested = max(0, requested)
    return min(provider_limit, requested) if provider_limit is not None else requested


def _batch_to_data(batch: EvidenceBatch, file_hash: str) -> dict[str, object]:
    return {
        "hash": file_hash,
        "nodes": [_node_to_data(node) for node in batch.nodes],
        "edges": [_edge_to_data(edge) for edge in batch.edges],
        "receipt": asdict(batch.receipt),
    }


def _receipt_from_data(data: dict[str, object], provider: EvidenceProvider) -> CapabilityReceipt:
    fields = CapabilityReceipt.__dataclass_fields__
    values = {key: data[key] for key in fields if key in data}
    values["provider"] = provider.name
    values["version"] = provider.version
    values["capabilities"] = tuple(data.get("capabilities") or provider.capabilities)
    values["warnings"] = tuple(data.get("warnings") or ())
    return CapabilityReceipt(**values)


def _node_to_data(node: Node) -> dict[str, object]:
    return {
        "id": node.id,
        "label": node.label,
        "kind": node.kind,
        "path": node.path,
        "summary": node.summary,
        "facts": list(node.facts),
        "scope": node.scope,
        "parent": node.parent,
        "source": node.source,
        "confidence": node.confidence,
        "active": node.active,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


def _node_from_data(data: dict[str, object]) -> Node:
    return Node(
        id=str(data["id"]),
        label=str(data.get("label", "")),
        kind=str(data.get("kind", "unknown")),
        path=str(data.get("path", "")),
        summary=str(data.get("summary", "")),
        facts=tuple(str(value) for value in data.get("facts", [])),
        scope=str(data.get("scope", "")),
        parent=str(data.get("parent", "")),
        source=str(data.get("source", "")),
        confidence=float(data.get("confidence", 1.0)),
        active=bool(data.get("active", True)),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
    )


def _edge_to_data(edge: Edge) -> dict[str, object]:
    return {
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "weight": edge.weight,
        "confidence": edge.confidence,
        "provenance": edge.provenance,
        "evidence": edge.evidence,
        "source_location": edge.source_location,
        "valid_from": edge.valid_from,
        "valid_to": edge.valid_to,
        "active": edge.active,
    }


def _edge_from_data(data: dict[str, object]) -> Edge:
    return Edge(
        source=str(data["source"]),
        target=str(data["target"]),
        type=str(data["type"]),
        weight=float(data.get("weight", 1.0)),
        confidence=float(data.get("confidence", 1.0)),
        provenance=str(data.get("provenance", "extracted")),
        evidence=str(data.get("evidence", "")),
        source_location=str(data.get("source_location", "")),
        valid_from=str(data.get("valid_from", "")),
        valid_to=str(data.get("valid_to", "")),
        active=bool(data.get("active", True)),
    )


def _graph_signature(graph: Graph) -> str:
    digest = hashlib.sha256()
    for node in sorted(graph.nodes.values(), key=lambda item: item.id):
        if node.active and node.path:
            digest.update(f"N\0{node.id}\0{node.path}\n".encode("utf-8"))
    for edge in sorted(
        (edge for edge in graph.edges if edge.active),
        key=lambda item: (item.source, item.target, item.type),
    ):
        digest.update(f"E\0{edge.source}\0{edge.type}\0{edge.target}\n".encode("utf-8"))
    return digest.hexdigest()
