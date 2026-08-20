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
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence, runtime_checkable

#: Sentinel backend name stored in an index built from the offline hash.
HASH_BACKEND_NAME = "hash"

#: Env var naming an HTTP embedding endpoint. It must accept a JSON POST
#: {"input": [text, ...]} and return {"embeddings": [[float, ...], ...]} in the
#: same order. Deliberately generic so it works against a local sidecar server,
#: a self-hosted model, or a proxy to a hosted provider.
EMBED_URL_ENV = "GRAPHGRAPH_EMBED_URL"
EMBED_MODEL_ENV = "GRAPHGRAPH_EMBED_MODEL"
EMBED_KEY_ENV = "GRAPHGRAPH_EMBED_API_KEY"
#: FastEmbed's own cache location override, read (never written) so the
#: auto-query path can tell "cached on disk" from "would download".
FASTEMBED_CACHE_ENV = "FASTEMBED_CACHE_PATH"
#: A cached model is only usable when its tokenizer and config sit beside the
#: weights; FastEmbed loads all three and silently falls back to the network
#: when any is missing.
_REQUIRED_MODEL_FILES = ("tokenizer.json", "config.json")


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


#: Batch size for local ONNX inference. Deliberately far below the library
#: default of 256, for two compounding reasons measured on 1,200 real nodes:
#: ONNX pads every batch to its longest member, so one long docstring inflates
#: the compute for everything batched with it; and a 256-row activation tensor
#: falls out of CPU cache where a 16-row one does not.
EMBED_BATCH_ENV = "GRAPHGRAPH_EMBED_BATCH"
_DEFAULT_EMBED_BATCH = 16


def _embed_batch_size() -> int:
    raw = os.environ.get(EMBED_BATCH_ENV, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _DEFAULT_EMBED_BATCH


def embed_length_sorted(
    texts: list[str],
    embed_batches: "Callable[[list[str], int], Iterable[Any]]",
    batch_size: int,
) -> list:
    """Embed with length-bucketed batches, returned in the caller's order.

    Grouping similar-length texts together minimizes the padding each batch is
    computed at. Throughput measured on a 1,200-node sample: 51 nodes/s at the
    library default (unsorted, batch 256) against 140 nodes/s length-sorted at
    batch 16, a 2.7x ratio on this machine. Bit-identity was verified separately
    on the 334-node `retrieval` package: 334/334 exact, max component delta 0.0.
    Two corpora, two claims -- the speedup is machine-specific, the identity is
    not.

    Restoring the caller's order is the whole correctness burden: a permutation
    bug here would bind every vector to the wrong node and still produce a
    perfectly well-formed index that silently answers nonsense.
    """
    if len(texts) <= batch_size:
        return list(embed_batches(texts, batch_size))
    order = sorted(range(len(texts)), key=lambda index: len(texts[index]))
    restored: list = [None] * len(texts)
    produced = 0
    for vector, index in zip(embed_batches([texts[i] for i in order], batch_size), order):
        restored[index] = vector
        produced += 1
    if produced != len(texts):
        raise ValueError(
            f"embedding backend returned {produced} vectors for {len(texts)} inputs"
        )
    return restored


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

    @property
    def model_name(self) -> str:
        return self._model_name

    def _ensure_model(self):
        if self._model is None:
            from fastembed import TextEmbedding  # lazy: optional dependency

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    @property
    def is_warm(self) -> bool:
        """Whether querying can proceed without importing/loading the model."""
        return self._model is not None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = embed_length_sorted(
            list(texts),
            lambda batch, size: model.embed(batch, batch_size=size),
            _embed_batch_size(),
        )
        return [[float(component) for component in vector] for vector in vectors]


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


def active_backend_is_warm() -> bool:
    """Whether the active backend avoids FastEmbed's first-query setup cliff.

    Hash vectors and explicitly supplied/custom backends have no implicit local
    model construction. FastEmbed is special: merely having the optional extra
    installed selects it, while its first embed can import ONNX, initialize a
    session, and download model files. Auto queries must not trigger that work.
    """
    backend = resolve_backend()
    return not isinstance(backend, FastEmbedBackend) or backend.is_warm


def _fastembed_cache_dir() -> Path:
    """Where FastEmbed keeps downloaded weights, without importing FastEmbed."""
    override = os.environ.get(FASTEMBED_CACHE_ENV, "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "fastembed_cache"


def local_model_is_cached(model_name: str) -> bool:
    """Whether this model's ONNX weights are already on disk.

    Deliberately does not import fastembed: this runs on the auto-query path,
    where the whole point is to decide *before* paying any import cost. The
    layout is huggingface-hub's (``models--<org>--<repo>/snapshots/<sha>/*.onnx``)
    and the repo name is matched on the model's trailing component, because
    FastEmbed maps e.g. ``BAAI/bge-small-en-v1.5`` onto the ONNX mirror
    ``qdrant/bge-small-en-v1.5-onnx-q``.
    """
    root = _fastembed_cache_dir()
    if not root.is_dir():
        return False
    stem = model_name.rsplit("/", 1)[-1].strip().lower()
    if not stem:
        return False
    try:
        for entry in root.iterdir():
            if not entry.name.startswith("models--") or stem not in entry.name.lower():
                continue
            for snapshot in (entry / "snapshots").glob("*"):
                if not snapshot.is_dir():
                    continue
                weights = [path for path in snapshot.glob("*.onnx") if path.stat().st_size > 0]
                if not weights:
                    continue
                # Weights alone are not a usable model. FastEmbed also loads the
                # tokenizer and config, and it tries `local_files_only=True`
                # first and then *falls through to a network fetch*. So an
                # interrupted download -- ONNX present, tokenizer missing --
                # would pass a weights-only probe and then quietly download,
                # which is the exact invariant this predicate exists to hold.
                if all((snapshot / name).is_file() for name in _REQUIRED_MODEL_FILES):
                    return True
    except OSError:
        return False
    return False


def active_backend_needs_download() -> bool:
    """Whether warming the active backend would fetch model files over the network.

    This is the fact auto queries actually care about, and it is narrower than
    :func:`active_backend_is_warm`. That predicate answers "is the model already
    constructed in this process", which every cold process answers `False` --
    including one whose weights have been cached on disk for months. Treating
    the two as the same fact made a cold CLI silently skip a current semantic
    index forever, so paraphrase queries fell back to structural-only retrieval
    with no download in prospect and nothing to warn about.
    """
    backend = resolve_backend()
    if not isinstance(backend, FastEmbedBackend) or backend.is_warm:
        return False
    return not local_model_is_cached(backend.model_name)


def normalize_dense(vector: Sequence[float]) -> dict[int, float]:
    """L2-normalize a dense vector into the sparse map the index stores.

    Real embeddings are dense, but the index serialization and cosine already
    speak `dict[int, float]`, so representing a dense vector as a full map keeps
    one storage path. Zero components are dropped; a real embedding has almost
    none, so the size cost is the vector itself, as expected.
    """
    norm = math.sqrt(sum(float(v) * float(v) for v in vector)) or 1.0
    return {index: float(v) / norm for index, v in enumerate(vector) if v != 0.0}
