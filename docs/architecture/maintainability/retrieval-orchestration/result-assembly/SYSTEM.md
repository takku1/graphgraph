# Retrieval Result Assembly (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Convert grounded candidates into one bounded `RetrievalResult` with coverage, quality, affected-test, and control receipts; does not discover anchors or re-evaluate request feasibility.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One assembly phase over existing expansion, reservation, selection, and quality modules.

## 3. Interface Contracts

- **Inputs:** `anchor_outcome`
- **Outputs:** `orchestration_modules`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Assembly SHALL preserve selected node IDs, edge IDs, ordering, and all receipt fields for fixed inputs, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a budget truncates evidence THEN THE SYSTEM SHALL preserve the current omission and completeness telemetry, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-RA-001:** Assembly coordinates existing modules; it does not absorb their algorithms.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/result_assembly.py`.
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_context_compiler.py`.

## 7. Measurement Seams

- **Primary Metric:** `node_recall` (target `>=0.75`, `direction: higher`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** unchanged quality, facet, affected-test, control, and budget receipts.
- **Branching Policy:** fixed-input structural equality first; then recall, token, and warm-latency non-regression.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — budgeted structural evidence assembly is core GraphGraph behavior.
- **Selected:** Python 3.10 typed records and pure assembly helpers over existing modules
- **Standard / protocol:** `RetrievalResult` and packet receipt contracts
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | LibCST 1.8.6 | Cannot establish equality of graph selection and receipt semantics. |
  | Rope 1.14.0 | Moves symbols but cannot preserve budgeted graph behavior. |

- **Fit gap:** no general workflow library represents the graph and receipt invariants.
- **Seam:** `src/graphgraph/retrieval/result_assembly.py`
- **Exit cost:** LOW — internal facade-preserving extraction.
- **Cost model:** no dependency; token, recall, and warm latency must not regress.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** structural or receipt drift fails fixture equality; metric drift rejects the branch.
- **Open questions:** none
