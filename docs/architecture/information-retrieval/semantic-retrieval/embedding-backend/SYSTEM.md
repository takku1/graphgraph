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

## 5. Architectural Decisions (ADRs)

- **ADR-EB-001:** Use an ONNX-based local embedder so semantic retrieval remains private and avoids a hosted-service dependency.

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
