"""GGB4 sectioned canonical graph storage.

GGB4 keeps the full-fidelity GGB3 contract while separating hot identity and
relation data from cold summaries, facts, evidence, and complete edge records.
Every section has an explicit offset, decoded record count, and CRC32. Readers
can therefore load the whole Graph or only the exact-relation sections without
maintaining a duplicate database or sidecar index.
"""

from __future__ import annotations

import hashlib
import io
import os
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from ..runtime.state import replace_with_retry

GGB4_MAGIC = b"GGB4"
_HEADER = struct.Struct("<4sHHI")  # magic, section count, flags, directory crc
_DIRECTORY_ENTRY = struct.Struct("<4sQQII")  # kind, offset, bytes, records, crc
_U32 = struct.Struct("<I")
_PAIR = struct.Struct("<II")
_NODE_LITE = struct.Struct("<IIIIiIB")
_NODE_DETAIL = struct.Struct("<8Id")
_EDGE = struct.Struct("<III5IddB")
_PAGERANK_HEADER = struct.Struct("<IdII")
_PAGERANK_SCORE = struct.Struct("<Id")
_RELATION_HEADER = struct.Struct("<II")
_CALL = struct.Struct("<IIdIIII")
_INDEX_REF = struct.Struct("<QI")
_MAX_SECTIONS = 64
_PAGERANK_ALGORITHM = "pagerank"


@dataclass(frozen=True, slots=True)
class Section:
    kind: bytes
    offset: int
    length: int
    count: int
    crc32: int


@dataclass(frozen=True, slots=True)
class SectionedDirectory:
    sections: dict[bytes, Section]
    file_size: int


@dataclass(frozen=True, slots=True)
class RelationNode:
    id: str
    label: str
    kind: str
    path: str
    line: int | None
    role: str


@dataclass(frozen=True, slots=True)
class RelationCall:
    source_n: int
    target_n: int
    confidence: float
    provenance: str
    source_location: str
    evidence: str
    edge_count: int


@dataclass(frozen=True, slots=True)
class SectionedRelationView:
    topology_status: str
    topology_detail: str
    nodes: tuple[RelationNode, ...]
    calls: tuple[RelationCall, ...]
    by_id: dict[str, int]
    incoming: dict[int, tuple[RelationCall, ...]]
    outgoing: dict[int, tuple[RelationCall, ...]]


@dataclass(frozen=True, slots=True)
class PackedRelationView:
    """Zero-materialization exact-relation view over GGB4 hot sections."""

    topology_status: str
    topology_detail: str
    identity: bytes
    identity_offsets: bytes
    node_rows: bytes
    node_count: int
    exact_index: bytes
    exact_index_count: int
    outgoing_calls: bytes
    outgoing_offsets: bytes
    incoming_calls: bytes
    incoming_offsets: bytes
    relation_strings: tuple[str, ...]


def is_sectioned_graph(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == GGB4_MAGIC
    except OSError:
        return False


def _put(strings: dict[str, int], value: str) -> int:
    value = value or ""
    found = strings.get(value)
    if found is not None:
        return found
    index = len(strings)
    strings[value] = index
    return index


def _encode_strings(strings: dict[str, int]) -> bytes:
    buffer = io.BytesIO()
    for value in sorted(strings, key=strings.__getitem__):
        encoded = value.encode("utf-8")
        buffer.write(_U32.pack(len(encoded)))
        buffer.write(encoded)
    return buffer.getvalue()


def _encode_string_offsets(strings: dict[str, int]) -> bytes:
    offsets: list[tuple[int]] = []
    offset = 0
    for value in sorted(strings, key=strings.__getitem__):
        offsets.append((offset,))
        offset += _U32.size + len(value.encode("utf-8"))
    return _pack_rows(_U32, offsets)


def _index_text(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/ ").casefold()


def _index_hash(namespace: bytes, value: str) -> int:
    digest = hashlib.blake2b(
        namespace + b"\0" + value.encode("utf-8"),
        digest_size=8,
        person=b"graphgg4",
    ).digest()
    return int.from_bytes(digest, "little")


def _call_offsets(rows: list[tuple], node_count: int, key_index: int) -> bytes:
    offsets: list[tuple[int]] = []
    cursor = 0
    for node_n in range(node_count):
        offsets.append((cursor,))
        while cursor < len(rows) and rows[cursor][key_index] == node_n:
            cursor += 1
    offsets.append((cursor,))
    return _pack_rows(_U32, offsets)


def _pack_rows(record: struct.Struct, rows: list[tuple]) -> bytes:
    buffer = io.BytesIO()
    for row in rows:
        buffer.write(record.pack(*row))
    return buffer.getvalue()


def _best_calls(graph: Graph, numeric: dict[str, int]) -> list[tuple[int, int, Edge, int]]:
    grouped: dict[tuple[int, int], tuple[Edge, int]] = {}
    for edge in graph.edges:
        if not edge.active or edge.type != "calls":
            continue
        source_n = numeric.get(edge.source)
        target_n = numeric.get(edge.target)
        if source_n is None or target_n is None:
            continue
        key = (source_n, target_n)
        current = grouped.get(key)
        if current is None:
            grouped[key] = (edge, 1)
        elif edge.confidence > current[0].confidence:
            grouped[key] = (edge, current[1] + 1)
        else:
            grouped[key] = (current[0], current[1] + 1)
    return [(source, target, edge, count) for (source, target), (edge, count) in grouped.items()]


def save_sectioned_graph(graph: Graph, path: Path) -> None:
    """Atomically write one full-fidelity GGB4 store."""

    # Imports stay local so the physical codec remains below retrieval during
    # module initialization while sharing the exact public role/receipt rules.
    from ..retrieval.relations import _node_role, _topology_receipt

    path.parent.mkdir(parents=True, exist_ok=True)
    identity: dict[str, int] = {}
    detail: dict[str, int] = {}
    relation: dict[str, int] = {}

    metadata_rows = [
        (_put(detail, str(key)), _put(detail, str(value)))
        for key, value in sorted(graph.metadata.items())
    ]
    fact_refs: list[tuple[int]] = []
    node_lite_rows: list[tuple] = []
    node_detail_rows: list[tuple] = []
    exact_index_rows: list[tuple[int, int]] = []
    numeric: dict[str, int] = {}
    for node_n, node in enumerate(graph.nodes.values()):
        if node.active:
            numeric[node.id] = node_n
            exact_index_rows.extend(
                (
                    (_index_hash(b"id", node.id), node_n),
                    (_index_hash(b"label", node.label.casefold()), node_n),
                    (_index_hash(b"path", _index_text(node.path)), node_n),
                )
            )
        fact_start = len(fact_refs)
        for fact in node.facts:
            fact_refs.append((_put(detail, fact),))
        node_lite_rows.append((
            _put(identity, node.id),
            _put(identity, node.label),
            _put(identity, node.kind),
            _put(identity, node.path),
            -1 if node.line is None else int(node.line),
            _put(identity, _node_role(node)),
            1 if node.active else 0,
        ))
        node_detail_rows.append((
            _put(detail, node.summary),
            fact_start,
            len(node.facts),
            _put(detail, node.scope),
            _put(detail, node.parent),
            _put(detail, node.source),
            _put(detail, node.created_at),
            _put(detail, node.updated_at),
            float(node.confidence),
        ))

    edge_rows = [
        (
            _put(identity, edge.source),
            _put(identity, edge.target),
            _put(identity, edge.type),
            _put(detail, edge.provenance),
            _put(detail, edge.evidence),
            _put(detail, edge.source_location),
            _put(detail, edge.valid_from),
            _put(detail, edge.valid_to),
            float(edge.weight),
            float(edge.confidence),
            1 if edge.active else 0,
        )
        for edge in graph.edges
    ]

    pagerank = graph.pagerank_cache_payload()
    pagerank_header = _PAGERANK_HEADER.pack(
        _put(identity, str(pagerank.get("signature", ""))),
        float(pagerank.get("damping", 0.85)),
        int(pagerank.get("max_iter", 20)),
        _put(detail, str(pagerank.get("tol", 1e-4))),
    )
    raw_scores = pagerank.get("scores")
    pagerank_rows = (
        [(_put(identity, str(node_id)), float(score)) for node_id, score in sorted(raw_scores.items())]
        if isinstance(raw_scores, dict)
        else []
    )

    topology_status, topology_detail = _topology_receipt(graph)
    relation_header = _RELATION_HEADER.pack(
        _put(relation, topology_status),
        _put(relation, topology_detail),
    )
    call_rows = [
        (
            source_n,
            target_n,
            float(edge.confidence),
            _put(relation, edge.provenance),
            _put(relation, edge.source_location),
            _put(relation, edge.evidence),
            count,
        )
        for source_n, target_n, edge, count in _best_calls(graph, numeric)
    ]
    outgoing_call_rows = sorted(call_rows, key=lambda row: (row[0], row[1]))
    incoming_call_rows = sorted(call_rows, key=lambda row: (row[1], row[0]))
    exact_index_rows.sort()
    node_count = len(node_lite_rows)

    raw_sections: list[tuple[bytes, bytes, int]] = [
        (b"IDS0", _encode_strings(identity), len(identity)),
        (b"IDOF", _encode_string_offsets(identity), len(identity)),
        (b"DTS0", _encode_strings(detail), len(detail)),
        (b"RLS0", _encode_strings(relation), len(relation)),
        (b"META", _pack_rows(_PAIR, metadata_rows), len(metadata_rows)),
        (b"FACT", _pack_rows(_U32, fact_refs), len(fact_refs)),
        (b"NODE", _pack_rows(_NODE_LITE, node_lite_rows), len(node_lite_rows)),
        (b"NDET", _pack_rows(_NODE_DETAIL, node_detail_rows), len(node_detail_rows)),
        (b"EDGE", _pack_rows(_EDGE, edge_rows), len(edge_rows)),
        (b"PRHD", pagerank_header, 1),
        (b"PRSC", _pack_rows(_PAGERANK_SCORE, pagerank_rows), len(pagerank_rows)),
        (b"RLHD", relation_header, 1),
        (b"XIDX", _pack_rows(_INDEX_REF, exact_index_rows), len(exact_index_rows)),
        (b"CALL", _pack_rows(_CALL, outgoing_call_rows), len(outgoing_call_rows)),
        (b"COFF", _call_offsets(outgoing_call_rows, node_count, 0), node_count + 1),
        (b"CIN0", _pack_rows(_CALL, incoming_call_rows), len(incoming_call_rows)),
        (b"CIOF", _call_offsets(incoming_call_rows, node_count, 1), node_count + 1),
    ]
    directory_size = len(raw_sections) * _DIRECTORY_ENTRY.size
    offset = _HEADER.size + directory_size
    entries: list[Section] = []
    for kind, payload, count in raw_sections:
        entries.append(Section(kind, offset, len(payload), count, zlib.crc32(payload)))
        offset += len(payload)
    directory = b"".join(
        _DIRECTORY_ENTRY.pack(entry.kind, entry.offset, entry.length, entry.count, entry.crc32)
        for entry in entries
    )

    handle = tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(_HEADER.pack(GGB4_MAGIC, len(entries), 0, zlib.crc32(directory)))
            handle.write(directory)
            for _kind, payload, _count in raw_sections:
                handle.write(payload)
            # Force the payload to disk before the rename publishes it. Without
            # this the directory entry can land ahead of the section bytes on a
            # crash, leaving a file whose header and CRCs promise data the store
            # does not actually contain.
            handle.flush()
            os.fsync(handle.fileno())
        # Readers of a .gg take no lock, and on Windows os.replace fails with
        # PermissionError while any reader holds a handle open. A bare replace
        # meant a scan that took minutes to build could be destroyed by a
        # transient reader: the except below would delete the staged file and
        # re-raise, losing the completed graph rather than the reader's read.
        replace_with_retry(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _parse_directory(data: bytes) -> SectionedDirectory:
    try:
        magic, section_count, _flags, expected_crc = _HEADER.unpack_from(data, 0)
    except struct.error as exc:
        raise ValueError("truncated GGB4 header") from exc
    if magic != GGB4_MAGIC:
        raise ValueError(f"unsupported sectioned graph magic/version: {magic!r}")
    if not 1 <= section_count <= _MAX_SECTIONS:
        raise ValueError(f"invalid GGB4 section count: {section_count}")
    directory_end = _HEADER.size + section_count * _DIRECTORY_ENTRY.size
    if directory_end > len(data):
        raise ValueError("truncated GGB4 section directory")
    raw_directory = data[_HEADER.size:directory_end]
    if zlib.crc32(raw_directory) != expected_crc:
        raise ValueError("GGB4 section-directory checksum mismatch")
    sections: dict[bytes, Section] = {}
    cursor = _HEADER.size
    expected_offset = directory_end
    for _ in range(section_count):
        kind, offset, length, count, checksum = _DIRECTORY_ENTRY.unpack_from(data, cursor)
        cursor += _DIRECTORY_ENTRY.size
        if kind in sections:
            raise ValueError(f"duplicate GGB4 section {kind!r}")
        if offset != expected_offset or offset + length > len(data):
            raise ValueError(f"invalid GGB4 section bounds for {kind!r}")
        sections[kind] = Section(kind, offset, length, count, checksum)
        expected_offset = offset + length
    if expected_offset != len(data):
        raise ValueError(f"unexpected GGB4 trailing bytes: {len(data) - expected_offset}")
    return SectionedDirectory(sections, len(data))


def _section(data: bytes, directory: SectionedDirectory, kind: bytes) -> tuple[bytes, int]:
    entry = directory.sections.get(kind)
    if entry is None:
        raise ValueError(f"missing required GGB4 section {kind!r}")
    payload = data[entry.offset:entry.offset + entry.length]
    if zlib.crc32(payload) != entry.crc32:
        raise ValueError(f"GGB4 section checksum mismatch for {kind!r}")
    return payload, entry.count


def _decode_strings(payload: bytes, count: int) -> list[str]:
    result: list[str] = []
    offset = 0
    try:
        for _ in range(count):
            length = _U32.unpack_from(payload, offset)[0]
            offset += _U32.size
            end = offset + length
            if end > len(payload):
                raise ValueError("truncated GGB4 string dictionary")
            result.append(payload[offset:end].decode("utf-8"))
            offset = end
    except (struct.error, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid GGB4 string dictionary: {exc}") from exc
    if offset != len(payload):
        raise ValueError(f"unexpected GGB4 string bytes: {len(payload) - offset}")
    return result


def _records(payload: bytes, count: int, record: struct.Struct) -> list[tuple]:
    if len(payload) != count * record.size:
        raise ValueError(
            f"GGB4 record section has {len(payload)} bytes; expected {count * record.size}"
        )
    return [record.unpack_from(payload, index * record.size) for index in range(count)]


def _iter_records(payload: bytes, count: int, record: struct.Struct):
    """Yield fixed records without allocating a second full tuple list."""

    if len(payload) != count * record.size:
        raise ValueError(
            f"GGB4 record section has {len(payload)} bytes; expected {count * record.size}"
        )
    for index in range(count):
        yield record.unpack_from(payload, index * record.size)


def load_sectioned_graph(path: Path) -> Graph:
    """Load every GGB4 section and materialize the compatibility Graph."""

    data = path.read_bytes()
    directory = _parse_directory(data)
    identity_payload, identity_count = _section(data, directory, b"IDS0")
    detail_payload, detail_count = _section(data, directory, b"DTS0")
    identity = _decode_strings(identity_payload, identity_count)
    detail = _decode_strings(detail_payload, detail_count)

    def identity_text(index: int) -> str:
        if not 0 <= index < len(identity):
            raise ValueError(f"invalid GGB4 identity string index {index}")
        return identity[index]

    def detail_text(index: int) -> str:
        if not 0 <= index < len(detail):
            raise ValueError(f"invalid GGB4 detail string index {index}")
        return detail[index]

    metadata_payload, metadata_count = _section(data, directory, b"META")
    metadata = {
        detail_text(key): detail_text(value)
        for key, value in _iter_records(metadata_payload, metadata_count, _PAIR)
    }
    fact_payload, fact_count = _section(data, directory, b"FACT")
    fact_refs = [row[0] for row in _iter_records(fact_payload, fact_count, _U32)]
    node_payload, node_count = _section(data, directory, b"NODE")
    detail_node_payload, detail_node_count = _section(data, directory, b"NDET")
    if node_count != detail_node_count:
        raise ValueError("GGB4 NODE/NDET record counts differ")
    nodes: dict[str, Node] = {}
    for lite, cold in zip(
        _iter_records(node_payload, node_count, _NODE_LITE),
        _iter_records(detail_node_payload, detail_node_count, _NODE_DETAIL),
        strict=True,
    ):
        id_idx, label, kind, node_path, _line, _role, active = lite
        summary, fact_start, node_fact_count, scope, parent, source, created, updated, confidence = cold
        if fact_start + node_fact_count > len(fact_refs):
            raise ValueError("invalid GGB4 node fact span")
        node_id = identity_text(id_idx)
        nodes[node_id] = Node(
            id=node_id,
            label=identity_text(label),
            kind=identity_text(kind) or "unknown",
            path=identity_text(node_path),
            summary=detail_text(summary),
            facts=tuple(detail_text(fact_refs[index]) for index in range(fact_start, fact_start + node_fact_count)),
            scope=detail_text(scope),
            parent=detail_text(parent),
            source=detail_text(source),
            confidence=float(confidence),
            active=bool(active),
            created_at=detail_text(created),
            updated_at=detail_text(updated),
        )

    edge_payload, edge_count = _section(data, directory, b"EDGE")
    edges = [
        Edge(
            source=identity_text(source),
            target=identity_text(target),
            type=identity_text(type_) or "dependency",
            weight=float(weight),
            confidence=float(confidence),
            provenance=detail_text(provenance) or "extracted",
            evidence=detail_text(evidence),
            source_location=detail_text(source_location),
            valid_from=detail_text(valid_from),
            valid_to=detail_text(valid_to),
            active=bool(active),
        )
        for (
            source, target, type_, provenance, evidence, source_location,
            valid_from, valid_to, weight, confidence, active,
        ) in _iter_records(edge_payload, edge_count, _EDGE)
    ]
    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)

    pagerank_header_payload, pagerank_header_count = _section(data, directory, b"PRHD")
    if pagerank_header_count != 1 or len(pagerank_header_payload) != _PAGERANK_HEADER.size:
        raise ValueError("invalid GGB4 PageRank header")
    signature, damping, max_iter, tolerance = _PAGERANK_HEADER.unpack(pagerank_header_payload)
    score_payload, score_count = _section(data, directory, b"PRSC")
    scores = {
        identity_text(node_id): float(score)
        for node_id, score in _iter_records(score_payload, score_count, _PAGERANK_SCORE)
    }
    if scores:
        graph.seed_pagerank_cache({
            "algorithm": _PAGERANK_ALGORITHM,
            "version": 1,
            "damping": float(damping),
            "max_iter": int(max_iter),
            "tol": float(detail_text(tolerance) or 1e-4),
            "signature": identity_text(signature),
            "scores": scores,
        }, trust_signature=True)
    # A full-store load is also the integrity-validation path. The partial
    # relation reader intentionally skips cold sections, but a complete load
    # must checksum the embedded derived relation sections even though the
    # compatibility Graph is reconstructed from EDGE.
    for relation_kind in (b"RLS0", b"RLHD", b"CALL"):
        _section(data, directory, relation_kind)
    for derived_kind in (b"IDOF", b"XIDX", b"COFF", b"CIN0", b"CIOF"):
        if derived_kind in directory.sections:
            _section(data, directory, derived_kind)
    return graph


def load_packed_relation_view(path: Path) -> PackedRelationView | None:
    """Load GGB4 exact indexes as raw buffers; return None for older GGB4 files."""

    directory = read_sectioned_directory(path)
    required = {b"IDOF", b"XIDX", b"COFF", b"CIN0", b"CIOF"}
    if not required <= directory.sections.keys():
        return None
    identity, identity_count = read_section(path, directory, b"IDS0")
    identity_offsets, offset_count = read_section(path, directory, b"IDOF")
    if offset_count != identity_count or len(identity_offsets) != identity_count * _U32.size:
        raise ValueError("invalid GGB4 identity offset index")
    relation_payload, relation_count = read_section(path, directory, b"RLS0")
    relation_strings = tuple(_decode_strings(relation_payload, relation_count))
    relation_header, relation_header_count = read_section(path, directory, b"RLHD")
    if relation_header_count != 1 or len(relation_header) != _RELATION_HEADER.size:
        raise ValueError("invalid GGB4 relation header")
    topology_status, topology_detail = _RELATION_HEADER.unpack(relation_header)
    if not 0 <= topology_status < len(relation_strings) or not 0 <= topology_detail < len(relation_strings):
        raise ValueError("invalid GGB4 relation header string index")
    node_rows, node_count = read_section(path, directory, b"NODE")
    exact_index, exact_index_count = read_section(path, directory, b"XIDX")
    outgoing_calls, outgoing_count = read_section(path, directory, b"CALL")
    outgoing_offsets, outgoing_offset_count = read_section(path, directory, b"COFF")
    incoming_calls, incoming_count = read_section(path, directory, b"CIN0")
    incoming_offsets, incoming_offset_count = read_section(path, directory, b"CIOF")
    if outgoing_count != incoming_count:
        raise ValueError("GGB4 forward/reverse call counts disagree")
    if len(node_rows) != node_count * _NODE_LITE.size:
        raise ValueError("invalid GGB4 packed node section")
    if len(outgoing_calls) != outgoing_count * _CALL.size:
        raise ValueError("invalid GGB4 outgoing call section")
    if len(incoming_calls) != incoming_count * _CALL.size:
        raise ValueError("invalid GGB4 incoming call section")
    if outgoing_offset_count != node_count + 1 or incoming_offset_count != node_count + 1:
        raise ValueError("invalid GGB4 call offset index")
    if len(exact_index) != exact_index_count * _INDEX_REF.size:
        raise ValueError("invalid GGB4 exact symbol index")
    if len(outgoing_offsets) != outgoing_offset_count * _U32.size:
        raise ValueError("invalid GGB4 outgoing call offsets")
    if len(incoming_offsets) != incoming_offset_count * _U32.size:
        raise ValueError("invalid GGB4 incoming call offsets")
    return PackedRelationView(
        topology_status=relation_strings[topology_status],
        topology_detail=relation_strings[topology_detail],
        identity=identity,
        identity_offsets=identity_offsets,
        node_rows=node_rows,
        node_count=node_count,
        exact_index=exact_index,
        exact_index_count=exact_index_count,
        outgoing_calls=outgoing_calls,
        outgoing_offsets=outgoing_offsets,
        incoming_calls=incoming_calls,
        incoming_offsets=incoming_offsets,
        relation_strings=relation_strings,
    )


def load_sectioned_relation_view(path: Path) -> SectionedRelationView:
    """Load only GGB4 identity and exact-call sections."""

    directory = read_sectioned_directory(path)
    identity_payload, identity_count = read_section(path, directory, b"IDS0")
    relation_payload, relation_count = read_section(path, directory, b"RLS0")
    identity = _decode_strings(identity_payload, identity_count)
    relation = _decode_strings(relation_payload, relation_count)

    def identity_text(index: int) -> str:
        if not 0 <= index < len(identity):
            raise ValueError(f"invalid GGB4 identity string index {index}")
        return identity[index]

    def relation_text(index: int) -> str:
        if not 0 <= index < len(relation):
            raise ValueError(f"invalid GGB4 relation string index {index}")
        return relation[index]

    node_payload, node_count = read_section(path, directory, b"NODE")
    nodes: list[RelationNode] = []
    numeric_remap: dict[int, int] = {}
    for stored_n, row in enumerate(_iter_records(node_payload, node_count, _NODE_LITE)):
        id_idx, label, kind, node_path, line, role, active = row
        if not active:
            continue
        numeric_remap[stored_n] = len(nodes)
        nodes.append(RelationNode(
            id=identity_text(id_idx),
            label=identity_text(label),
            kind=identity_text(kind),
            path=identity_text(node_path),
            line=None if line < 0 else line,
            role=identity_text(role),
        ))

    relation_header, relation_header_count = read_section(path, directory, b"RLHD")
    if relation_header_count != 1 or len(relation_header) != _RELATION_HEADER.size:
        raise ValueError("invalid GGB4 relation header")
    topology_status, topology_detail = _RELATION_HEADER.unpack(relation_header)
    call_payload, call_count = read_section(path, directory, b"CALL")
    calls: list[RelationCall] = []
    for source_n, target_n, confidence, provenance, location, evidence, edge_count in _iter_records(
        call_payload, call_count, _CALL
    ):
        if source_n not in numeric_remap or target_n not in numeric_remap:
            raise ValueError("GGB4 relation endpoint does not name an active node")
        calls.append(RelationCall(
            source_n=numeric_remap[source_n],
            target_n=numeric_remap[target_n],
            confidence=float(confidence),
            provenance=relation_text(provenance),
            source_location=relation_text(location),
            evidence=relation_text(evidence),
            edge_count=edge_count,
        ))
    incoming_lists: dict[int, list[RelationCall]] = {}
    outgoing_lists: dict[int, list[RelationCall]] = {}
    for call in calls:
        incoming_lists.setdefault(call.target_n, []).append(call)
        outgoing_lists.setdefault(call.source_n, []).append(call)
    return SectionedRelationView(
        topology_status=relation_text(topology_status),
        topology_detail=relation_text(topology_detail),
        nodes=tuple(nodes),
        calls=tuple(calls),
        by_id={node.id: index for index, node in enumerate(nodes)},
        incoming={key: tuple(value) for key, value in incoming_lists.items()},
        outgoing={key: tuple(value) for key, value in outgoing_lists.items()},
    )


def read_sectioned_directory(path: Path) -> SectionedDirectory:
    """Read and validate the small GGB4 header/directory only."""

    with path.open("rb") as handle:
        header = handle.read(_HEADER.size)
        try:
            magic, section_count, _flags, expected_crc = _HEADER.unpack(header)
        except struct.error as exc:
            raise ValueError("truncated GGB4 header") from exc
        if magic != GGB4_MAGIC or not 1 <= section_count <= _MAX_SECTIONS:
            raise ValueError("unsupported or invalid GGB4 header")
        raw_directory = handle.read(section_count * _DIRECTORY_ENTRY.size)
        if len(raw_directory) != section_count * _DIRECTORY_ENTRY.size:
            raise ValueError("truncated GGB4 section directory")
        if zlib.crc32(raw_directory) != expected_crc:
            raise ValueError("GGB4 section-directory checksum mismatch")
        file_size = path.stat().st_size
        sections: dict[bytes, Section] = {}
        expected_offset = _HEADER.size + len(raw_directory)
        for index in range(section_count):
            kind, offset, length, count, checksum = _DIRECTORY_ENTRY.unpack_from(
                raw_directory, index * _DIRECTORY_ENTRY.size
            )
            if kind in sections or offset != expected_offset or offset + length > file_size:
                raise ValueError(f"invalid GGB4 section bounds for {kind!r}")
            sections[kind] = Section(kind, offset, length, count, checksum)
            expected_offset = offset + length
        if expected_offset != file_size:
            raise ValueError(f"unexpected GGB4 trailing bytes: {file_size - expected_offset}")
        return SectionedDirectory(sections, file_size)


def read_section(path: Path, directory: SectionedDirectory, kind: bytes) -> tuple[bytes, int]:
    """Read and checksum one named GGB4 section without loading the file."""

    entry = directory.sections.get(kind)
    if entry is None:
        raise ValueError(f"missing required GGB4 section {kind!r}")
    with path.open("rb") as handle:
        handle.seek(entry.offset)
        payload = handle.read(entry.length)
    if len(payload) != entry.length or zlib.crc32(payload) != entry.crc32:
        raise ValueError(f"GGB4 section checksum mismatch for {kind!r}")
    return payload, entry.count


__all__ = [
    "GGB4_MAGIC",
    "Section",
    "SectionedDirectory",
    "RelationCall",
    "RelationNode",
    "PackedRelationView",
    "SectionedRelationView",
    "is_sectioned_graph",
    "load_sectioned_graph",
    "load_packed_relation_view",
    "load_sectioned_relation_view",
    "read_section",
    "read_sectioned_directory",
    "save_sectioned_graph",
]
