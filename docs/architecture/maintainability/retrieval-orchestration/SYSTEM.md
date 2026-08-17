# Retrieval Orchestration (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Turn a retrieval request into a bounded evidence result through explicit phase interfaces; does not change ranking formulas, query-class policy, or packet encoding.

## 2. Sub-System Decomposition

- **[Request Feasibility](./request-feasibility/SYSTEM.md)** — normalize the request and decide whether corpus evidence permits retrieval.
- **[Anchor and Search Execution](./anchor-search/SYSTEM.md)** — produce grounded starts and ranked candidates with receipts.
- **[Retrieval Result Assembly](./result-assembly/SYSTEM.md)** — expand, reserve, select, score quality, and construct the final result.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `orchestration_modules`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** `retrieve_context` SHALL remain the public orchestration facade during decomposition, as checked by `tests/test_retrieval_phase_characterization.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN a phase abstains or reports incomplete evidence THE SYSTEM SHALL preserve the current status, control reason, and zero/non-zero packet behavior, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a phase extraction changes retrieval output THEN THE SYSTEM SHALL reject the change even when structural complexity decreases, as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Measured

## 5. Architectural Decisions (ADRs)

- **ADR-RO-001:** Split by independently failing evidence phases, not helper size.
- **ADR-RO-002:** Carry explicit immutable phase records rather than a shared mutable context dictionary.
- **ADR-RO-003:** No ranking or threshold changes are allowed in this cleanup tree; empirical algorithm changes belong to OW-Q03 and OW-Q04.
