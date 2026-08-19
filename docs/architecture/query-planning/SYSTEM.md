# Query Planning (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Map a natural-language or typed request to a query class, expansion budget, and packet choice; does not retrieve nodes or render packets.

## 2. Sub-System Decomposition

- **[Query Routing and Class Assignment](./query-routing/SYSTEM.md)** — score a request into a query class with its own confidence, and select the policies that scope it.
- **[Budget and Token-Cost Model](./budget-model/SYSTEM.md)** — profile graph shape and the fitted packet token surface into a node budget.
- **[Plan Compilation](./plan-compilation/SYSTEM.md)** — assemble class, budget, and packet choice into one typed read-only plan.

## 3. Interface Contracts

- **Inputs:** `query_text`
- **Outputs:** `query_plan`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Read-only query facades SHALL NOT imply mutation or a silent full reindex.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-QP-001:** Routing stays deterministic while no held-out utility gain exists (OW-Q03). A fitted model is a later replacement, not the current leaf.
- **ADR-QP-002:** Per-class encoding heuristics are defaults, not law; packet choice is a measured token-cost decision.
- **ADR-QP-003:** Decomposed at three failure modes that are independently observable in the emitted plan. Routing fails by picking the wrong class while the budget arithmetic stays correct; the cost model fails by choosing a wrong node count for a correctly identified class; compilation fails by assembling correct parts into a plan that promises the wrong operator or a mutation. Nothing below compilation knows what the compiled plan looks like, which is why compilation is the only child that owns `plan_latency_us`. The one back-reference is the shared query tokenizer, which lives with the budget model and is read by the router; it is called out here rather than duplicated, because a second tokenizer would let routing and budgeting disagree about what a query's words are.
