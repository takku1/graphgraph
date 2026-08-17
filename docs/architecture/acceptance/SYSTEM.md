# Acceptance and Qualification (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Decide whether a GraphGraph build qualifies on a sealed black-box task set; does not own retrieval behavior, seed retrieval with ground truth, or treat a model judgment as a blocking gate.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One harness, one task set, mechanical gates only.

## 3. Interface Contracts

- **Inputs:** `context_packet`
- **Outputs:** `qualification_verdict`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Ground truth SHALL be used only to score a produced packet, never as a retrieval seed.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a probe reports completeness THEN the harness SHALL verify required symbols are present before accepting it, as checked by `tests/test_acceptance.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Token ceilings and irrelevant-context ratios SHALL be gated per case, not averaged.
  - `EvidenceStage:` Observed
- **[Conditional]** IF live-model scoring is requested THEN its verdict SHALL be reported separately from mechanical gates.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A case SHALL fail closed: an unrunnable probe is not a pass, as checked by `tests/test_acceptance_exec.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-AC-001:** Black-box only. A harness that can see the expected answer measures the fixture.
- **ADR-AC-002:** Cases are named against recorded defects (GG10-LC-*).
- **ADR-AC-003:** Mechanical gates may block; a model judgment is evidence, not a gate.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/acceptance/proof_lanes.py`, `src/graphgraph/acceptance/__init__.py`, `src/graphgraph/acceptance/__main__.py`, `src/graphgraph/acceptance/affected_tests_case.py`, `src/graphgraph/acceptance/boundary.py`, `src/graphgraph/acceptance/cache_latency.py`, `src/graphgraph/acceptance/delete_rename.py`, `src/graphgraph/acceptance/docs_case.py`, `src/graphgraph/acceptance/execution.py`, `src/graphgraph/acceptance/gates.py`, `src/graphgraph/acceptance/incremental.py`, `src/graphgraph/acceptance/live_validation.py`, `src/graphgraph/acceptance/model.py`, `src/graphgraph/acceptance/parity.py`, `src/graphgraph/acceptance/qualification.py`, `src/graphgraph/acceptance/quality.py`, `src/graphgraph/acceptance/runner.py`, `src/graphgraph/acceptance/scope_case.py`, `src/graphgraph/acceptance/scoreboard.py`, `src/graphgraph/acceptance/tasks.py`, `src/graphgraph/acceptance/test_exec.py`, `src/graphgraph/acceptance/tokens.py`, `src/graphgraph/assets/validate_live.py`
- **Test Surface Seam:** `tests/test_acceptance.py`, `tests/test_acceptance_exec.py`, `tests/test_acceptance_quality.py`, `tests/test_live_validation.py`, `tests/test_proof_lanes.py`.

## 7. Measurement Seams

- **Primary Metric:** `acceptance_pass_rate` (target `1.0` on active cases, `direction: higher`)
- **Evaluation Gate Path:** `components/acceptance/measure.sh`
- **Correctness Backpressure:** `components/acceptance/checks.sh`
- **Telemetry Surface:** per-case `GateResult`, token accounting, scoreboard.
- **Branching Policy:** isolated candidate; missing corpus yields no verdict, not a pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the qualification procedure is the project's standard of proof for any superiority claim.
- **Selected:** in-repo harness on Python 3.10; tiktoken 0.13.0 under the `benchmark` extra for token accounting
- **Standard / protocol:** none — the task set is project-specific
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | SWE-bench | Measures patch success, not context-representation cost. |
  | pytest alone | Gates are domain judgments over packets, not return values. |
  | LLM-as-judge as the primary gate | Nondeterministic and unfalsifiable as a blocker. |

- **Fit gap:** the canonical corpus is one external repository; rotating multi-language qualification is OW-AC-10.
- **Seam:** `src/graphgraph/acceptance/execution.py`
- **Exit cost:** LOW — the harness observes the public surface.
- **Cost model:** local runs; live-model scoring is opt-in and separately billed by the caller.
- **Liability transferred:** none for mechanical gates
- **Operational owner:** us
- **Failure mode:** a missing target corpus yields no verdict rather than a default pass.
- **Open questions:** OW-AC-10, OW-P0-01
