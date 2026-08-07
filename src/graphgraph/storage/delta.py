"""Append-delta store for cheaper incremental saves (T15).

This is the *promoted* incremental writer: :func:`save_incremental_validated_graph`
is wired into ``services.lifecycle`` and :func:`apply_delta_sidecar` into
``io.core.load_any``. It is not a bypass of the cycle 5-8 data-loss guards -- an
invalid graph never appends, and every case the delta cannot safely handle (a
large update, a torn/damaged sidecar, a non-native store, or the compaction
threshold) falls back to the canonical atomic full rewrite. The full rewrite is
therefore still the safety and compaction path, not a second weaker writer.

Cost model (measured, honestly)
-------------------------------
Let ``N`` be the base graph size (nodes + edges), ``Δ`` the records one update
touches, and ``k`` the deltas since the last compaction.

* Full-rewrite ``.gg``: every update pays ``load O(N) + save O(N)`` -- on the
  8.4k-node / 30.9k-edge self-graph, ~124 ms uncached load + ~76 ms validated
  save, independent of Δ.
* The *append itself* is genuinely ``O(Δ)``: ``append_delta`` of a one-node change
  measures ~0.35 ms versus ~70 ms for a full ``save_graph`` (~200x on that step
  alone).
* But the *promoted lifecycle* around it is not yet O(Δ): today it obtains the
  delta with :meth:`GraphDelta.between`, which diffs two fully materialized graphs
  (``O(N)``), and validates the new graph (``O(N)``). End-to-end that measures
  ~58 ms delta-save versus ~264 ms full save -- a real but modest **~4.5x**, not
  200x. The remaining ``O(N)`` terms are the diff and validation, not the write;
  a scanner that emitted the delta directly (rather than reconstructing it by
  comparing two whole graphs) would remove them.

A load is inherently ``Θ(N)`` because a :class:`Graph` is materialized in full
everywhere -- replay only removes the ``O(N)`` term from *save*, never from load.
Replay itself is ``O(E + Δ)`` per record: :func:`_apply` batches a record's edge
deletes, tombstones, and upserts into a single pass over the edge list rather than
re-filtering it once per changed edge.

Crash safety
------------
Each delta record is ``MAGIC | u32 length | u32 crc32 | payload``. A load replays
records until the first short read or crc mismatch (a torn tail from an
interrupted append) and returns the base plus every intact delta -- the base
``.gg`` is never mutated except by an atomic compaction, so a crashed append can
never corrupt the last good graph.
"""

from __future__ import annotations

import json
import struct
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from ..io.core import load_any, save_graph, save_validated_graph
from ..packets.validation import ValidationResult, validate_graph_object
from ..runtime.state import file_lock, replace_with_retry

_DELTA_MAGIC = b"GGD1"
_RECORD_HEADER = struct.Struct("<4sII")  # magic, payload_len, crc32

_NODE_FIELDS = (
    "id", "label", "kind", "path", "summary", "facts", "scope", "parent",
    "source", "confidence", "active", "created_at", "updated_at",
)
_EDGE_FIELDS = (
    "source", "target", "type", "weight", "confidence", "provenance",
    "evidence", "source_location", "valid_from", "valid_to", "active",
)


def delta_sidecar_path(base_path: Path) -> Path:
    return base_path.with_name(base_path.name + ".delta")


def _node_to_dict(node: Node) -> dict:
    data = {name: getattr(node, name) for name in _NODE_FIELDS}
    data["facts"] = list(node.facts)
    return data


def _edge_to_dict(edge: Edge) -> dict:
    return {name: getattr(edge, name) for name in _EDGE_FIELDS}


def _node_from_dict(data: dict) -> Node:
    return Node(**{**data, "facts": tuple(data.get("facts", ()))})


def _edge_from_dict(data: dict) -> Edge:
    return Edge(**data)


@dataclass
class GraphDelta:
    """One incremental change: node/edge upserts plus tombstones.

    Edge identity includes ``source_location``. This lets a file-scoped splice
    replace the observation owned by one source location without deleting a
    parallel observation of the same relation from another file.
    """

    upsert_nodes: list[Node] = field(default_factory=list)
    delete_node_ids: list[str] = field(default_factory=list)
    upsert_edges: list[Edge] = field(default_factory=list)
    delete_edge_keys: list[tuple[str, str, str, str]] = field(default_factory=list)
    metadata: dict[str, str] | None = None

    def is_empty(self) -> bool:
        return not (
            self.upsert_nodes or self.delete_node_ids
            or self.upsert_edges or self.delete_edge_keys
            or self.metadata is not None
        )

    @classmethod
    def between(cls, previous: Graph, current: Graph) -> GraphDelta:
        """Exact delta whose replay over *previous* equals *current*."""

        previous_edges = {_edge_key(edge): edge for edge in previous.edges}
        current_edges = {_edge_key(edge): edge for edge in current.edges}
        delete_edge_keys = [
            key
            for key, edge in previous_edges.items()
            if key not in current_edges or current_edges[key] != edge
        ]
        upsert_edges = [
            edge
            for key, edge in current_edges.items()
            if key not in previous_edges or previous_edges[key] != edge
        ]
        return cls(
            upsert_nodes=[
                node
                for node_id, node in current.nodes.items()
                if previous.nodes.get(node_id) != node
            ],
            delete_node_ids=[
                node_id for node_id in previous.nodes if node_id not in current.nodes
            ],
            upsert_edges=upsert_edges,
            delete_edge_keys=delete_edge_keys,
            metadata=(
                dict(current.metadata)
                if previous.metadata != current.metadata
                else None
            ),
        )


def _edge_key(edge: Edge) -> tuple[str, str, str, str]:
    return (edge.source, edge.target, edge.type, edge.source_location)


def _encode(delta: GraphDelta) -> bytes:
    payload = json.dumps(
        {
            "upsert_nodes": [_node_to_dict(n) for n in delta.upsert_nodes],
            "delete_node_ids": list(delta.delete_node_ids),
            "upsert_edges": [_edge_to_dict(e) for e in delta.upsert_edges],
            "delete_edge_keys": [list(k) for k in delta.delete_edge_keys],
            "metadata": delta.metadata,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return _RECORD_HEADER.pack(_DELTA_MAGIC, len(payload), zlib.crc32(payload)) + payload


def _append_delta_unlocked(base_path: Path, delta: GraphDelta) -> Path:
    if delta.is_empty():
        return delta_sidecar_path(base_path)
    sidecar = delta_sidecar_path(base_path)
    with sidecar.open("ab") as fh:
        fh.write(_encode(delta))
        fh.flush()
    return sidecar


def append_delta(base_path: Path, delta: GraphDelta) -> Path:
    """Append one serialized delta record (O(Δ)); never touches the base."""

    sidecar = delta_sidecar_path(base_path)
    with file_lock(sidecar):
        return _append_delta_unlocked(base_path, delta)


def _iter_intact_records(data: bytes):
    offset = 0
    n = len(data)
    while offset + _RECORD_HEADER.size <= n:
        magic, length, crc = _RECORD_HEADER.unpack_from(data, offset)
        start = offset + _RECORD_HEADER.size
        end = start + length
        if magic != _DELTA_MAGIC or end > n:
            return  # torn tail: stop, keep everything intact so far
        payload = data[start:end]
        if zlib.crc32(payload) != crc:
            return  # corrupted record: stop cleanly
        yield json.loads(payload.decode("utf-8"))
        offset = end


def _apply(nodes: dict[str, Node], edges: list[Edge], record: dict) -> None:
    """Apply one delta record in a single ``O(E + Δ)`` pass over the edge list.

    Filtering the whole edge list once per changed edge (the earlier shape) is
    ``O(E · Δ)`` -- ~443 ms to replay 100 changed edges over 30k. This batches a
    record's node tombstones, edge-key deletes, and edge upserts into one keyed
    pass, so a 100-edge record costs one traversal, not a hundred.
    """
    for raw in record.get("upsert_nodes", ()):
        node = _node_from_dict(raw)
        nodes[node.id] = node
    deleted_nodes = set(record.get("delete_node_ids", ()))
    for node_id in deleted_nodes:
        nodes.pop(node_id, None)

    deleted_keys: set[tuple[str, str, str, str]] = set()
    # GGD1 prototype records used three-field keys. Keep them readable while all
    # new records carry location-aware identity.
    legacy_deletes: set[tuple[str, str, str]] = set()
    for key in record.get("delete_edge_keys", ()):
        s, t, ty, *location = key
        if location:
            deleted_keys.add((s, t, ty, location[0]))
        else:
            legacy_deletes.add((s, t, ty))

    # Upserts are keyed last-wins, matching the prior sequential replace-append.
    upsert_by_key: dict[tuple[str, str, str, str], Edge] = {}
    for raw in record.get("upsert_edges", ()):
        edge = _edge_from_dict(raw)
        upsert_by_key[_edge_key(edge)] = edge

    if deleted_nodes or deleted_keys or legacy_deletes or upsert_by_key:
        kept: list[Edge] = []
        for edge in edges:
            if edge.source in deleted_nodes or edge.target in deleted_nodes:
                continue
            key = _edge_key(edge)
            if key in deleted_keys or key in upsert_by_key:
                continue
            if legacy_deletes and (edge.source, edge.target, edge.type) in legacy_deletes:
                continue
            kept.append(edge)
        kept.extend(upsert_by_key.values())
        edges[:] = kept


def load_with_deltas(base_path: Path) -> Graph:
    """Base ``.gg`` plus every intact appended delta, replayed in order."""
    base = load_any(base_path, _include_deltas=False)
    return apply_delta_sidecar(base, base_path)


def apply_delta_sidecar(base: Graph, base_path: Path) -> Graph:
    """Replay a sidecar onto an already-loaded base graph.

    A sidecar is only applied when it is strictly newer than its base. A full
    rewrite (compaction) writes the base *after* folding the deltas in, so if it
    is interrupted before unlinking the sidecar, the leftover records predate the
    new base and replaying them would double-apply already-folded changes. The
    ``mtime`` guard is the crash-safe backstop for that window; the writers also
    unlink the sidecar explicitly on the happy path.
    """

    sidecar = delta_sidecar_path(base_path)
    if not sidecar.exists():
        return base
    try:
        # Skip only when the base is *strictly* newer than the sidecar: a full
        # rewrite advances the base mtime past the last append. Equal timestamps
        # (a coarse-resolution filesystem where an append lands in the same tick
        # as its base write) favor applying, since dropping a valid delta is
        # worse than the vanishingly rare same-tick crash-window replay.
        if sidecar.stat().st_mtime_ns < base_path.stat().st_mtime_ns:
            return base  # stale: base was rewritten after this sidecar's records
    except OSError:
        pass
    nodes = dict(base.nodes)
    edges = list(base.edges)
    metadata = dict(base.metadata)
    for record in _iter_intact_records(sidecar.read_bytes()):
        _apply(nodes, edges, record)
        replacement = record.get("metadata")
        if replacement is not None:
            metadata = {str(key): str(value) for key, value in replacement.items()}
    return Graph(nodes=nodes, edges=edges, metadata=metadata)


def _intact_record_count(data: bytes) -> tuple[int, bool]:
    """Return intact record count and whether the byte stream ends cleanly."""

    count = 0
    offset = 0
    while offset + _RECORD_HEADER.size <= len(data):
        magic, length, crc = _RECORD_HEADER.unpack_from(data, offset)
        start = offset + _RECORD_HEADER.size
        end = start + length
        if magic != _DELTA_MAGIC or end > len(data):
            return count, False
        payload = data[start:end]
        if zlib.crc32(payload) != crc:
            return count, False
        count += 1
        offset = end
    return count, offset == len(data)


def save_incremental_validated_graph(
    previous: Graph,
    current: Graph,
    base_path: Path,
    *,
    max_delta_ratio: float = 0.25,
    max_records: int = 64,
) -> ValidationResult:
    """Persist an update as a delta when the measured cost model favors it.

    Invalid graphs never append. Large updates, damaged/torn sidecars, non-native
    stores, and compaction thresholds all fall back to the canonical atomic full
    rewrite. Thus the promoted lifecycle keeps the existing safety path as its
    repair/compaction path rather than maintaining a second weaker writer.
    """

    result = validate_graph_object(current, format_name="graph.gg")
    if not result.ok:
        raise ValueError(
            "Refusing to write invalid native graph: "
            + "; ".join(result.errors[:5])
            + (f"; ... {len(result.errors) - 5} more" if len(result.errors) > 5 else "")
        )
    if base_path.suffix.lower() != ".gg" or not base_path.exists():
        return save_validated_graph(current, base_path)

    delta = GraphDelta.between(previous, current)
    if delta.is_empty():
        return result
    sidecar = delta_sidecar_path(base_path)
    with file_lock(sidecar):
        encoded_size = len(_encode(delta))
        base_size = max(1, base_path.stat().st_size)
        sidecar_data = sidecar.read_bytes() if sidecar.exists() else b""
        record_count, sidecar_intact = _intact_record_count(sidecar_data)
        projected_size = len(sidecar_data) + encoded_size
        if (
            not sidecar_intact
            or encoded_size >= base_size * max_delta_ratio
            or projected_size >= base_size * max_delta_ratio
            or record_count >= max_records
        ):
            # This is a compaction: `current` is the complete graph, so writing
            # it as the new base makes every accumulated delta record stale.
            # `save_validated_graph` -> `save_gg` clears the sidecar as part of a
            # full base rewrite (its single clearing point), and the mtime guard
            # in `apply_delta_sidecar` is the crash-safe backstop.
            return save_validated_graph(current, base_path)

        _append_delta_unlocked(base_path, delta)
    return result


def compact(base_path: Path) -> Graph:
    """Fold deltas into the base ``.gg`` atomically, then drop the sidecar."""
    sidecar = delta_sidecar_path(base_path)
    with file_lock(sidecar):
        merged = load_with_deltas(base_path)
        tmp = Path(
            tempfile.NamedTemporaryFile(
                dir=base_path.parent, prefix=f".{base_path.name}.", suffix=".gg", delete=False
            ).name
        )
        try:
            save_graph(merged, tmp)
            # Same reader-vs-rename hazard as the graph writer: on Windows a
            # reader holding the base .gg open makes a bare replace raise, and
            # the handler below would then discard the already-merged result.
            replace_with_retry(tmp, base_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        sidecar.unlink(missing_ok=True)
        return merged
