from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import struct
import warnings
from collections import OrderedDict
from pathlib import Path
from threading import RLock

from ..graph.core import Graph, Node
from .embeddings import (
    HASH_BACKEND_NAME,
    EmbeddingBackend,
    active_backend_name,
    normalize_dense,
    resolve_backend,
)
from .persistence import atomic_write_json


class SemanticBackendMismatch(ValueError):
    """An index built by one backend was queried through another.

    The offline hash space and any embedding space are unrelated coordinate
    systems; scoring a query from one against vectors from the other yields
    confident nonsense. Refusing is the only safe response -- the caller should
    rebuild the index under the active backend.
    """

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")
_INDEX_CACHE_LIMIT = 4
_INDEX_CACHE: OrderedDict[Path, tuple[int, int, "SemanticIndex"]] = OrderedDict()
_INDEX_CACHE_LOCK = RLock()
_INDEX_METADATA_PREFIX_CHARS = 16_384
_VECTOR_RECORD = struct.Struct("<If")
_VECTOR_ENCODING = "base85-u32-f32-le"
_INDEX_VERSION = 4
_TRANSACTION_POLICY = "graph-version-coupled-v1"


class SemanticIndex:
    """Dependency-free hashed vector index used only when lexical retrieval is weak."""

    def __init__(self, path: Path | None = None, *, dimensions: int = 2048) -> None:
        self.path = path
        self.dimensions = max(32, dimensions)
        self.vectors: dict[str, dict[int, float]] = {}
        self.signature = ""
        self.graph_version = ""
        self.transaction_policy = _TRANSACTION_POLICY
        # Which backend produced these vectors. "hash" is the offline default;
        # any other value is an embedding space and must be queried through the
        # same backend. Set on build/load, checked on query.
        self.backend_name = HASH_BACKEND_NAME

    def build(self, graph: Graph, *, backend: EmbeddingBackend | None = None) -> "SemanticIndex":
        active = backend if backend is not None else resolve_backend()
        nodes = [node for node in graph.nodes.values() if node.active]
        dense: list | None = None
        if active is not None:
            # One batched call, not one request per node: the offline path is
            # free but a network backend is not, and per-node calls made a
            # large repo unusably slow.
            try:
                dense = active.embed([_node_text(node) for node in nodes])
            except Exception as exc:  # noqa: BLE001
                # A real backend can fail at runtime -- an offline first-use model
                # download, an unreachable embedding endpoint. Degrade to the
                # offline hash index rather than crashing the scan or query; the
                # index records `backend_name = hash`, so provenance stays honest
                # and a later query against a real backend rebuilds rather than
                # scoring across incompatible vector spaces.
                warnings.warn(
                    f"embedding backend {active.name!r} failed ({exc}); "
                    "falling back to the offline hash index",
                    RuntimeWarning,
                    stacklevel=2,
                )
                active = None
        if active is not None and dense is not None:
            self.vectors = {
                node.id: normalize_dense(vector)
                for node, vector in zip(nodes, dense)
            }
            self.backend_name = active.name
        else:
            self.vectors = {
                node.id: _vector(_node_text(node), self.dimensions)
                for node in nodes
            }
            self.backend_name = HASH_BACKEND_NAME
        self.signature = _graph_signature(graph)
        self.graph_version = _graph_version(graph)
        if self.path:
            self.save()
        return self

    def _query_vector(self, text: str, backend: EmbeddingBackend | None) -> dict[int, float]:
        if self.backend_name == HASH_BACKEND_NAME:
            return _vector(text, self.dimensions)
        active = backend if backend is not None else resolve_backend()
        if active is None or active.name != self.backend_name:
            raise SemanticBackendMismatch(
                f"index was built by backend {self.backend_name!r} but the "
                f"active backend is {active_backend_name()!r}; rebuild the "
                "semantic index under the active backend before querying"
            )
        return normalize_dense(active.embed([text])[0])

    def query(
        self,
        text: str,
        *,
        limit: int = 10,
        threshold: float = 0.05,
        backend: EmbeddingBackend | None = None,
    ) -> list[tuple[str, float]]:
        query_vector = self._query_vector(text, backend)
        scored = [
            (node_id, _cosine(query_vector, vector))
            for node_id, vector in self.vectors.items()
        ]
        scored = [item for item in scored if item[1] >= threshold]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:max(0, limit)]

    def save(self) -> None:
        if not self.path:
            raise ValueError("SemanticIndex.save requires a path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _INDEX_VERSION,
            "dimensions": self.dimensions,
            "signature": self.signature,
            "graph_version": self.graph_version,
            "transaction_policy": self.transaction_policy,
            "backend": self.backend_name,
            "vector_encoding": _VECTOR_ENCODING,
            "vectors": {
                node_id: _encode_vector(vector)
                for node_id, vector in self.vectors.items()
            },
        }
        atomic_write_json(self.path, data, indent=None)
        _remember_index(self.path, self)

    @classmethod
    def load(cls, path: Path) -> "SemanticIndex":
        resolved = path.resolve()
        stat = resolved.stat()
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        with _INDEX_CACHE_LOCK:
            cached = _INDEX_CACHE.get(resolved)
            if cached is not None and cached[:2] == fingerprint:
                _INDEX_CACHE.move_to_end(resolved)
                return cached[2]
        data = json.loads(resolved.read_text(encoding="utf-8"))
        index = cls(path, dimensions=int(data.get("dimensions", 2048)))
        index.signature = str(data.get("signature", ""))
        index.graph_version = str(data.get("graph_version", ""))
        index.transaction_policy = str(data.get("transaction_policy", ""))
        # Pre-backend indexes carry no "backend" key; they are hash indexes.
        index.backend_name = str(data.get("backend", HASH_BACKEND_NAME))
        vectors = data.get("vectors", {})
        if int(data.get("version", 0)) >= 3:
            if data.get("vector_encoding") != _VECTOR_ENCODING:
                raise ValueError(
                    f"unsupported semantic vector encoding: {data.get('vector_encoding')!r}"
                )
            index.vectors = {
                str(node_id): _decode_vector(str(vector))
                for node_id, vector in vectors.items()
            }
        else:
            index.vectors = {
                str(node_id): {int(key): float(value) for key, value in vector.items()}
                for node_id, vector in vectors.items()
            }
        _remember_index(resolved, index)
        return index

    @classmethod
    def state_for_graph(cls, path: Path, graph: Graph) -> str:
        """Classify an on-disk index without decoding its vector payload.

        A dense semantic sidecar can be tens of megabytes. The query planner
        only needs the signature and backend to decide whether that sidecar is
        usable; loading every vector merely to discover staleness turns a cheap
        guard into another cold-start cost. ``save`` writes metadata before the
        final ``vectors`` field, so reading a bounded prefix is sufficient for
        every index version GraphGraph has emitted.
        """
        if not path.exists():
            return "missing"
        try:
            metadata = cls._load_metadata(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return "invalid"
        current = (
            int(metadata.get("version", 0)) >= _INDEX_VERSION
            and metadata.get("transaction_policy") == _TRANSACTION_POLICY
            and bool(metadata.get("signature"))
            and str(metadata["signature"]) == _graph_signature(graph)
            and bool(metadata.get("graph_version"))
            and str(metadata["graph_version"]) == _graph_version(graph)
            and str(metadata.get("backend", HASH_BACKEND_NAME))
            == active_backend_name()
        )
        return "current" if current else "stale"

    @staticmethod
    def _load_metadata(path: Path) -> dict[str, object]:
        with path.open("r", encoding="utf-8") as stream:
            prefix = stream.read(_INDEX_METADATA_PREFIX_CHARS)
        marker = re.search(r'"vectors"\s*:', prefix)
        if marker is None:
            raise ValueError("semantic index metadata exceeds bounded prefix")
        # ``vectors`` is the final field in every emitted format. Replace its
        # omitted payload with an empty object to parse metadata with the JSON
        # decoder instead of maintaining a second, escape-sensitive parser.
        return json.loads(prefix[: marker.end()] + "{}}")

    def is_current(self, graph: Graph) -> bool:
        # Stale if the graph changed OR the active backend differs from the one
        # that built the vectors -- an index carried across a backend switch is
        # not reusable, and treating it as current would trip the query-time
        # mismatch guard on every call.
        return (
            bool(self.signature)
            and self.signature == _graph_signature(graph)
            and bool(self.graph_version)
            and self.graph_version == _graph_version(graph)
            and self.transaction_policy == _TRANSACTION_POLICY
            and self.backend_name == active_backend_name()
        )


def _node_text(node: Node) -> str:
    return " ".join((node.label, node.kind, node.path, node.summary, *node.facts))


def _graph_signature(graph: Graph) -> str:
    digest = hashlib.sha256()
    for node in sorted(graph.nodes.values(), key=lambda item: item.id):
        if node.active:
            digest.update(f"{node.id}\0{_node_text(node)}\n".encode("utf-8"))
    return digest.hexdigest()


def _graph_version(graph: Graph) -> str:
    """Fingerprint the complete active graph transaction.

    The semantic vectors depend only on node text, but retrieval combines their
    seeds with graph traversal. Coupling the sidecar to active topology prevents
    a reader from mixing vectors built for one graph with edges from another.
    """
    digest = hashlib.sha256()
    digest.update(f"nodes:{_graph_signature(graph)}\n".encode("utf-8"))
    active_nodes = {node.id for node in graph.nodes.values() if node.active}
    for edge in sorted(
        (
            edge
            for edge in graph.edges
            if edge.active and edge.source in active_nodes and edge.target in active_nodes
        ),
        key=lambda item: (
            item.source,
            item.target,
            item.type,
            item.weight,
            item.confidence,
            item.provenance,
            item.evidence,
            item.source_location,
        ),
    ):
        record = (
            edge.source,
            edge.target,
            edge.type,
            format(edge.weight, ".17g"),
            format(edge.confidence, ".17g"),
            edge.provenance,
            edge.evidence,
            edge.source_location,
        )
        digest.update(("\0".join(record) + "\n").encode("utf-8"))
    return digest.hexdigest()


def _terms(text: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", "-")
    return [term.casefold() for term in _TOKEN_RE.findall(expanded)]


def _vector(text: str, dimensions: int) -> dict[int, float]:
    vector: dict[int, float] = {}
    terms = _terms(text)
    features = terms + [f"{left}:{right}" for left, right in zip(terms, terms[1:])]
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "little")
        index = raw % dimensions
        sign = 1.0 if raw & (1 << 63) else -1.0
        vector[index] = vector.get(index, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
    return {key: value / norm for key, value in vector.items()}


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def _encode_vector(vector: dict[int, float]) -> str:
    packed = b"".join(
        _VECTOR_RECORD.pack(index, value)
        for index, value in sorted(vector.items())
    )
    return base64.b85encode(packed).decode("ascii")


def _decode_vector(encoded: str) -> dict[int, float]:
    packed = base64.b85decode(encoded.encode("ascii"))
    if len(packed) % _VECTOR_RECORD.size:
        raise ValueError("invalid semantic vector payload length")
    return {
        index: float(value)
        for index, value in _VECTOR_RECORD.iter_unpack(packed)
    }


def _remember_index(path: Path, index: SemanticIndex) -> None:
    resolved = path.resolve()
    stat = resolved.stat()
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, index)
        _INDEX_CACHE.move_to_end(resolved)
        while len(_INDEX_CACHE) > _INDEX_CACHE_LIMIT:
            _INDEX_CACHE.popitem(last=False)
