"""Alternative persisted storage backends for a scanned Graph.

These are candidates being benchmarked against the default JSON/`.gg` formats
in `io.py` (see `benchmarks/context_graph/storage_backend_bakeoff.py` and
`docs/empirical-findings.md`). Each backend provides `save_x(graph, path)` /
`load_x(path) -> Graph`, matching the shape of `io.save_graph`/`io.load_any`
so `io.py` can dispatch to them by file suffix without any change to `core.py`.

`duckdb` and `msgpack` are optional dependencies (extras group
`storage-bakeoff` in pyproject.toml); `sqlite3` is stdlib.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .core import Edge, Graph, Node

_NODE_COLUMNS = (
    "id", "label", "kind", "path", "summary", "facts", "scope", "parent",
    "source", "confidence", "active", "created_at", "updated_at",
)
_EDGE_COLUMNS = (
    "source", "target", "type", "weight", "confidence", "provenance",
    "evidence", "source_location", "valid_from", "valid_to", "active",
)

_SCHEMA_STATEMENTS = (
    """CREATE TABLE nodes (
        id TEXT PRIMARY KEY, label TEXT, kind TEXT, path TEXT, summary TEXT,
        facts TEXT, scope TEXT, parent TEXT, source TEXT, confidence REAL,
        active INTEGER, created_at TEXT, updated_at TEXT
    )""",
    """CREATE TABLE edges (
        source TEXT, target TEXT, type TEXT, weight REAL, confidence REAL,
        provenance TEXT, evidence TEXT, source_location TEXT, valid_from TEXT,
        valid_to TEXT, active INTEGER
    )""",
    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE INDEX idx_edges_source ON edges(source)",
    "CREATE INDEX idx_edges_target ON edges(target)",
)

_PAGERANK_KEY = "__pagerank__"


def _node_row(node: Node) -> tuple:
    return (
        node.id, node.label, node.kind, node.path, node.summary,
        json.dumps(list(node.facts)), node.scope, node.parent, node.source,
        node.confidence, int(node.active), node.created_at, node.updated_at,
    )


def _edge_row(edge: Edge) -> tuple:
    return (
        edge.source, edge.target, edge.type, edge.weight, edge.confidence,
        edge.provenance, edge.evidence, edge.source_location, edge.valid_from,
        edge.valid_to, int(edge.active),
    )


def _node_from_row(row: tuple) -> Node:
    (id_, label, kind, path, summary, facts_json, scope, parent, source,
     confidence, active, created_at, updated_at) = row
    return Node(
        id=id_, label=label, kind=kind, path=path or "", summary=summary or "",
        facts=tuple(json.loads(facts_json)) if facts_json else (),
        scope=scope or "", parent=parent or "", source=source or "",
        confidence=float(confidence), active=bool(active),
        created_at=created_at or "", updated_at=updated_at or "",
    )


def _edge_from_row(row: tuple) -> Edge:
    (source, target, type_, weight, confidence, provenance, evidence,
     source_location, valid_from, valid_to, active) = row
    return Edge(
        source=source, target=target, type=type_, weight=float(weight),
        confidence=float(confidence), provenance=provenance or "extracted",
        evidence=evidence or "", source_location=source_location or "",
        valid_from=valid_from or "", valid_to=valid_to or "", active=bool(active),
    )


def _graph_from_rows(
    node_rows: list[tuple], edge_rows: list[tuple], metadata_rows: list[tuple]
) -> Graph:
    nodes = {row[0]: _node_from_row(row) for row in node_rows}
    edges = [_edge_from_row(row) for row in edge_rows]
    metadata: dict[str, str] = {}
    pagerank_payload = None
    for key, value in metadata_rows:
        if key == _PAGERANK_KEY:
            pagerank_payload = json.loads(value)
        else:
            metadata[key] = value
    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)
    if isinstance(pagerank_payload, dict):
        graph.seed_pagerank_cache(pagerank_payload)
    return graph


# --- SQLite (stdlib) --------------------------------------------------------

def save_sqlite(graph: Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    try:
        for stmt in _SCHEMA_STATEMENTS:
            con.execute(stmt)
        con.executemany(
            f"INSERT INTO nodes VALUES ({','.join('?' * len(_NODE_COLUMNS))})",
            [_node_row(n) for n in graph.nodes.values()],
        )
        con.executemany(
            f"INSERT INTO edges VALUES ({','.join('?' * len(_EDGE_COLUMNS))})",
            [_edge_row(e) for e in graph.edges],
        )
        metadata_rows = list(graph.metadata.items())
        metadata_rows.append((_PAGERANK_KEY, json.dumps(graph.pagerank_cache_payload())))
        con.executemany("INSERT INTO metadata VALUES (?, ?)", metadata_rows)
        con.commit()
    finally:
        con.close()


def load_sqlite(path: Path) -> Graph:
    con = sqlite3.connect(str(path))
    try:
        node_rows = con.execute(f"SELECT {','.join(_NODE_COLUMNS)} FROM nodes").fetchall()
        edge_rows = con.execute(f"SELECT {','.join(_EDGE_COLUMNS)} FROM edges").fetchall()
        metadata_rows = con.execute("SELECT key, value FROM metadata").fetchall()
    finally:
        con.close()
    return _graph_from_rows(node_rows, edge_rows, metadata_rows)


# --- DuckDB (optional extra) -------------------------------------------------

def _arrow_table(columns: tuple[str, ...], rows: list[tuple]) -> "pa.Table":
    import pyarrow as pa

    transposed = list(zip(*rows)) if rows else [() for _ in columns]
    return pa.table(dict(zip(columns, transposed)))


def save_duckdb(graph: Graph, path: Path) -> None:
    # duckdb.executemany() has severe per-call overhead (seconds per few thousand
    # rows even on an in-memory DB); bulk-loading via an Arrow table and
    # `INSERT ... SELECT * FROM <arrow_var>` (DuckDB's replacement-scan path) is
    # ~150x faster and is the documented way to bulk-load DuckDB from Python.
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        for stmt in _SCHEMA_STATEMENTS:
            con.execute(stmt)

        nodes_arrow = _arrow_table(_NODE_COLUMNS, [_node_row(n) for n in graph.nodes.values()])
        con.execute("INSERT INTO nodes SELECT * FROM nodes_arrow")

        edges_arrow = _arrow_table(_EDGE_COLUMNS, [_edge_row(e) for e in graph.edges])
        con.execute("INSERT INTO edges SELECT * FROM edges_arrow")

        metadata_rows = list(graph.metadata.items())
        metadata_rows.append((_PAGERANK_KEY, json.dumps(graph.pagerank_cache_payload())))
        metadata_arrow = _arrow_table(("key", "value"), metadata_rows)
        con.execute("INSERT INTO metadata SELECT * FROM metadata_arrow")
    finally:
        con.close()


def load_duckdb(path: Path) -> Graph:
    import duckdb

    con = duckdb.connect(str(path))
    try:
        node_rows = con.execute(f"SELECT {','.join(_NODE_COLUMNS)} FROM nodes").fetchall()
        edge_rows = con.execute(f"SELECT {','.join(_EDGE_COLUMNS)} FROM edges").fetchall()
        metadata_rows = con.execute("SELECT key, value FROM metadata").fetchall()
    finally:
        con.close()
    return _graph_from_rows(node_rows, edge_rows, metadata_rows)


# --- msgpack (optional extra) -------------------------------------------------

def _graph_to_dict(graph: Graph) -> dict:
    return {
        "nodes": [
            {
                "id": node.id, "label": node.label, "kind": node.kind,
                "path": node.path, "summary": node.summary, "facts": list(node.facts),
                "scope": node.scope, "parent": node.parent, "source": node.source,
                "confidence": node.confidence, "active": node.active,
                "created_at": node.created_at, "updated_at": node.updated_at,
            }
            for node in graph.nodes.values()
        ],
        "edges": [
            {
                "source": edge.source, "target": edge.target, "type": edge.type,
                "weight": edge.weight, "confidence": edge.confidence,
                "provenance": edge.provenance, "evidence": edge.evidence,
                "source_location": edge.source_location, "valid_from": edge.valid_from,
                "valid_to": edge.valid_to, "active": edge.active,
            }
            for edge in graph.edges
        ],
        "metadata": dict(graph.metadata),
        "centrality": {"pagerank": graph.pagerank_cache_payload()},
    }


def _graph_from_dict(data: dict) -> Graph:
    nodes = {
        item["id"]: Node(
            id=item["id"], label=item["label"], kind=item["kind"], path=item["path"],
            summary=item["summary"], facts=tuple(item.get("facts") or []),
            scope=item["scope"], parent=item["parent"], source=item["source"],
            confidence=float(item["confidence"]), active=bool(item["active"]),
            created_at=item["created_at"], updated_at=item["updated_at"],
        )
        for item in data["nodes"]
    }
    edges = [
        Edge(
            source=item["source"], target=item["target"], type=item["type"],
            weight=float(item["weight"]), confidence=float(item["confidence"]),
            provenance=item["provenance"], evidence=item["evidence"],
            source_location=item["source_location"], valid_from=item["valid_from"],
            valid_to=item["valid_to"], active=bool(item["active"]),
        )
        for item in data["edges"]
    ]
    graph = Graph(nodes=nodes, edges=edges, metadata=dict(data.get("metadata") or {}))
    pagerank_payload = (data.get("centrality") or {}).get("pagerank")
    if isinstance(pagerank_payload, dict):
        graph.seed_pagerank_cache(pagerank_payload)
    return graph


def save_msgpack(graph: Graph, path: Path) -> None:
    import msgpack

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(msgpack.packb(_graph_to_dict(graph), use_bin_type=True))


def load_msgpack(path: Path) -> Graph:
    import msgpack

    data = msgpack.unpackb(path.read_bytes(), raw=False)
    return _graph_from_dict(data)
