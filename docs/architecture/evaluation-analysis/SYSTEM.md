# Evaluation Analysis (L1)

> **Package:** `analysis/` (excluding `navigation.py`, which belongs to [project-atlas](../project-atlas/SYSTEM.md))
> **Related:** [../acceptance/SYSTEM.md](../acceptance/SYSTEM.md), [../../evaluation/README.md](../../evaluation/README.md)

## 1. Intent

Turn raw evaluation runs into **defensible statements**: calibrate the tool's
own confidence against ground truth, rank document authority deterministically,
run versioned and stratified evaluation suites, and compute the metrics other
subsystems are gated on.

Where [acceptance](../acceptance/SYSTEM.md) decides *whether a build qualifies*,
this subsystem decides *whether a measurement means what it claims*.

**Does not own:** the acceptance verdict, or the retrieval behavior measured.

## 2. Decomposition

| Concern | Module |
|---------|--------|
| Confidence calibration against ground truth | `calibration.py` |
| Deterministic document-authority signal | `document_authority.py` |
| Versioned suites, stratified reports, paired comparisons | `eval_protocol.py` |
| Evaluation driver | `eval.py` |
| Metric computation | `metrics.py` |

## 3. Interface contracts

| | |
|--|--|
| **Inputs** | Evaluation task sets, retrieval results, ground-truth labels |
| **Outputs** | Calibration curves, stratified reports, paired deltas, metric values |
| **Consumers** | Acceptance gates, the agent-cycle scorecard, research promotion decisions |
| **Non-goals** | Producing the retrieval results it scores |

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Comparisons SHALL be paired positionally, never keyed on query text.
  - `EvidenceStage: Measured` — duplicate query strings across task files silently paired rows against the wrong task and made an arm differ from itself; the red test is that a baseline compared to itself reads exactly zero.
- **[Ubiquitous]** Expectations SHALL be resolved through the harness's own resolver rather than matched literally.
  - `EvidenceStage: Measured` — expectations are written as labels, not node IDs; literal matching scored every arm at zero.
- **[Ubiquitous]** Reported confidence SHALL be calibrated against outcomes, not asserted.
  - `EvidenceStage: Sampled` — `tests/test_calibration.py`.
- **[Conditional]** IF a suite is versioned THEN results from different versions SHALL NOT be compared directly.
  - `EvidenceStage: Observed` — `eval_protocol.py`.
- **[Ubiquitous]** Document authority SHALL be deterministic, so ranking does not drift between identical runs.
  - `EvidenceStage: Sampled` — `tests/test_document_authority.py`.

## 5. ADRs

- **ADR-EA-001:** Instrument red tests come first. Two bugs here — literal expectation matching and text-keyed pairing — each produced plausible, wrong tables. A comparison is trusted only as far as its self-comparison reads zero.
- **ADR-EA-002:** Stratified reporting over aggregate scores: a single mean hides the language or query-class where the system fails, which is the number that matters.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `analysis/calibration.py`, `document_authority.py`, `eval_protocol.py`, `eval.py`, `metrics.py` |
| **Test surface** | `tests/test_calibration.py`, `tests/test_document_authority.py`, `tests/test_eval_protocol.py`, `tests/test_eval_harness.py` |
| **Component gate** | `components/evaluation-analysis/checks.sh` |
| **Note** | `test_calibration.py` and `test_eval_harness.py` require the active `.graphgraph/graph.gg`; they fail in a bare checkout by design, since they score against a real graph |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Calibration error between reported confidence and observed correctness (`direction: lower`) |
| **Harness path** | `components/evaluation-analysis/measure.sh` — **not yet implemented** (T-B03) |
| **Correctness backpressure** | The four suites above |
| **Caution** | This subsystem measures other subsystems, so its own regressions are silent: nothing downstream fails, the numbers just quietly stop meaning what they say |

## 8. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo; stdlib plus `tiktoken` (`benchmark` extra) for token-denominated metrics
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | scikit-learn / scipy for calibration | A heavy numerical dependency for reliability curves and paired deltas that are a few dozen lines; the project ships stdlib-only at runtime |
  | An MLOps experiment tracker | Solves storage and dashboards, not the correctness of the comparison; the failures here were logic bugs a tracker would have faithfully recorded |

- **Fit gap:** no significance testing on paired comparisons yet — deltas are reported without confidence intervals.
- **BUILD justification:** differentiator — the evidence standard is the project's product claim, and its instruments must be inspectable.
- **Seam:** `analysis/eval_protocol.py`
- **Exit cost:** **MEDIUM**
- **Operational owner:** us
- **Failure mode:** an unresolvable expectation is reported as unresolved rather than scored zero.
- **Open questions:** OW-P0-01, T-B03 — [open-work.md](../../open-work.md)
