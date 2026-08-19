# Token Estimation (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Price packet text in calibrated token units without loading a runtime tokenizer; does not render packets, declare which formats exist, or decide whether a packet validates.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One calibrated estimator over rendered packet text.

## 3. Interface Contracts

- **Inputs:** `context_packet`
- **Outputs:** `token_estimate`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Estimator mean absolute error SHALL stay at or below 5% and p95 at or below 10% against production tokenizers, as checked by `components/context-packets/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** The estimator SHALL NOT rank one packet format above another through a systematic cross-format bias, so format decisions rest on cost rather than on estimator artifact.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Estimation SHALL NOT import a runtime tokenizer on the cold path, so pricing a packet stays inside the cold-start budget.
  - `EvidenceStage:` Observed
- **[Conditional]** IF the calibration constants change THEN token comparisons recorded before that change SHALL be treated as incommensurable rather than compared directly.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-TE-001:** A calibrated proxy, not a real tokenizer. The packet is priced on every compile, and importing a tokenizer would put a model dependency and its load time inside the cold-start budget the product sells.
- **ADR-TE-002:** A whitespace-blind word count is not an estimator. The original proxy carried a 47% cross-format spread, which silently mis-ranked every format decision above it; that was a project-level defect, not a rounding issue.
- **ADR-TE-003:** Recalibration invalidates prior token comparisons. Constants are versioned rather than tuned in place, because a cost metric that changes meaning without notice makes every historical baseline a false comparison.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/packets/metrics.py`
- **Test Surface Seam:** `tests/test_packets.py`

## 7. Measurement Seams

- **Primary Metric:** `packet_token_units` (`direction: lower`)
- **Evaluation Gate Path:** `components/context-packets/measure.sh`
- **Correctness Backpressure:** `components/context-packets/checks.sh`
- **Telemetry Surface:** estimated units per packet, per-format estimate, calibration constant version.
- **Branching Policy:** isolated candidate; an estimator change must report MAE and p95 against the tokenizer panel, and re-baselines every dependent token comparison.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Cost inversion at this scale — the estimator runs on every compile inside a millisecond budget, and the alternative moves a tokenizer import and its model load onto the cold path.
- **Selected:** in-repo calibrated estimator on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | `tiktoken` at runtime | Correct by construction but puts a model-data load inside the cold-start budget; retained offline as the calibration oracle rather than the hot path. |
  | HuggingFace `tokenizers` | Heavier dependency and a per-model vocabulary for a number used only to compare packets. |
  | Character count / 4 | The naive heuristic this replaced; carries the cross-format bias ADR-TE-002 records. |
  | Split conformal prediction over the estimator's residuals | **The principled upgrade to this leaf's guarantee class.** MAE ≤5% / p95 ≤10% are empirical summaries on a fitted panel: they describe the calibration set, and say nothing provable about the next packet. Split conformal wraps the existing estimator and returns a distribution-free, finite-sample interval — "this packet is within ±N tokens with 95% coverage" — under exchangeability alone, with no distributional assumption and no change to the estimator itself. It converts a fitted average into a stated guarantee, which is what a budget enforcer actually needs. Tracked as `RF-07`. |
  | Conformalized quantile regression | The variant to prefer if residuals are heteroskedastic across formats — likely here, since ADR-TE-002 records that cross-format spread was the original defect. |

- **Fit gap:** calibrated against a fixed tokenizer panel; a consumer using an unfitted tokenizer is priced by extrapolation.
- **Seam:** `src/graphgraph/packets/metrics.py`
- **Exit cost:** LOW — one estimator function behind the catalog's cost model.
- **Cost model:** in-process CPU; no model load, no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unrecognized format falls back to the generic estimate and records that it did.
- **Open questions:** OW-AC-07 is met; drift re-checks belong to the tokenizer panel refresh.
