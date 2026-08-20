# Probe Execution and Suite Driver (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Drive GraphGraph's public retrieval surface as a black-box probe, select and run the requested suite, and execute recommended test commands well enough to classify their outcome; does not define a case, own a gate verdict, or reach a live external repository on its own.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One probe driver plus the suite selector that fans it over the registry.

## 3. Interface Contracts

- **Inputs:** `context_packet`, `acceptance_task_set`, `gate_result`
- **Outputs:** `probe_result`, `suite_report`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a probe reports completeness THEN the harness SHALL verify required symbols are present before accepting it, as checked by `tests/test_acceptance.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a recommended test command selects zero tests THEN the run SHALL be classified a failed recommendation even when the runner exits zero.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN an unknown case id is requested THE SYSTEM SHALL reject the selection rather than silently run a smaller suite.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a packet format carries no node paths THEN the probe SHALL leave paths empty rather than guess them, so a path assertion cannot pass vacuously.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Executing a recommended test command SHALL require explicit opt-in, so a shared board never launches a toolchain unexpectedly.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-AHE-001:** The probe drives only the public retrieval surface. A driver with private access measures the implementation rather than the product.
- **ADR-AHE-002:** Test-runner output is normalized into one outcome type, and the classifier is pure, so the ecosystem layer stays trustworthy on a machine where that toolchain is not installed.
- **ADR-AHE-003:** Suite selection rejects unknown ids. A typo that quietly narrows the board is indistinguishable from a green board.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/acceptance/__init__.py`, `src/graphgraph/acceptance/__main__.py`, `src/graphgraph/acceptance/execution.py`, `src/graphgraph/acceptance/runner.py`, `src/graphgraph/acceptance/test_exec.py`
- **Test Surface Seam:** `tests/test_acceptance.py`, `tests/test_acceptance_exec.py`

## 7. Measurement Seams

- **Primary Metric:** `acceptance_pass_rate` (target `1.0` on active cases, `direction: higher`)
- **Evaluation Gate Path:** `components/acceptance/measure.sh`
- **Correctness Backpressure:** `components/acceptance/checks.sh`
- **Telemetry Surface:** graph identity, per-probe packet and token counts, selected case ids, test-command classifications.
- **Branching Policy:** isolated candidate; missing corpus yields no verdict, not a pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — driving the compiler through its public surface and recording a black-box receipt is the qualification procedure itself, not a generic runner concern.
- **Selected:** in-repo probe driver on Python 3.10; `argparse` for the `python -m graphgraph.acceptance` entry point; `subprocess` for opt-in test-command execution
- **Standard / protocol:** none — the probe receipt is project-specific
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | pytest as the suite driver | Cases must report `pending` and `na`, which a pass/fail runner cannot express without lying. |
  | tox / nox | Orchestrates environments; the missing piece is packet-level receipts, not environment matrixing. |
  | A per-ecosystem plugin for every test runner | Output normalization is a handful of regexes; a plugin system would add install weight for the same classification. |

- **Fit gap:** execution is opt-in, so a board run on a machine without a runner records a skip rather than a green execution result.
- **Seam:** `src/graphgraph/acceptance/execution.py`
- **Exit cost:** LOW — the driver observes the public surface.
- **Cost model:** local runs; one interpreter plus any opt-in test-runner spawn.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a missing target corpus yields no verdict rather than a default pass.
- **Open questions:** OW-P0-01
