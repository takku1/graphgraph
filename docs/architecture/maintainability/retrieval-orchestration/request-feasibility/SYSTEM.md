# Request Feasibility (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Normalize one retrieval request and establish whether structural, document, or semantic evidence permits execution; does not rank anchors or select result nodes.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One feasibility phase over existing evidence predicates.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `prepared_request`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a facet term is absent from every eligible corpus form THEN THE SYSTEM SHALL preserve the current honest-abstention result, as checked by `tests/test_adversarial_ambiguity.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF evidence is documented but unbuilt THEN THE SYSTEM SHALL report `incomplete`, not `unanswerable`, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-RF-001:** Extract the feasibility phase without changing any threshold or evidence predicate.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/request_feasibility.py`.
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_adversarial_ambiguity.py`.

## 7. Measurement Seams

- **Primary Metric:** `conceptual_full_recall` (target `>=0.80`, `direction: higher`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** unchanged answerability and facet-coverage receipts.
- **Branching Policy:** extraction-only; no receipt or result diff on fixed fixtures.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — honest evidence feasibility is part of GraphGraph's retrieval semantics; no generic library knows the project's evidence taxonomy.
- **Selected:** Python 3.10 immutable dataclasses and pure functions
- **Standard / protocol:** existing `RetrievalResult` contract
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | LibCST 1.8.6 | Can move syntax but cannot verify the domain phase boundary. |
  | Rope 1.14.0 | Symbol moves do not establish the abstention/incomplete contract. |

- **Fit gap:** no generic library knows the project's evidence taxonomy.
- **Seam:** `src/graphgraph/retrieval/request_feasibility.py`
- **Exit cost:** LOW — internal facade-preserving extraction.
- **Cost model:** no dependency; fixed-fixture equality plus retrieval measurement.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** any result or receipt mismatch fails focused tests and the labelled eval.
- **Open questions:** none
