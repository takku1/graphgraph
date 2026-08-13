# Retrieval Orchestration Decomposition (L2)

## 1. System Intent & Responsibility

Turn a retrieval request into a bounded evidence result through explicit phase
interfaces; does not change ranking formulas, query-class policy, or packet
encoding.

## 2. Sub-System Decomposition

- **[Request Feasibility](./request-feasibility/SYSTEM.md)** — normalize the request and decide whether corpus evidence permits retrieval.
- **[Anchor and Search Execution](./anchor-search/SYSTEM.md)** — produce grounded starts and ranked candidates with receipts.
- **[Result Assembly](./result-assembly/SYSTEM.md)** — expand, reserve, select, score quality, and construct the final retrieval result.

## 3. Interface Contracts

- **Inputs:** graph snapshot, query text/class, budgets, scopes, source evidence, and optional seed IDs.
- **Outputs:** the existing `RetrievalResult` and its answerability, quality, facet, source, and affected-test receipts.

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** `retrieve_context` SHALL remain the public orchestration facade during decomposition.
  - `EvidenceStage: Sampled` — public signature, defaults, annotations, return type, and invalid-scope behavior remained unchanged in the independent audit.
- **[Event-driven]** WHEN a phase abstains or reports incomplete evidence THE SYSTEM SHALL preserve the current status, control reason, and zero/non-zero packet behavior.
  - `EvidenceStage: Sampled` — 251 focused retrieval tests and 1,191 full-suite tests passed; six result/Receipt cases were byte-identical.
- **[Conditional]** IF a phase extraction changes retrieval output THEN THE SYSTEM SHALL reject the change even when structural complexity decreases.
  - `EvidenceStage: Measured` — sampled node recall and tokens were identical, warm latency improved 1.396%, and structural diagnostics fell from 249 to 248.

## 5. Architectural Decisions (ADRs)

- **ADR-RO-001:** Split by independently failing evidence phases, not helper size.
- **ADR-RO-002:** Carry explicit immutable phase records rather than a shared mutable context dictionary.
- **ADR-RO-003:** No ranking or threshold changes are allowed in this cleanup tree; empirical algorithm changes belong to OW-Q03/Q04.
