# Calibration and Derived Signals (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Turn run records into the numbers other subsystems are gated on — a calibrated reliability decomposition, graph shape and diff summaries, and a deterministic document-authority ordering; does not execute a suite, resolve expectations, or decide which runs to compare.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One reliability decomposition plus the two derived orderings computed from the same records.

## 3. Interface Contracts

- **Inputs:** `eval_run_records`, `task_subgraph`
- **Outputs:** `evaluation_metrics`, `authority_ranks`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Reported confidence SHALL be calibrated against outcomes, as checked by `tests/test_calibration.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Document authority SHALL be deterministic between identical runs, as checked by `tests/test_document_authority.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A document's authority tier SHALL be derived from the single documentation index rather than from a second in-code classification, so one document cannot hold two authorities.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CS-001:** Calibration is reported as a decomposition — reliability, resolution, and the residual — not as a single scalar, because a passing aggregate can hide a bin that is confidently wrong.
- **ADR-CS-002:** The binning used by the gate script and by the shipped assertion is the same, so the reported number cannot silently disagree with the assertion it is meant to track.
- **ADR-CS-003:** Document authority is self-contained and depends on no retrieval state: it decides an ordering, and a caller decides how to apply it as a tiebreaker.
- **ADR-CS-004 (instrument defect, 2026-08-19):** The gate metric is a **known-biased estimator, and it is being read at the sample size where that bias is worst.** Equal-width binned ECE is not a consistent calibration measure: it is discontinuous in the predictions and its value depends on the bin count, so two runs can differ in reported ECE without differing in calibration. Roelofs et al. (AISTATS 2022, *Mitigating Bias in Calibration Error Estimation*) quantify that bias and give a jackknife-debiased estimator; Błasiok and Nakkiran (ICLR 2024, *Smooth ECE: Principled Reliability Diagrams via Kernel Smoothing*, arXiv:2309.12236) give **smECE**, an RBF-kernel-smoothed measure that is consistent in the sense of Błasiok et al. (2023) and needs no binning choice at all.

  This matters concretely here rather than academically. The gate is `ECE < 0.10` over **ten bins on 26 labelled predictions** — under three samples per bin, which is the regime where binned ECE's bias is largest and its variance is untrustworthy. The project's recorded trajectory (0.24 → 0.15 → 0.12, and a separate 0.0627 reading) is denominated entirely in this estimator, so those numbers are not comparable across changes in bin count or panel size, and the distance-to-gate they imply is not reliable.

  Recorded as an instrument defect, not silently repaired: changing the estimator re-denominates every historical ECE reading, which is exactly the trap ADR-TE-003 records for token constants. Opened as `RF-05` — adopt smECE (or debiased ECE) as the reported measure, re-baseline the history under it, and keep the binned value only as a legacy column.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/analysis/calibration.py`, `src/graphgraph/analysis/document_authority.py`, `src/graphgraph/analysis/metrics.py`
- **Test Surface Seam:** `tests/test_calibration.py`, `tests/test_document_authority.py`

## 7. Measurement Seams

- **Primary Metric:** `answer_confidence_ece` (gate `< 0.10`, ten bins over the hand-labelled task set, `direction: lower`)
- **Evaluation Gate Path:** `components/evaluation-analysis/measure.sh`
- **Correctness Backpressure:** `components/evaluation-analysis/checks.sh`
- **Telemetry Surface:** ECE, MCE, Brier, base rate, reliability/resolution and decomposition residual, bin count.
- **Branching Policy:** isolated candidate; a broken instrument is a revert, not a pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the calibration claim is a product claim, and its instrument must be readable in full by anyone auditing the number. scikit-learn would add a heavy numerical dependency for a few dozen lines of isotonic regression and binning.
- **Selected:** in-repo calibration on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | scikit-learn / scipy | Heavy numerical dependency for reliability curves the project computes in stdlib. |
  | `netcal` or a dedicated calibration package | Same dependency weight; the decomposition is the part under review, not the part to hide. |
  | Reporting a raw accuracy instead | A pass rate cannot detect that confidence stopped meaning what it says. |
  | smECE — kernel-smoothed ECE (arXiv:2309.12236) | **Not declined; scheduled.** A consistent calibration measure with no bin-count dependence, and a few dozen lines of stdlib RBF smoothing — the same weight as what is here. Deferred only because switching re-denominates the recorded ECE history (`RF-05`). |
  | Jackknife-debiased binned ECE (Roelofs et al. 2022) | The cheaper half-step: keeps the current binning but removes its small-sample bias. A candidate for `RF-05` if smECE's re-baselining cost is judged too high. |
  | Proper scoring rules alone (Brier / log loss) | Already reported alongside, and strictly better behaved — but a proper score conflates calibration with resolution, so it cannot replace the decomposition ADR-CS-001 exists for. |

- **Fit gap:** the decomposition is reported without confidence intervals on the bins, and the binned ECE estimator itself is biased at this panel size (ADR-CS-004, `RF-05`).
- **Seam:** `src/graphgraph/analysis/calibration.py`
- **Exit cost:** MEDIUM — recorded ECE history is denominated in this binning.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an empty pair set reports `unavailable` rather than a fabricated calibration number.
- **Open questions:** OW-P0-01
