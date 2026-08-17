# Structural Complexity Ratchet (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Expose structural-complexity drift as a stable machine gate; does not claim that a diagnostic is a defect or prescribe how a flagged function must be decomposed.

## 2. Sub-System Decomposition

**Atomic leaf (procured).** Ruff is adopted behind a count-ratchet wrapper.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `structural_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN the maintainability gate runs THE SYSTEM SHALL analyze all production Python files with the same four stable rules, as checked by `tests/test_maintainability.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF the diagnostic count exceeds 248 THEN THE SYSTEM SHALL fail the maintainability gate, as checked by `components/maintainability/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** The default Ruff profile SHALL remain independently green, as checked by `components/maintainability/checks.sh`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-SR-001:** Use a count ratchet as the first gate. Per-symbol budgets remain a later refinement because line-based identities make harmless moves look like regressions.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `tests/test_maintainability.py`, `components/maintainability/baseline.json`, `components/maintainability/measure.py`.
- **Test Surface Seam:** `tests/test_maintainability.py`.

## 7. Measurement Seams

- **Primary Metric:** `structural_complexity_diagnostics` (target `<=248`, `direction: lower`)
- **Evaluation Gate Path:** `components/maintainability/measure.sh`
- **Correctness Backpressure:** `components/maintainability/checks.sh`
- **Telemetry Surface:** one measurement JSON object on stdout.
- **Branching Policy:** merge only when checks pass and the count does not regress.

## 8. Technology Resolution

- **Decision class:** WRAP
- **Selected:** Ruff 0.15.21 from `uv.lock`, invoked through its JSON output
- **Dependency:** ruff
- **Pin:** 0.15.21
- **Adapter namespace:** `components/maintainability`
- **Standard / protocol:** Ruff diagnostic JSON
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Python 3.10 `ast` visitor | BUILD would recreate mature branch/statement counting. |
  | Import Linter 2.13 | Enforces import architecture, not control-flow complexity. |

- **Fit gap:** a total count can hide one new diagnostic behind one removed diagnostic.
- **Seam:** `tests/test_maintainability.py`, `components/maintainability/measure.py`
- **Exit cost:** LOW — replace one subprocess adapter and preserve the JSON/count contract.
- **Cost model:** zero runtime cost; CI cost is one Ruff source scan.
- **Liability transferred:** parsing Python and maintaining complexity-rule implementations.
- **Operational owner:** us (wrapper and baseline); Ruff (diagnostic engine)
- **Failure mode:** missing Ruff or invalid JSON fails the gate as an instrument error.
- **Open questions:** none
