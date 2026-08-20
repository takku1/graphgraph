# Evaluation Analysis (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Turn raw evaluation runs into defensible statements — calibration, stratified reports, and the metrics other subsystems are gated on; does not own the acceptance verdict or the retrieval behavior measured.

## 2. Sub-System Decomposition

- **[Evaluation Protocol and Harness](./evaluation-protocol/SYSTEM.md)** — freeze the suite, resolve expectations, and produce positionally paired run records.
- **[Calibration and Derived Signals](./calibration-scoring/SYSTEM.md)** — turn run records into calibrated confidence, graph summaries, and a deterministic document-authority ordering.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`, `context_packet`
- **Outputs:** `evaluation_metrics`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a suite is versioned THEN results from different versions SHALL NOT be compared directly.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-EA-001:** Instrument red tests come first. A comparison is trusted only as far as its self-comparison reads zero.
- **ADR-EA-002:** Stratified reporting over aggregate scores.
- **ADR-EA-003:** Decomposed at the two independent failure modes this leaf already carried. A harness failure — mis-pairing, an unresolved expectation — makes every downstream number meaningless while each number still looks well formed. A scoring failure leaves the runs correct and only the confidence attached to them wrong, and it is the one the `answer_confidence_ece` gate actually measures. Splitting them keeps a broken instrument distinguishable from a miscalibrated one.
