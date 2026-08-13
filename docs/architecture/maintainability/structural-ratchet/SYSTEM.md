# Structural Complexity Ratchet (L2)

## 1. System Intent & Responsibility

Expose structural-complexity drift as a stable machine gate; does not claim
that a diagnostic is a defect or prescribe how a flagged function must be
decomposed.

## 2. Sub-System Decomposition

Atomic leaf (wrapped adopted tool).

## 3. Interface Contracts

- **Inputs:** `src/graphgraph/**/*.py`; Ruff rule set C901, PLR0911, PLR0912, PLR0915.
- **Outputs:** diagnostic count, baseline comparison, and structured measurement JSON.

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN the maintainability gate runs THE SYSTEM SHALL analyze all production Python files with the same four stable rules.
  - `EvidenceStage: Sampled` — `tests/test_maintainability.py`.
- **[Conditional]** IF the diagnostic count exceeds 248 THEN THE SYSTEM SHALL fail the maintainability gate.
  - `EvidenceStage: Measured` — Ruff 0.15.21 reported 248 diagnostics after the retrieval decomposition on 2026-08-13.
- **[Ubiquitous]** The default Ruff profile SHALL remain independently green.
  - `EvidenceStage: Sampled` — `components/maintainability/checks.sh`.

## 5. Architectural Decisions (ADRs)

- **ADR-SR-001:** Use a count ratchet as the first gate. Per-symbol budgets remain a later refinement because line-based identities make harmless moves look like regressions.

## 6. Leaf Execution & Test Seam

- **Implementation File(s):** `tests/test_maintainability.py`, `components/maintainability/baseline.json`, `components/maintainability/checks.sh`, `components/maintainability/measure.py`, `components/maintainability/measure.sh`.
- **Test Surface Seam:** `tests/test_maintainability.py` (`components/maintainability/checks.sh`).

## 7. Measurement Seams

- **Primary Metric:** `structural_complexity_diagnostics` (target `<=248`, `direction: lower`).
- **Harness Path:** `components/maintainability/measure.sh`.
- **Correctness Backpressure:** `components/maintainability/checks.sh`.
- **Telemetry Surface:** one measurement JSON object on stdout.
- **Branching Policy:** merge only when checks pass, the count does not regress, and owning component metrics do not regress.

## 8. Technology Resolution

- **Decision class:** WRAP.
- **Selected:** Ruff 0.15.21 from `uv.lock`, invoked through its JSON output.
- **Standard / protocol:** Ruff diagnostic JSON.
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Python 3.10 `ast` visitor | BUILD would recreate mature branch/statement counting and make GraphGraph own rule compatibility. |
  | Import Linter 2.13 | Enforces import architecture, not control-flow or statement complexity; it cannot produce this metric. |

- **Fit gap:** a total count can hide one new diagnostic behind one removed diagnostic; the gate is a ratchet, not proof of per-symbol improvement.
- **Seam:** `tests/test_maintainability.py::_ruff_complexity_diagnostics`.
- **Exit cost:** LOW — replace one subprocess adapter and preserve the JSON/count contract.
- **Cost model:** zero runtime cost and one existing dev dependency; CI cost is one Ruff source scan.
- **Liability transferred:** parsing Python and maintaining complexity-rule implementations.
- **Operational owner:** us (wrapper and baseline); Ruff (diagnostic engine).
- **Failure mode:** missing Ruff or invalid JSON fails the gate as an instrument error.
- **Open questions:** none.
