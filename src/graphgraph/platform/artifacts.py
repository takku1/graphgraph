"""Content-addressed compiler artifacts and bounded analysis reuse."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import astuple, dataclass
from typing import Generic, TypeVar

from ..graph.core import Graph

GRAPH_NODES = "graph.nodes"
GRAPH_EDGES = "graph.edges"
GRAPH_METADATA = "graph.metadata"
GRAPH_ARTIFACTS = (GRAPH_NODES, GRAPH_EDGES, GRAPH_METADATA)


@dataclass(frozen=True)
class ArtifactFingerprint:
    """Revision and content identity of one semantic graph component."""

    artifact: str
    revision: int | str
    digest: str


@dataclass(frozen=True)
class AnalysisKey:
    """Complete identity of a deterministic compiler-pass application."""

    pass_name: str
    pass_version: str
    parameters: tuple[tuple[str, object], ...]
    inputs: tuple[ArtifactFingerprint, ...]

    @property
    def digest(self) -> str:
        payload = (
            self.pass_name,
            self.pass_version,
            self.parameters,
            tuple((item.artifact, item.revision, item.digest) for item in self.inputs),
        )
        return _digest(payload)


class ArtifactIndex:
    """Fingerprint graph components once per relevant mutation revision."""

    def __init__(self, *, max_entries: int = 128) -> None:
        self.max_entries = max(1, max_entries)
        self._cache: OrderedDict[tuple[int, str, int], tuple[Graph, str]] = OrderedDict()

    def fingerprints(
        self,
        graph: Graph,
        artifacts: tuple[str, ...],
    ) -> tuple[ArtifactFingerprint, ...]:
        return tuple(self.fingerprint(graph, artifact) for artifact in artifacts)

    def fingerprint(self, graph: Graph, artifact: str) -> ArtifactFingerprint:
        if artifact == GRAPH_NODES:
            revision = graph.node_revision
            digest = self._revisioned_digest(
                graph,
                artifact,
                revision,
                tuple((node_id, astuple(node)) for node_id, node in sorted(graph.nodes.items())),
            )
        elif artifact == GRAPH_EDGES:
            revision = graph.edge_revision
            digest = self._revisioned_digest(
                graph,
                artifact,
                revision,
                tuple(astuple(edge) for edge in graph.edges),
            )
        elif artifact == GRAPH_METADATA:
            # Graph metadata remains a compatibility dict rather than a
            # revisioned container. Its digest is therefore also its revision.
            digest = _digest(tuple(sorted(graph.metadata.items())))
            revision = digest
        else:
            raise ValueError(f"unknown graph artifact: {artifact}")
        return ArtifactFingerprint(artifact, revision, digest)

    def _revisioned_digest(
        self,
        graph: Graph,
        artifact: str,
        revision: int,
        payload: object,
    ) -> str:
        key = (id(graph), artifact, revision)
        cached = self._cache.get(key)
        if cached is not None and cached[0] is graph:
            self._cache.move_to_end(key)
            return cached[1]
        digest = _digest(payload)
        self._cache[key] = (graph, digest)
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return digest


T = TypeVar("T")


class AnalysisCache(Generic[T]):
    """Bounded LRU cache for deterministic pass outcomes."""

    def __init__(self, *, max_entries: int = 32) -> None:
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[AnalysisKey, T] = OrderedDict()

    def get(self, key: AnalysisKey) -> T | None:
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def put(self, key: AnalysisKey, value: T) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()


__all__ = [
    "GRAPH_ARTIFACTS",
    "GRAPH_EDGES",
    "GRAPH_METADATA",
    "GRAPH_NODES",
    "AnalysisCache",
    "AnalysisKey",
    "ArtifactFingerprint",
    "ArtifactIndex",
]
