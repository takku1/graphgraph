# Retrieval Result Assembly (L3)

## 1. System Intent & Responsibility

Convert grounded candidates into one bounded `RetrievalResult` with coverage,
quality, affected-test, and control receipts; does not discover anchors or
re-evaluate request feasibility.

## 2. Sub-System Decomposition

Atomic leaf (atomic build).

## 3. Interface Contracts

- **Inputs:** prepared request, anchor/search outcome, graph snapshot, node/edge budgets.
- **Outputs:** existing `RetrievalResult` with selected nodes/edges and complete receipts.

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Assembly SHALL preserve selected node IDs, edge IDs, ordering, and all receipt fields for fixed inputs.
  - `EvidenceStage: Sampled` — six public result/Receipt cases and a stabilized compiler packet/Receipt were byte-identical.
- **[Conditional]** IF a budget truncates evidence THEN THE SYSTEM SHALL preserve the current omission and completeness telemetry.
  - `EvidenceStage: Sampled` — budget and affected-test tests.

## 5. Architectural Decisions (ADRs)

- **ADR-RA-001:** Assembly coordinates existing expansion, reservation, selection, quality, and test-recommendation modules; it does not absorb their algorithms.

## 6. Leaf Execution & Test Seam

- **Implementation File(s):** `src/graphgraph/retrieval/result_assembly.py`, facade wiring in `retrieval/context.py`.
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_affected_tests.py`, `tests/test_context_packet.py`.

## 7. Measurement Seams

- **Primary Metric:** node recall (target `>=0.75`, `direction: higher`).
- **Harness Path:** `components/information-retrieval/measure.sh` and retrieval eval tasks.
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`.
- **Telemetry Surface:** unchanged quality, facet, affected-test, control, and budget receipts.
- **Branching Policy:** fixed-input structural equality first; then recall/token/latency non-regression.

## 8. Technology Resolution

- **Decision class:** BUILD.
- **Selected:** Python 3.10 typed records and pure assembly helpers over existing modules.
- **Standard / protocol:** `RetrievalResult` and packet receipt contracts.
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | LibCST 1.8.6 codemod | Cannot establish equality of graph selection and receipt semantics. |
  | Rope 1.14.0 automated refactor | Moves symbols but cannot preserve budgeted graph behavior by construction. |

- **Justification:** differentiator — budgeted structural evidence assembly is core GraphGraph behavior.
- **Fit gap:** no general workflow library represents the graph and receipt invariants.
- **Seam:** private `_assemble_retrieval_result` returning the existing `RetrievalResult`.
- **Exit cost:** LOW — internal facade-preserving extraction.
- **Cost model:** no dependency; token, recall, and warm latency must not regress.
- **Liability transferred:** none.
- **Operational owner:** us.
- **Failure mode:** structural or receipt drift fails fixture equality; metric drift rejects the branch.
- **Open questions:** none.
