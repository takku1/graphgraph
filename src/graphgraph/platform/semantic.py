from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from pathlib import Path
from threading import RLock

from ..graph.core import Graph, Node
from .persistence import atomic_write_json

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")
_INDEX_CACHE_LIMIT = 4
_INDEX_CACHE: OrderedDict[Path, tuple[int, int, "SemanticIndex"]] = OrderedDict()
_INDEX_CACHE_LOCK = RLock()


class SemanticIndex:
    """Dependency-free hashed vector index used only when lexical retrieval is weak."""

    def __init__(self, path: Path | None = None, *, dimensions: int = 2048) -> None:
        self.path = path
        self.dimensions = max(32, dimensions)
        self.vectors: dict[str, dict[int, float]] = {}
        self.signature = ""

    def build(self, graph: Graph) -> "SemanticIndex":
        self.vectors = {
            node.id: _vector(_node_text(node), self.dimensions)
            for node in graph.nodes.values()
            if node.active
        }
        self.signature = _graph_signature(graph)
        if self.path:
            self.save()
        return self

    def query(self, text: str, *, limit: int = 10, threshold: float = 0.05) -> list[tuple[str, float]]:
        query_vector = _vector(text, self.dimensions)
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
            "version": 2,
            "dimensions": self.dimensions,
            "signature": self.signature,
            "vectors": {node_id: {str(key): value for key, value in vector.items()} for node_id, vector in self.vectors.items()},
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
        index.vectors = {
            str(node_id): {int(key): float(value) for key, value in vector.items()}
            for node_id, vector in data.get("vectors", {}).items()
        }
        _remember_index(resolved, index)
        return index

    def is_current(self, graph: Graph) -> bool:
        return bool(self.signature) and self.signature == _graph_signature(graph)


def _node_text(node: Node) -> str:
    return " ".join((node.label, node.kind, node.path, node.summary, *node.facts))


def _graph_signature(graph: Graph) -> str:
    digest = hashlib.sha256()
    for node in sorted(graph.nodes.values(), key=lambda item: item.id):
        if node.active:
            digest.update(f"{node.id}\0{_node_text(node)}\n".encode("utf-8"))
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


def _remember_index(path: Path, index: SemanticIndex) -> None:
    resolved = path.resolve()
    stat = resolved.stat()
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, index)
        _INDEX_CACHE.move_to_end(resolved)
        while len(_INDEX_CACHE) > _INDEX_CACHE_LIMIT:
            _INDEX_CACHE.popitem(last=False)
