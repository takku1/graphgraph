# Embedding Backend (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Convert query and corpus text into deterministic local embedding vectors with explicit model identity; does not own vector persistence, nearest-neighbor policy, graph identity, or downloads during retrieval.

## 2. Sub-System Decomposition

**Atomic leaf (procured).** The optional model runtime is adopted behind the existing backend seam.

## 3. Interface Contracts

- **Inputs:** query text and model configuration.
- **Outputs:** query vector, backend/model identity, and embedding timing.

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** The Embedding Backend SHALL report the model identity and true vector dimension used to produce every dense generation, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF the optional runtime or model is unavailable THEN THE SYSTEM SHALL report that state without downloading or building during retrieval, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN an exact structural query bypasses semantic retrieval THE SYSTEM SHALL avoid initializing the embedding backend, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF model weights are already cached on disk THEN an auto-mode query SHALL be permitted to load them and consult a current index, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF model weights are absent THEN an auto-mode query SHALL refuse the index and report `cold_backend` rather than fetching over the network, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-EB-001:** Use an ONNX-based local embedder so semantic retrieval remains private and avoids a hosted-service dependency.
- **ADR-EB-002 (2026-08-19):** The auto-mode gate is "would this download", not "is the model already constructed in this process". The two were treated as one fact, and the second is false in every cold process by construction — auto is precisely the path that declines to construct the model, so it could never become true. The effect was perverse and silent: with `fastembed` absent the hash index was consulted, and with `fastembed` *installed* the auto path consulted nothing at all, in every process, forever. Installing the better backend disabled semantic retrieval, and the documented "warm it explicitly with `platform semantic --rebuild`" workflow bought a cold CLI nothing.

  Cached weights are now detected by a filesystem probe of FastEmbed's own cache layout that imports nothing, so the decision costs a few `stat` calls on the hot path. Measured on `eval/conceptual-fixture.json` with a current index: paraphrase recall **0.200 → 0.800**, red control abstaining in both arms. Cost, on a 334-node corpus with a current index: exact warm queries **27.3 → 26.9 ms** (unchanged — the exact fast path never requests semantic), conceptual **first** query +754 ms for the one-time model load, conceptual warm +20 ms.

  This is deliberately narrower than the reverted `hypothesis/ow-ac-03-semantic-auto` attempt (`430a64d`), which removed the guard and the `cold_backend` state outright and so would fetch during a query. Refusing an actual download is still correct; refusing a local load of already-present weights was not.
- **ADR-EB-003 (2026-08-19):** Embed in length-sorted batches of 16, not the library default of unsorted 256. ONNX pads every batch to its longest member, so batching a 14-character label with a 465-character docstring computes both at the longer width; and a 256-row activation tensor falls out of CPU cache where a 16-row one does not. The two effects compound. Measured on 1,200 real nodes: **51 → 140 nodes/s (2.7x)**, and end-to-end index build on a 334-node corpus **5.97 s → 3.11 s**, with **bit-identical** vectors (334/334 exact, max component delta 0.0) and a byte-identical serialized index.

  Throughput is a correctness input here, not a convenience. A semantic index that is too slow to rebuild goes stale, and a stale index silently drops conceptual recall from 0.800 to 0.200 (and that residual is a single `subsystem_summary` task returning two-thirds of the corpus) — this repository's own index was stale for exactly that reason. `parallel` was rejected: FastEmbed's multiprocessing path terminates its workers on Windows, which is a supported platform. Thread count was measured and is not the constraint (63–67 nodes/s across 8, 16, and default).

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/embeddings.py`.
- **Test Surface Seam:** `tests/test_platform.py`, `tests/test_planning.py`.

## 7. Measurement Seams

- **Primary Metric:** `semantic_embed_p95_ms` (observation with cold/warm query SLO backpressure, `direction: lower`).
- **Harness Path:** `modules/semantic-store/measure.sh`.
- **Correctness Backpressure:** `modules/semantic-store/checks.sh`.
- **Telemetry Surface:** backend/model identity, dimension, and embed milliseconds in the retrieval Receipt.
- **Branching Policy:** isolated candidate; no implicit downloads; keep only with semantic-store and retrieval gates green.

## 8. Technology Resolution

- **Decision class:** ADOPT.
- **Selected:** FastEmbed 0.8.0, locked in `uv.lock`, using ONNX Runtime; dependency-free hash fallback remains built in.
- **Standard / protocol:** ONNX model inference and NumPy float vectors.
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Sentence Transformers | Capable semantic-search baseline, but its PyTorch-oriented installation is heavier than the existing ONNX integration for a local optional feature. |
  | Hosted embedding API | Adds source-code disclosure, network latency, credentials, and variable per-query cost to a local-first tool. |

- **Fit gap:** FastEmbed supplies vectors, not graph-bound publication, freshness, category-aware selection, or receipts; those stay in the sibling Semantic Store.
- **Seam:** `src/graphgraph/platform/embeddings.py::EmbeddingBackend`.
- **Exit cost:** MEDIUM — rebuild dense generations with a replacement backend while preserving the vector/provenance Interface.
- **Cost model:** no service spend; one optional model download and local CPU/RAM cost.
- **Liability transferred:** model packaging and ONNX inference compatibility.
- **Operational owner:** Qdrant/FastEmbed for runtime; us for selection and provenance.
- **Failure mode:** backend unavailable returns an explicit state and structural retrieval continues; retrieval never installs or downloads implicitly.
- **Open questions:** model tournament remains research work only if the current backend cannot meet OW-AC-03.
