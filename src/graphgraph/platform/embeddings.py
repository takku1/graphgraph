"""Optional real-embedding backend for the semantic index.

The default `SemanticIndex` is a dependency-free hashed bag-of-words: cosine is
high only when two texts share literal tokens, so paraphrases that resolve to
the same node score near zero. That is fine as an offline floor but it is not
semantic, and it caps paraphrase recall regardless of tuning.

This module lets a real embedding model supply the vectors when one is
available, while leaving the offline behaviour byte-identical when one is not.
Nothing here is imported on the hot path unless a backend is actually
configured, and no third-party package is required: the built-in backend talks
to an HTTP embedding endpoint using only the standard library. A heavier local
backend (sentence-transformers, etc.) can register itself via `set_backend`.

Provenance matters more than it looks. An index built from hashed vectors and
queried with real embeddings -- or the reverse -- produces confident nonsense,
because the two vector spaces are unrelated. The index records which backend
built it, and the query path refuses a mismatch rather than serving garbage.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from typing import Protocol, Sequence, runtime_checkable

#: Sentinel backend name stored in an index built from the offline hash.
HASH_BACKEND_NAME = "hash"

#: Env var naming an HTTP embedding endpoint. It must accept a JSON POST
#: {"input": [text, ...]} and return {"embeddings": [[float, ...], ...]} in the
#: same order. Deliberately generic so it works against a local sidecar server,
#: a self-hosted model, or a proxy to a hosted provider.
EMBED_URL_ENV = "GRAPHGRAPH_EMBED_URL"
EMBED_MODEL_ENV = "GRAPHGRAPH_EMBED_MODEL"
EMBED_KEY_ENV = "GRAPHGRAPH_EMBED_API_KEY"


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Turns text into dense vectors in a fixed, model-defined space."""

    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per input, in input order."""
        ...


class HttpEmbeddingBackend:
    """Embeds via a JSON HTTP endpoint, using only the standard library.

    Kept dependency-free on purpose: the tool's identity is offline-first, and
    a network backend that needs no extra install is the least invasive way to
    make real embeddings available to anyone who wants them.
    """

    def __init__(
        self,
        url: str,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        batch_size: int = 64,
    ) -> None:
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.batch_size = max(1, batch_size)
        # The endpoint plus model define the vector space; fold both into the
        # name so an index built against one is not reused against another.
        self.name = f"http:{url}" + (f"#{model}" if model else "")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        items = list(texts)
        for start in range(0, len(items), self.batch_size):
            out.extend(self._embed_batch(items[start : start + self.batch_size]))
        return out

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {"input": batch}
        if self.model:
            payload["model"] = self.model
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        vectors = _extract_vectors(data)
        if len(vectors) != len(batch):
            raise ValueError(
                f"embedding backend returned {len(vectors)} vectors for "
                f"{len(batch)} inputs"
            )
        return vectors


def _extract_vectors(data: object) -> list[list[float]]:
    """Accept the two response shapes seen in the wild.

    Native: {"embeddings": [[...], ...]}. OpenAI-compatible:
    {"data": [{"embedding": [...]}, ...]}.
    """
    if isinstance(data, dict):
        if isinstance(data.get("embeddings"), list):
            return [[float(x) for x in vec] for vec in data["embeddings"]]
        if isinstance(data.get("data"), list):
            return [
                [float(x) for x in row["embedding"]]
                for row in data["data"]
                if isinstance(row, dict) and "embedding" in row
            ]
    raise ValueError("unrecognized embedding response shape")


#: Default local model for the optional `graphgraph[semantic]` extra. A small,
#: strong retrieval model that runs on onnxruntime (no torch).
LOCAL_MODEL_ENV = "GRAPHGRAPH_EMBED_LOCAL_MODEL"
_DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"


class FastEmbedBackend:
    """Local ONNX embeddings via the optional ``fastembed`` dependency.

    Installed with ``pip install graphgraph[semantic]``. Nothing here imports or
    downloads anything until :meth:`embed` is first called, so resolving the
    backend is cheap and a core (hash-only) install is never touched. The model
    is fetched and cached once by fastembed on first use.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or _DEFAULT_LOCAL_MODEL
        self._model = None
        self.name = f"fastembed:{self._model_name}"

    def _ensure_model(self):
        if self._model is None:
            from fastembed import TextEmbedding  # lazy: optional dependency

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._ensure_model()
        return [[float(component) for component in vector] for vector in model.embed(list(texts))]


def _local_backend_available() -> bool:
    """Whether the optional `fastembed` backend can be constructed (cheap check).

    Uses ``find_spec`` so a core install returns immediately without importing
    fastembed or triggering a model download.
    """
    import importlib.util

    return importlib.util.find_spec("fastembed") is not None


_BACKEND: EmbeddingBackend | None = None
_RESOLVED = False


def set_backend(backend: EmbeddingBackend | None) -> None:
    """Register a process-wide backend (e.g. a local model). Overrides env."""
    global _BACKEND, _RESOLVED
    _BACKEND = backend
    _RESOLVED = True


def resolve_backend() -> EmbeddingBackend | None:
    """Return the active backend, or None to mean 'use the offline hash'.

    Resolution is cached: the first call reads the environment, later calls
    reuse the result so a per-node build does not re-parse env every time.
    `reset_backend_cache` exists for tests that mutate the environment.
    """
    global _BACKEND, _RESOLVED
    if _RESOLVED:
        return _BACKEND
    url = os.environ.get(EMBED_URL_ENV, "").strip()
    if url:
        # An explicit endpoint always wins: it is a deliberate override.
        _BACKEND = HttpEmbeddingBackend(
            url,
            model=os.environ.get(EMBED_MODEL_ENV) or None,
            api_key=os.environ.get(EMBED_KEY_ENV) or None,
        )
    elif _local_backend_available():
        # `graphgraph[semantic]` is installed -> use the local ONNX model so
        # paraphrase recall works without any configuration. A core install
        # skips this branch and stays on the offline hash.
        _BACKEND = FastEmbedBackend(os.environ.get(LOCAL_MODEL_ENV) or None)
    else:
        _BACKEND = None
    _RESOLVED = True
    return _BACKEND


def reset_backend_cache() -> None:
    """Forget any resolved backend so the next call re-reads the environment."""
    global _BACKEND, _RESOLVED
    _BACKEND = None
    _RESOLVED = False


def active_backend_name() -> str:
    """Name of the backend an index would be built with right now."""
    backend = resolve_backend()
    return backend.name if backend is not None else HASH_BACKEND_NAME


def normalize_dense(vector: Sequence[float]) -> dict[int, float]:
    """L2-normalize a dense vector into the sparse map the index stores.

    Real embeddings are dense, but the index serialization and cosine already
    speak `dict[int, float]`, so representing a dense vector as a full map keeps
    one storage path. Zero components are dropped; a real embedding has almost
    none, so the size cost is the vector itself, as expected.
    """
    norm = math.sqrt(sum(float(v) * float(v) for v in vector)) or 1.0
    return {index: float(v) / norm for index, v in enumerate(vector) if v != 0.0}
