# Research Laboratory (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Hold unpromoted candidate mechanisms with an executable claim registry; does not own production ranking and SHALL NOT sit on the hot path.

## 2. Sub-System Decomposition

- **[Claim Registry](./claim-registry/SYSTEM.md)** — bind every recorded claim to a mechanism and a source that still exists.
- **[Candidate Mechanisms](./candidate-mechanisms/SYSTEM.md)** — unpromoted retrieval and coverage experiments held off the production path.
- **[Benchmark Probes](./benchmark-probes/SYSTEM.md)** — small reproducible probes that produce a number for a specific question.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `research_scores`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Mechanisms in this laboratory SHALL be off the production path.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-RE-001:** Research code ships in the package but never on the hot path.
- **ADR-RE-002:** The claim registry is executable; a deleted source is a test failure.
- **ADR-RE-003:** Negative results are retained with the same status as positive ones.
- **ADR-RE-004:** Decomposed at the boundary between the *record* of an experiment, the *mechanism* under test, and the *probe* that measures one. A registry failure is a bookkeeping defect, a mechanism failure is a refuted hypothesis, and a probe failure is a broken instrument — three different remedies, so three contracts.
