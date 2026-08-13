# Request Feasibility (L3)

## 1. System Intent & Responsibility

Normalize one retrieval request and establish whether structural, document, or
semantic evidence permits execution; does not rank anchors or select result
nodes.

## 2. Sub-System Decomposition

Atomic leaf (atomic build).

## 3. Interface Contracts

- **Inputs:** query, query class, scope, graph/source metadata, semantic-index status, explicit seeds.
- **Outputs:** immutable prepared request or the existing abstain/incomplete result with exact reason.

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a facet term is absent from every eligible corpus form THEN THE SYSTEM SHALL preserve the current honest-abstention result.
  - `EvidenceStage: Sampled` — public retrieval characterization and the zero-recall red control passed unchanged.
- **[Conditional]** IF evidence is documented but unbuilt THEN THE SYSTEM SHALL report `incomplete`, not `unanswerable`.
  - `EvidenceStage: Sampled` — document-status tests.

## 5. Architectural Decisions (ADRs)

- **ADR-RF-001:** Extract the feasibility phase without changing any threshold or evidence predicate.

## 6. Leaf Execution & Test Seam

- **Implementation File(s):** `src/graphgraph/retrieval/request_feasibility.py`, facade wiring in `retrieval/context.py`.
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_retrieval_document_status.py`, `tests/test_adversarial_ambiguity.py`.

## 7. Measurement Seams

- **Primary Metric:** conceptual full recall (target `>=0.80`, `direction: higher`).
- **Harness Path:** `components/information-retrieval/measure.sh` plus the labelled retrieval eval suite.
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`.
- **Telemetry Surface:** unchanged answerability and facet-coverage receipts.
- **Branching Policy:** one extraction-only branch; no receipt or result diff on fixed fixtures.

## 8. Technology Resolution

- **Decision class:** BUILD.
- **Selected:** Python 3.10 immutable dataclasses and pure functions.
- **Standard / protocol:** existing `RetrievalResult` contract.
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | LibCST 1.8.6 codemod | Can move syntax but cannot choose or verify the domain phase boundary. |
  | Rope 1.14.0 automated refactor | Symbol moves do not establish the abstention/incomplete behavioral contract. |

- **Justification:** differentiator — honest evidence feasibility is part of GraphGraph's retrieval semantics.
- **Fit gap:** no generic library knows the project's evidence taxonomy.
- **Seam:** private `_prepare_retrieval` returning a frozen, slotted typed outcome or the existing terminal result.
- **Exit cost:** LOW — internal facade-preserving extraction.
- **Cost model:** no dependency; fixed-fixture equality plus retrieval measurement.
- **Liability transferred:** none.
- **Operational owner:** us.
- **Failure mode:** any result/receipt mismatch fails focused tests and the labelled eval.
- **Open questions:** none.
