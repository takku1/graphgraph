# Evaluation Protocol and Harness (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Freeze the versioned evaluation suite, resolve declared expectations against a real graph, and emit positionally paired, stratum-preserving run records; does not calibrate the confidence attached to those records, rank documents, or decide the acceptance verdict.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One frozen suite schema and one harness that executes it.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`, `context_packet`
- **Outputs:** `eval_run_records`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Comparisons SHALL be paired positionally, never keyed on query text, as checked by `tests/test_eval_protocol.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Expectations SHALL be resolved through the harness resolver rather than matched literally, as checked by `tests/test_eval_harness.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** A run record SHALL carry the protocol versions it was produced under — task resolver, token proxy, reference tokenizers, and expected-evidence rule — so a number cannot outlive the definition that produced it.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-EP-001:** Instrument red tests come first. A comparison is trusted only as far as its self-comparison reads zero, so pairing is positional and the pairing rule is itself under test.
- **ADR-EP-002:** Stratified reporting over aggregate scores: weak strata are preserved in the record rather than averaged out of sight.
- **ADR-EP-003:** The suite is repository-held-out and every qrel names its independent source receipt, so an expectation cannot be justified by the same evidence the system under test used to produce it.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/analysis/__init__.py`, `src/graphgraph/analysis/eval.py`, `src/graphgraph/analysis/eval_protocol.py`
- **Test Surface Seam:** `tests/test_eval_harness.py`, `tests/test_eval_protocol.py`, `tests/test_benchmark.py`, `tests/test_docs_contract.py`, `tests/test_locus_findings.py`

## 7. Measurement Seams

- **Primary Metric:** `answer_confidence_ece` (over the hand-labelled task set, `direction: lower`)
- **Evaluation Gate Path:** `components/evaluation-analysis/measure.sh`
- **Correctness Backpressure:** `components/evaluation-analysis/checks.sh`
- **Telemetry Surface:** protocol versions, stratified deltas, unresolved-expectation counts, scored-prediction count.
- **Branching Policy:** isolated candidate; a broken instrument is a revert, not a pass.
- **Known granularity gap:** this leaf currently shares the component-level `answer_confidence_ece` gate, which is the sibling's number; the harness has no unresolved-expectation-rate gate of its own. Recorded as an open granularity gap rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the evidence standard is a product claim, and the harness that produces the numbers must be inspectable as a diff. A tracker that stores numbers cannot catch a pairing or resolver bug, which is the failure this leaf exists to make impossible.
- **Selected:** in-repo harness on Python 3.10; tiktoken 0.13.0 for token-denominated metrics
- **Standard / protocol:** none; suite schema is versioned in-repo
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | MLOps experiment tracker | Stores numbers; does not catch pairing or resolver bugs. |
  | pytest-benchmark as the suite runner | Times code; carries no notion of a held-out qrel or a stratum. |
  | An off-the-shelf IR evaluation toolkit | Assumes a document corpus and fixed qrel format; the unit here is a graph subgraph. |

- **Fit gap:** paired deltas are reported without confidence intervals.
- **Seam:** `src/graphgraph/analysis/eval_protocol.py`
- **Exit cost:** MEDIUM — recorded suites are denominated in this schema version.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unresolvable expectation is reported unresolved rather than scored zero.
- **Open questions:** OW-P0-01
