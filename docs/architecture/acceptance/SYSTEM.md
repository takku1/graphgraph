# Acceptance and Qualification (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Decide whether a GraphGraph build qualifies on a sealed black-box task set; does not own retrieval behavior, seed retrieval with ground truth, or treat a model judgment as a blocking gate.

## 2. Sub-System Decomposition

- **[Case Registry and Ground Truth](./case-registry/SYSTEM.md)** — register the canonical cases and hold their sealed ground truth.
- **[Gate Scoring and Scoreboard](./gate-scoring/SYSTEM.md)** — score an already-produced packet and publish the release grade.
- **[Probe Execution and Suite Driver](./harness-execution/SYSTEM.md)** — drive the public retrieval surface and run the selected suite.
- **[Live Repository Validation](./live-validation/SYSTEM.md)** — validate a real external repository outside the sealed board.

## 3. Interface Contracts

- **Inputs:** `context_packet`
- **Outputs:** `qualification_verdict`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A case SHALL fail closed: an unrunnable probe is not a pass, as checked by `tests/test_acceptance_exec.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-AC-001:** Black-box only. A harness that can see the expected answer measures the fixture.
- **ADR-AC-002:** Cases are named against recorded defects (GG10-LC-*).
- **ADR-AC-003:** Mechanical gates may block; a model judgment is evidence, not a gate.
- **ADR-AC-004:** Decomposed at the four independent failure modes the pre-split leaf already carried: a case's sealed ground truth can be wrong, a gate or scoreboard can score a correct packet wrongly, the probe driver can fail to run a case at all, and the live external-repository run can break without any sealed case moving. Each pre-split invariant lands in exactly one child, which is the evidence the seam is real rather than a file-tree rename.
