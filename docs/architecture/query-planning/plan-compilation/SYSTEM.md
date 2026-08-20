# Plan Compilation (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Assemble a class, a budget, and a per-class packet choice into one typed, versioned, read-only plan, and compile unrestricted user text into a typed operator without inferring a mutation; does not classify the request or size the budget itself.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One plan record assembled by one conservative compiler.

## 3. Interface Contracts

- **Inputs:** `query_text`, `query_route`, `expansion_budget`, `token_cost_model`
- **Outputs:** `query_plan`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a request cannot be represented without dropping a clause THEN THE SYSTEM SHALL fall back to the context compiler rather than compile a lossy exact operator.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** An emitted plan SHALL carry its planner and compiler version, so a recorded plan cannot be read under a later planner's semantics.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-PC-001:** Per-class encoding heuristics are defaults, not law; packet choice is a measured token-cost decision, and structural classes keep their packet even when the query uses documentation vocabulary.
- **ADR-PC-002:** The compiler is conservative by construction: exact operators are selected only when the request survives representation intact, and mutating lifecycle operations are never inferred from prose.
- **ADR-PC-003:** The plan is a frozen record with an explicit version string rather than a mutable dictionary, so every consumer of a plan can be shown to read the same fields.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/planning/__init__.py`, `src/graphgraph/planning/context.py`, `src/graphgraph/planning/packet.py`, `src/graphgraph/planning/query_compiler.py`
- **Test Surface Seam:** `tests/test_query_compiler.py`, `tests/test_planning.py`, `tests/test_public_contracts.py`

## 7. Measurement Seams

- **Primary Metric:** `plan_latency_us` (median `plan_context` build over the gate's query set, `direction: lower`)
- **Evaluation Gate Path:** `components/query-planning/measure.sh`
- **Correctness Backpressure:** `components/query-planning/checks.sh`
- **Telemetry Surface:** chosen operator and its fallback, cost class, mutating flag, hops, packet target, planner and compiler version.
- **Branching Policy:** isolated candidate; explicit override and public-contract parity must stay green.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — assembling four already-decided fields into a frozen record, behind a compiler whose whole value is what it refuses to infer. A general query-language front end would widen exactly the surface this leaf narrows.
- **Selected:** in-repo plan compiler on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | A parser generator (Lark, ANTLR) | A grammar for prose that is deliberately not a language; the fallback path is the design. |
  | LLM-generated query plans | Puts a model call on the hot path and can infer a mutation the user never asked for. |
  | Cypher / GraphQL as the plan format | A general query language re-admits mutation and ad-hoc traversal the retrieval budget exists to bound. |

- **Fit gap:** the compiler represents a closed operator set; anything outside it degrades to ranked retrieval rather than failing.
- **Seam:** `src/graphgraph/planning/context.py`
- **Exit cost:** LOW — the plan record is the only contract retrieval reads.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unrepresentable request compiles to the context fallback, never to a mutating operator.
- **Open questions:** OW-Q06
