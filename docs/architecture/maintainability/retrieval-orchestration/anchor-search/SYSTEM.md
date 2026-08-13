# Anchor and Search Execution (L3)

## 1. System Intent & Responsibility

Produce grounded anchor starts and ranked candidates with complete routing and
source receipts; does not decide feasibility or assemble the final packet set.

## 2. Sub-System Decomposition

Atomic leaf (atomic build).

## 3. Interface Contracts

- **Inputs:** prepared request, graph snapshot, lexical/semantic source plan, anchor budget.
- **Outputs:** immutable anchor/search outcome containing candidates, seeds, timing, provenance, and truncation state.

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN exact anchoring is possible THE SYSTEM SHALL preserve the exact-fast-path and its timing receipt.
  - `EvidenceStage: Measured` — controlled warm A/B improved from 524.747 ms to 517.419 ms with exact public Receipt equality.
- **[Conditional]** IF a source is stale or unavailable THEN THE SYSTEM SHALL preserve its warning rather than silently treating it as empty evidence.
  - `EvidenceStage: Sampled` — semantic source-planner tests.

## 5. Architectural Decisions (ADRs)

- **ADR-ASX-001:** The phase owns execution order and receipts, while ranking algorithms remain in `anchors.py` and `search.py`.

## 6. Leaf Execution & Test Seam

- **Implementation File(s):** `src/graphgraph/retrieval/anchor_search.py`, facade wiring in `retrieval/context.py`.
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_semantic_retrieval.py`, `tests/test_query_fastpath.py`.

## 7. Measurement Seams

- **Primary Metric:** `retrieval_query_warm_ms` (no regression, `direction: lower`).
- **Harness Path:** `components/information-retrieval/measure.sh`.
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`.
- **Telemetry Surface:** unchanged anchor, source-plan, cache, and timing receipts.
- **Branching Policy:** extract orchestration only; compare fixed-query node IDs and receipts before merge.

## 8. Technology Resolution

- **Decision class:** BUILD.
- **Selected:** Python 3.10 typed records over the existing anchor/search implementations.
- **Standard / protocol:** existing retrieval receipt JSON.
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | LibCST 1.8.6 codemod | Preserves syntax, not execution ordering or timing provenance. |
  | Rope 1.14.0 automated refactor | Cannot validate source-plan and cache receipt equivalence. |

- **Justification:** differentiator — bounded structural/semantic source coordination is project-specific.
- **Fit gap:** generic refactoring tools do not model retrieval provenance.
- **Seam:** private `_execute_anchor_search` returning a frozen, slotted typed outcome or the existing terminal result.
- **Exit cost:** LOW — internal facade-preserving extraction.
- **Cost model:** no dependency; warm latency must remain within harness tolerance.
- **Liability transferred:** none.
- **Operational owner:** us.
- **Failure mode:** output or receipt drift fails focused tests; latency regression fails measurement.
- **Open questions:** none.
