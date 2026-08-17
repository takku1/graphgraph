# Evaluation Analysis (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Turn raw evaluation runs into defensible statements — calibration, stratified reports, and the metrics other subsystems are gated on; does not own the acceptance verdict or the retrieval behavior measured.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One protocol and one metric Module.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`, `context_packet`
- **Outputs:** `evaluation_metrics`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Comparisons SHALL be paired positionally, never keyed on query text, as checked by `tests/test_eval_protocol.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Expectations SHALL be resolved through the harness resolver rather than matched literally, as checked by `tests/test_eval_harness.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Reported confidence SHALL be calibrated against outcomes, as checked by `tests/test_calibration.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a suite is versioned THEN results from different versions SHALL NOT be compared directly.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Document authority SHALL be deterministic between identical runs, as checked by `tests/test_document_authority.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-EA-001:** Instrument red tests come first. A comparison is trusted only as far as its self-comparison reads zero.
- **ADR-EA-002:** Stratified reporting over aggregate scores.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/analysis/__init__.py`, `src/graphgraph/analysis/calibration.py`, `src/graphgraph/analysis/document_authority.py`, `src/graphgraph/analysis/eval.py`, `src/graphgraph/analysis/eval_protocol.py`, `src/graphgraph/analysis/metrics.py`
- **Test Surface Seam:** `tests/test_benchmark.py`, `tests/test_calibration.py`, `tests/test_distribution_artifacts.py`, `tests/test_docs_contract.py`, `tests/test_document_authority.py`, `tests/test_eval_harness.py`, `tests/test_eval_protocol.py`, `tests/test_locus_findings.py`

## 7. Measurement Seams

- **Primary Metric:** `expected_calibration_error` (target `<0.10`, `direction: lower`)
- **Evaluation Gate Path:** `components/evaluation-analysis/measure.sh`
- **Correctness Backpressure:** `components/evaluation-analysis/checks.sh`
- **Telemetry Surface:** ECE, stratified deltas, unresolved-expectation counts.
- **Branching Policy:** isolated candidate; a broken instrument is a revert, not a pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the evidence standard is a product claim, and its instruments must be inspectable. scikit-learn would add a heavy dependency for a few dozen lines.
- **Selected:** in-repo analysis on Python 3.10; tiktoken 0.13.0 for token-denominated metrics
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | scikit-learn / scipy | Heavy numerical dependency for reliability curves the project can compute in stdlib. |
  | MLOps experiment tracker | Stores numbers; does not catch pairing or resolver bugs. |

- **Fit gap:** paired deltas are reported without confidence intervals.
- **Seam:** `src/graphgraph/analysis/eval_protocol.py`
- **Exit cost:** MEDIUM
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unresolvable expectation is reported unresolved rather than scored zero.
- **Open questions:** OW-P0-01
