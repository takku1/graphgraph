# Semantic Store (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Publish and query graph-bound dense vector generations with bounded cold cost, exact invalidation, and balanced implementation/document evidence; does not own embedding semantics, structural expansion, final packet selection, or confidence thresholds.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One persistence/query Module and one public planner integration seam.

## 3. Interface Contracts

- **Inputs:** graph snapshot, semantic manifest, source mode, query vector, and backend identity.
- **Outputs:** balanced code/prose candidates plus generation state and load/score receipts.

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN a dense generation is published THE SYSTEM SHALL expose all generation files atomically and SHALL leave the prior generation usable after interruption.
  - `EvidenceStage:` Inferred
- **[Conditional]** IF both code and prose candidates exist THEN THE SYSTEM SHALL reserve capacity for both; shortages SHALL yield unused capacity without empty result slots.
  - `EvidenceStage:` Inferred
- **[Conditional]** IF a legacy dense JSON artifact is encountered THEN THE SYSTEM SHALL classify it as actionable non-current state and SHALL NOT decode it on a default cold query.
  - `EvidenceStage:` Refuted
- **[State-driven]** WHILE a dense generation is current THE SYSTEM SHALL memory-map its vectors and SHALL preserve graph node IDs and true vector dimensionality, as checked by `modules/semantic-store/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF state is missing, stale, or backend-incompatible THEN THE SYSTEM SHALL avoid implicit build and return an actionable state, as checked by `tests/test_cycle5_regressions.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-SS-001:** Use a generation manifest plus NumPy memory-mappable vector file; dense JSON is legacy-only.
- **ADR-SS-002:** Compute one score vector, then apply deterministic category-aware top-k inside the store rather than exposing rank multipliers to callers.
- **ADR-SS-003:** Preserve the small dependency-free JSON hash store as a separate compatibility path.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/semantic.py`, integration in `src/graphgraph/platform/source_planner.py`.
- **Test Surface Seam:** `tests/test_cycle5_regressions.py`, `tests/test_planning.py`, `tests/test_platform.py`.

## 7. Measurement Seams

- **Primary Metric:** `cold_query_p95_ms` (target `<=3000`, `direction: lower`); warm target `<=1500` ms.
- **Harness Path:** `modules/semantic-store/measure.sh`.
- **Correctness Backpressure:** `modules/semantic-store/checks.sh`.
- **Telemetry Surface:** semantic state, code/prose seed counts, artifact bytes, and load/embed/score milliseconds.
- **Branching Policy:** isolated hypothesis; independent checker; merge only if absolute SLOs, correctness, exact bypass, freshness, and structural ratchet all pass.

## 8. Technology Resolution

- **Decision class:** BUILD.
- **Justification:** Differentiator and fatal fit gap — graph revision compatibility, atomic generation publication, evidence-category balancing, and Receipt semantics are GraphGraph-specific.
- **Selected:** Python 3.11, NumPy 2.4.6 memory maps, atomic filesystem replacement, and exact vectorized cosine/dot-product scoring at the current repository scale.
- **Standard / protocol:** NumPy `.npy`-compatible dense float storage plus a versioned JSON manifest.
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | FAISS 1.14.x | Excellent large-scale ANN library, but current stores are tens of thousands of vectors; adding native index packaging does not supply publication, graph freshness, category balancing, or receipts. Reconsider only after scale measurements show exact NumPy scoring misses its SLO. |
  | Qdrant local/server | Adds another database lifecycle and duplicates GraphGraph's graph-bound state for a small exact-search corpus; its filtering does not remove the need for atomic graph revision compatibility. |

- **Fit gap:** exact NumPy scoring is O(N×D); graph partitioning or FAISS becomes justified only when large-repository measurements cross the declared SLO.
- **Seam:** `src/graphgraph/platform/semantic.py::SemanticIndex` and its balanced query result.
- **Exit cost:** MEDIUM — replace the storage/query Implementation and rebuild generations without changing planner callers.
- **Cost model:** local disk roughly `nodes × dimension × 4 bytes` plus manifest; no service spend.
- **Liability transferred:** NumPy owns portable array/mmap mechanics; generation correctness and recovery remain ours.
- **Operational owner:** us.
- **Failure mode:** invalid or incomplete generations are ignored with an actionable rebuild state; the previous complete generation or structural retrieval remains usable.
- **Open questions:** OW-AC-03 conceptual full recall and cross-repository scale remain measured promotion gates.
