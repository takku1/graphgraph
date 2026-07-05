"""GraphGraph native binary storage.

The promoted ``.gg`` store is a full-fidelity binary format for scanned
GraphGraph graphs. It is dictionary-coded, sequential to load, and intentionally
does not carry generic object-map overhead from JSON/msgpack/SQL rows.

Legacy text ``.gg`` adjacency files are still readable through ``io.load_gg``;
new ``.gg`` writes use this binary format.
"""

from __future__ import annotations

import struct
from pathlib import Path

from .core import Edge, Graph, Node

_PAGERANK_ALGORITHM = "pagerank"
_GGB_MAGIC = b"GGB3"
_GGB_HEADER = struct.Struct("<4sIIIIII")
_GGB_NODE_RECORD = struct.Struct("<" + "I" * 12 + "dB")
_GGB_EDGE_RECORD = struct.Struct("<" + "I" * 8 + "ddB")
_PAIR_RECORD = struct.Struct("<II")
_PAGERANK_HEADER = struct.Struct("<IdII")
_PAGERANK_SCORE_RECORD = struct.Struct("<Id")


def is_binary_gg(path: Path) -> bool:
    try:
        return path.read_bytes()[:4] in {_GGB_MAGIC, b"GGB2"}
    except OSError:
        return False


def _put_string(strings: dict[str, int], value: str) -> int:
    value = value or ""
    idx = strings.get(value)
    if idx is None:
        idx = len(strings)
        strings[value] = idx
    return idx


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def save_graph_binary(graph: Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    strings: dict[str, int] = {}

    metadata_rows = [
        (_put_string(strings, str(key)), _put_string(strings, str(value)))
        for key, value in sorted(graph.metadata.items())
    ]

    pagerank = graph.pagerank_cache_payload()
    pagerank_signature = _put_string(strings, str(pagerank.get("signature", "")))
    pagerank_tol = _put_string(strings, str(pagerank.get("tol", 1e-4)))
    pagerank_scores = []
    raw_scores = pagerank.get("scores")
    if isinstance(raw_scores, dict):
        pagerank_scores = [
            (_put_string(strings, str(node_id)), float(score))
            for node_id, score in sorted(raw_scores.items())
        ]

    fact_refs: list[int] = []
    node_rows = []
    for node in graph.nodes.values():
        fact_start = len(fact_refs)
        for fact in node.facts:
            fact_refs.append(_put_string(strings, fact))
        node_rows.append((
            _put_string(strings, node.id),
            _put_string(strings, node.label),
            _put_string(strings, node.kind),
            _put_string(strings, node.path),
            _put_string(strings, node.summary),
            fact_start,
            len(node.facts),
            _put_string(strings, node.scope),
            _put_string(strings, node.parent),
            _put_string(strings, node.source),
            _put_string(strings, node.created_at),
            _put_string(strings, node.updated_at),
            float(node.confidence),
            1 if node.active else 0,
        ))

    edge_rows = [
        (
            _put_string(strings, edge.source),
            _put_string(strings, edge.target),
            _put_string(strings, edge.type),
            _put_string(strings, edge.provenance),
            _put_string(strings, edge.evidence),
            _put_string(strings, edge.source_location),
            _put_string(strings, edge.valid_from),
            _put_string(strings, edge.valid_to),
            float(edge.weight),
            float(edge.confidence),
            1 if edge.active else 0,
        )
        for edge in graph.edges
    ]

    dictionary = sorted(strings, key=strings.__getitem__)
    with path.open("wb") as fh:
        fh.write(_GGB_HEADER.pack(
            _GGB_MAGIC,
            len(dictionary),
            len(node_rows),
            len(edge_rows),
            len(metadata_rows),
            len(fact_refs),
            len(pagerank_scores),
        ))
        fh.write(_PAGERANK_HEADER.pack(
            pagerank_signature,
            float(pagerank.get("damping", 0.85)),
            int(pagerank.get("max_iter", 20)),
            pagerank_tol,
        ))
        for value in dictionary:
            raw = value.encode("utf-8")
            fh.write(struct.pack("<I", len(raw)))
            fh.write(raw)
        for key_idx, value_idx in metadata_rows:
            fh.write(_PAIR_RECORD.pack(key_idx, value_idx))
        for fact_idx in fact_refs:
            fh.write(struct.pack("<I", fact_idx))
        for row in node_rows:
            fh.write(_GGB_NODE_RECORD.pack(*row))
        for row in edge_rows:
            fh.write(_GGB_EDGE_RECORD.pack(*row))
        for node_idx, score in pagerank_scores:
            fh.write(_PAGERANK_SCORE_RECORD.pack(node_idx, score))


def load_graph_binary(path: Path) -> Graph:
    data = path.read_bytes()
    magic = data[:4]
    if magic == b"GGB2":
        return _load_ggb2(data)
    if magic != _GGB_MAGIC:
        raise ValueError(f"unsupported .gg binary magic/version: {magic!r}")

    offset = 0
    (
        _magic,
        string_count,
        node_count,
        edge_count,
        metadata_count,
        fact_ref_count,
        pagerank_count,
    ) = _GGB_HEADER.unpack_from(data, offset)
    offset += _GGB_HEADER.size
    pagerank_signature, pagerank_damping, pagerank_max_iter, pagerank_tol = _PAGERANK_HEADER.unpack_from(data, offset)
    offset += _PAGERANK_HEADER.size

    strings, offset = _read_strings(data, offset, string_count)

    def s(idx: int) -> str:
        return strings[idx] if 0 <= idx < len(strings) else ""

    metadata: dict[str, str] = {}
    for _ in range(metadata_count):
        key_idx, value_idx = _PAIR_RECORD.unpack_from(data, offset)
        offset += _PAIR_RECORD.size
        metadata[s(key_idx)] = s(value_idx)

    fact_refs = []
    for _ in range(fact_ref_count):
        fact_idx, offset = _read_u32(data, offset)
        fact_refs.append(fact_idx)

    nodes: dict[str, Node] = {}
    for _ in range(node_count):
        record = _GGB_NODE_RECORD.unpack_from(data, offset)
        offset += _GGB_NODE_RECORD.size
        (
            id_,
            label,
            kind,
            node_path,
            summary,
            fact_start,
            fact_count,
            scope,
            parent,
            source,
            created_at,
            updated_at,
            confidence,
            active,
        ) = record
        facts = tuple(s(fact_refs[i]) for i in range(fact_start, fact_start + fact_count))
        node_id = s(id_)
        nodes[node_id] = Node(
            id=node_id,
            label=s(label),
            kind=s(kind) or "unknown",
            path=s(node_path),
            summary=s(summary),
            facts=facts,
            scope=s(scope),
            parent=s(parent),
            source=s(source),
            confidence=float(confidence),
            active=bool(active),
            created_at=s(created_at),
            updated_at=s(updated_at),
        )

    edges: list[Edge] = []
    for _ in range(edge_count):
        source, target, type_, provenance, evidence, source_location, valid_from, valid_to, weight, confidence, active = (
            _GGB_EDGE_RECORD.unpack_from(data, offset)
        )
        offset += _GGB_EDGE_RECORD.size
        edges.append(Edge(
            source=s(source),
            target=s(target),
            type=s(type_) or "dependency",
            weight=float(weight),
            confidence=float(confidence),
            provenance=s(provenance) or "extracted",
            evidence=s(evidence),
            source_location=s(source_location),
            valid_from=s(valid_from),
            valid_to=s(valid_to),
            active=bool(active),
        ))

    pagerank_scores = {}
    for _ in range(pagerank_count):
        node_idx, score = _PAGERANK_SCORE_RECORD.unpack_from(data, offset)
        offset += _PAGERANK_SCORE_RECORD.size
        pagerank_scores[s(node_idx)] = float(score)

    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)
    if pagerank_scores:
        graph.seed_pagerank_cache({
            "algorithm": _PAGERANK_ALGORITHM,
            "version": 1,
            "damping": pagerank_damping,
            "max_iter": pagerank_max_iter,
            "tol": float(s(pagerank_tol) or 1e-4),
            "signature": s(pagerank_signature),
            "scores": pagerank_scores,
        })
    return graph


def _read_strings(data: bytes, offset: int, string_count: int) -> tuple[list[str], int]:
    strings: list[str] = []
    for _ in range(string_count):
        size, offset = _read_u32(data, offset)
        strings.append(data[offset: offset + size].decode("utf-8"))
        offset += size
    return strings, offset


def _load_ggb2(data: bytes) -> Graph:
    # Backward compatibility for the brief .ggb/GGB2 bake-off candidate.
    import json

    header = struct.Struct("<4sIII")
    node_record = struct.Struct("<" + "I" * 9 + "dB")
    edge_record = _GGB_EDGE_RECORD

    offset = header.size
    string_count, node_count, edge_count = header.unpack_from(data, 0)[1:]
    metadata_len, offset = _read_u32(data, offset)
    raw_metadata = json.loads(data[offset: offset + metadata_len].decode("utf-8")) if metadata_len else {}
    offset += metadata_len
    strings, offset = _read_strings(data, offset, string_count)

    def s(idx: int) -> str:
        return strings[idx] if 0 <= idx < len(strings) else ""

    nodes: dict[str, Node] = {}
    for _ in range(node_count):
        record = node_record.unpack_from(data, offset)
        offset += node_record.size
        created_at, updated_at = struct.unpack_from("<II", data, offset)
        offset += 8
        id_, label, kind, node_path, summary, facts, scope, parent, source, confidence, active = record
        node_id = s(id_)
        nodes[node_id] = Node(
            id=node_id,
            label=s(label),
            kind=s(kind) or "unknown",
            path=s(node_path),
            summary=s(summary),
            facts=tuple(json.loads(s(facts))) if s(facts) else (),
            scope=s(scope),
            parent=s(parent),
            source=s(source),
            confidence=float(confidence),
            active=bool(active),
            created_at=s(created_at),
            updated_at=s(updated_at),
        )

    edges: list[Edge] = []
    for _ in range(edge_count):
        source, target, type_, provenance, evidence, source_location, valid_from, valid_to, weight, confidence, active = (
            edge_record.unpack_from(data, offset)
        )
        offset += edge_record.size
        edges.append(Edge(
            source=s(source),
            target=s(target),
            type=s(type_) or "dependency",
            weight=float(weight),
            confidence=float(confidence),
            provenance=s(provenance) or "extracted",
            evidence=s(evidence),
            source_location=s(source_location),
            valid_from=s(valid_from),
            valid_to=s(valid_to),
            active=bool(active),
        ))

    pagerank_payload = raw_metadata.pop("__pagerank__", None)
    graph = Graph(nodes=nodes, edges=edges, metadata={str(k): str(v) for k, v in raw_metadata.items()})
    if isinstance(pagerank_payload, str):
        try:
            payload = json.loads(pagerank_payload)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            graph.seed_pagerank_cache(payload)
    return graph
