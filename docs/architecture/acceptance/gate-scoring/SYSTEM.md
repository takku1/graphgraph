# Gate Scoring and Scoreboard (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Score an already-produced packet against sealed truth, account its tokens, and publish the release grade and the bounded proof lanes; does not register cases, drive retrieval, or promote a model judgment into a blocking gate.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One family of total gate functions sharing the token unit the scoreboard reports.

## 3. Interface Contracts

- **Inputs:** `context_packet`, `case_result`
- **Outputs:** `gate_result`, `qualification_verdict`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Token ceilings and irrelevant-context ratios SHALL be gated per case, not averaged.
  - `EvidenceStage:` Observed
- **[Conditional]** IF live-model scoring is requested THEN its verdict SHALL be reported separately from mechanical gates.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a gate is inapplicable to a case THEN it SHALL return `NA` rather than raise.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a real tokenizer is unavailable THEN the count SHALL be labelled as the deterministic proxy rather than reported as a real-encoder measurement.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A high pass rate SHALL NOT hide an open P0 or P1 failure in the release grade.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Recall SHALL NOT fall against the committed quality baseline, and tokens SHALL rise beyond tolerance only when recall or precision improves.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A proof-lane receipt SHALL name the suite it was computed from and state its claim boundary, so a superiority claim cannot outrun its evidence set.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-AGS-001:** Gates are total functions from (probe, task) to a result. A gate that raises turns a scoring defect into an unrunnable suite, which reads identically to a broken build.
- **ADR-AGS-002:** Baseline token comparison uses the deterministic proxy, so installing an optional tokenizer cannot move the unit under a baseline; real encoder counts stay telemetry.
- **ADR-AGS-003:** A proof lane publishes its own claim boundary. The scoreboard reports what the evidence licenses, not the strongest reading of it.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/acceptance/gates.py`, `src/graphgraph/acceptance/quality.py`, `src/graphgraph/acceptance/scoreboard.py`, `src/graphgraph/acceptance/tokens.py`, `src/graphgraph/acceptance/proof_lanes.py`
- **Test Surface Seam:** `tests/test_acceptance.py`, `tests/test_acceptance_quality.py`, `tests/test_proof_lanes.py`, `tests/test_conceptual_heldout.py`

## 7. Measurement Seams

- **Primary Metric:** `acceptance_pass_rate` (target `1.0` on active cases, `direction: higher`)
- **Evaluation Gate Path:** `components/acceptance/measure.sh`
- **Correctness Backpressure:** `components/acceptance/checks.sh`
- **Telemetry Surface:** per-case `GateResult`, token accounting with precision flag, quality baseline deltas, proof-lane receipts.
- **Branching Policy:** isolated candidate; a recall fall against the committed baseline is a hard gate.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the gate semantics are the project's standard of proof for any superiority claim; a general assertion library cannot express "irrelevant-context ratio per case".
- **Selected:** in-repo gate and scoreboard functions on Python 3.10; tiktoken 0.13.0 under the `benchmark` extra for token accounting
- **Standard / protocol:** none — the gate vocabulary is project-specific
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | pytest assertions alone | Gates are domain judgments over packets, not return values, and must report `NA` rather than fail. |
  | LLM-as-judge as the primary gate | Nondeterministic and unfalsifiable as a blocker. |
  | A generic benchmarking/reporting framework | Would own the report format but not the release-floor rule, which is the part with teeth. |

- **Fit gap:** the quality baseline is committed per query set; cross-repository baselines are not modelled.
- **Seam:** `src/graphgraph/acceptance/gates.py`
- **Exit cost:** LOW — gates read a probe result and emit plain data.
- **Cost model:** local runs; live-model scoring is opt-in and separately billed by the caller.
- **Liability transferred:** none for mechanical gates
- **Operational owner:** us
- **Failure mode:** an absent baseline reports "no baseline" rather than silently passing.
- **Open questions:** OW-P0-01
