# Anchor and Search Execution (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Produce grounded anchor starts and ranked candidates with complete routing and source receipts; does not decide feasibility or assemble the final packet set.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One execution-order phase over existing anchor and search modules.

## 3. Interface Contracts

- **Inputs:** `prepared_request`
- **Outputs:** `anchor_outcome`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN exact anchoring is possible THE SYSTEM SHALL preserve the exact-fast-path and its timing receipt, as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a source is stale or unavailable THEN THE SYSTEM SHALL preserve its warning rather than silently treating it as empty evidence, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-ASX-001:** The phase owns execution order and receipts; ranking algorithms remain in `anchors.py` and `search.py`.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/anchor_search.py`.
- **Test Surface Seam:** `tests/test_retrieval.py`.

## 7. Measurement Seams

- **Primary Metric:** `retrieval_query_warm_ms` (no regression, `direction: lower`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** unchanged anchor, source-plan, cache, and timing receipts.
- **Branching Policy:** extract orchestration only; compare fixed-query node IDs and receipts before merge.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — bounded structural and semantic source coordination is project-specific.
- **Selected:** Python 3.10 typed records over the existing anchor and search implementations
- **Standard / protocol:** existing retrieval receipt JSON
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | LibCST 1.8.6 | Preserves syntax, not execution ordering or timing provenance. |
  | Rope 1.14.0 | Cannot validate source-plan and cache receipt equivalence. |

- **Fit gap:** generic refactoring tools do not model retrieval provenance.
- **Seam:** `src/graphgraph/retrieval/anchor_search.py`
- **Exit cost:** LOW — internal facade-preserving extraction.
- **Cost model:** no dependency; warm latency must remain within harness tolerance.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** output or receipt drift fails focused tests; latency regression fails measurement.
- **Open questions:** none
