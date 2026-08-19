# Live Repository Validation (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Scan and interrogate a real repository on disk end to end and report what the tool actually did there; does not register a sealed case, compute a gate verdict, or feed its result back into the qualification board.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One end-to-end live run plus the launcher shim that finds the interpreter owning the installed tool.

## 3. Interface Contracts

- **Inputs:** `context_packet`, `suite_report`
- **Outputs:** `live_validation_report`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Live validation SHALL run against a real repository on disk rather than a bundled fixture.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN the invoking interpreter cannot import `graphgraph` THE SYSTEM SHALL re-execute under the interpreter that owns the installed launcher rather than reporting a validation failure.
  - `EvidenceStage:` Observed
- **[Conditional]** IF no interpreter owning the installed launcher can be found THEN THE SYSTEM SHALL exit with that diagnosis rather than continue against a partial import.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A live-validation result SHALL be reported outside the sealed board, so an external-repository run cannot change the qualification verdict.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Directories the scanner is expected to ignore SHALL be skipped by default, so a live run does not report on caches and build output.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-ALV-001:** Live validation is evidence, not a gate. It runs against whatever repository the operator points at, so its result is not reproducible enough to block a release, and it is deliberately unreachable from the sealed board's import graph.
- **ADR-ALV-002:** The launcher shim re-execs rather than failing. The common operator error is running the script under a different interpreter than the one that owns `graphgraph`, and reporting that as a tool defect would be a false negative about the product.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/acceptance/live_validation.py`, `src/graphgraph/assets/validate_live.py`
- **Test Surface Seam:** `tests/test_live_validation.py`, `tests/test_cli_mcp.py`, `tests/test_cycle5_regressions.py`

## 7. Measurement Seams

- **Primary Metric:** `acceptance_pass_rate` (target `1.0` on active cases, `direction: higher`)
- **Evaluation Gate Path:** `components/acceptance/measure.sh`
- **Correctness Backpressure:** `components/acceptance/checks.sh`
- **Telemetry Surface:** scanned repository root, skipped directories, per-step wall time, structural node-kind counts.
- **Branching Policy:** isolated candidate; live results are reported, never merged into the sealed board's grade.
- **Known granularity gap:** this leaf contributes to the component-level `acceptance_pass_rate` gate but has no metric of its own, because its target repository is operator-chosen and a number computed there is not comparable across runs. No per-child metric has been recorded, and none is asserted here with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — a scripted sequence of the tool's own public commands over a caller-named directory, plus an interpreter-resolution shim that exists only because this repository ships a console launcher.
- **Selected:** in-repo live driver on Python 3.10; `subprocess` and `shutil.which` for launcher resolution
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Folding live runs into the sealed board | Makes the release grade depend on whichever repository the operator had checked out. |
  | A shell script | Would not survive the Windows/POSIX launcher-layout matrix this shim exists to handle. |
  | `pipx run` / an environment manager | Solves installation, not "which interpreter already owns the installed launcher". |

- **Fit gap:** results describe one operator-chosen repository and are not comparable across machines.
- **Seam:** `src/graphgraph/assets/validate_live.py`
- **Exit cost:** LOW — it drives the public command surface only.
- **Cost model:** local runs; one or two interpreter spawns.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unresolvable interpreter exits with the diagnosis rather than reporting a tool defect.
- **Open questions:** OW-AC-10
