# Query Planning (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Map a natural-language or typed request to a query class, expansion budget, and packet choice; does not retrieve nodes or render packets.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Deterministic router and budget model.

## 3. Interface Contracts

- **Inputs:** `query_text`
- **Outputs:** `query_plan`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF routing is automatic THEN an explicit class override SHALL still win, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Read-only query facades SHALL NOT imply mutation or a silent full reindex.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Route confidence SHALL NOT be reported as retrieval confidence.
  - `EvidenceStage:` Observed
- **[State-driven]** WHILE no held-out utility gain exists THE SYSTEM SHALL keep deterministic routing, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-QP-001:** Routing stays deterministic while no held-out utility gain exists (OW-Q03). A fitted model is a later replacement, not the current leaf.
- **ADR-QP-002:** Per-class encoding heuristics are defaults, not law; packet choice is a measured token-cost decision.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/planning/__init__.py`, `src/graphgraph/planning/budgets.py`, `src/graphgraph/planning/context.py`, `src/graphgraph/planning/packet.py`, `src/graphgraph/planning/policies.py`, `src/graphgraph/planning/query_compiler.py`, `src/graphgraph/planning/routing.py`, `src/graphgraph/planning/shape.py`, `src/graphgraph/planning/stats.py`, `src/graphgraph/planning/token_cost.py`, `src/graphgraph/planning/types.py`
- **Test Surface Seam:** `tests/test_planning.py`, `tests/test_query_compiler.py`, `tests/test_public_contracts.py`.

## 7. Measurement Seams

- **Primary Metric:** `routing_accuracy` (held-out labelled set, `direction: higher`)
- **Evaluation Gate Path:** `components/query-planning/measure.sh`
- **Correctness Backpressure:** `components/query-planning/checks.sh`
- **Telemetry Surface:** chosen class, budget, packet target, and route-confidence vs answerability-confidence.
- **Branching Policy:** isolated candidate; explicit override and public-contract parity must stay green.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — a deterministic mapping over a closed class set whose failures are inspectable.
- **Selected:** in-repo deterministic router on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | LLM classifier | A model call on the hot path; nondeterministic routing regressions. |
  | Learned ranker | Gated on held-out utility (OW-Q03); not rejected, not default. |
  | Fixed single strategy | Measured worse: path depth wastes budget on direct lookup. |

- **Fit gap:** a request that fits no class routes to a default rather than inventing a class.
- **Seam:** `src/graphgraph/planning/routing.py`
- **Exit cost:** LOW — swapping the router does not change retrieval or packet contracts.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unroutable query falls back to a default class and budget.
- **Open questions:** OW-Q03, OW-Q06
