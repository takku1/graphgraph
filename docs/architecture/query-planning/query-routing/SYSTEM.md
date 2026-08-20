# Query Routing and Class Assignment (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Score a request into one of the closed set of query classes with its own route confidence, and select the policies whose path and tag scopes apply to it; does not size a budget, price a packet, or assemble the plan the retriever executes.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One additive log-linear intent classifier over a closed class set, plus the policy scope matcher it shares a request with.

## 3. Interface Contracts

- **Inputs:** `query_text`
- **Outputs:** `query_route`, `policy_selection`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF routing is automatic THEN an explicit class override SHALL still win, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Route confidence SHALL NOT be reported as retrieval confidence.
  - `EvidenceStage:` Observed
- **[State-driven]** WHILE no held-out utility gain exists THE SYSTEM SHALL keep deterministic routing, as checked by `tests/test_planning.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF no class is decisive THEN THE SYSTEM SHALL abstain to a broad fallback class rather than invent a new one.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-QR-001:** Routing stays deterministic while no held-out utility gain exists (OW-Q03). A fitted model is a later replacement, not the current leaf.
- **ADR-QR-002:** The router is additive and log-linear so every class assignment decomposes into the signals that fired. Replacing the confidence blend with a calibrated softmax posterior is deferred to the evaluation loop, because it moves the abstention boundary and must be measured rather than guessed.
- **ADR-QR-003:** Route confidence is class certainty about the text, not evidence about the graph, and is named separately for that reason. A policy scope is matched over whole wildcard segments, not by a prefix test, because a prefix test silently matched every path for a leading-wildcard pattern.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/planning/policies.py`, `src/graphgraph/planning/routing.py`, `src/graphgraph/planning/types.py`
- **Test Surface Seam:** `tests/test_planning.py`, `tests/test_public_contracts.py`

## 7. Measurement Seams

- **Primary Metric:** `plan_latency_us` (median plan build over the gate's query set, `direction: lower`)
- **Evaluation Gate Path:** `components/query-planning/measure.sh`
- **Correctness Backpressure:** `components/query-planning/checks.sh`
- **Telemetry Surface:** chosen class, score margin, route confidence, signals that fired, selected policies.
- **Branching Policy:** isolated candidate; explicit override and public-contract parity must stay green.
- **Known granularity gap:** this leaf currently shares the component-level `plan_latency_us` gate and has no routing-accuracy metric wired into `measure.sh`; routing accuracy remains gated on the held-out labelled set in OW-Q03. Recorded as an open granularity gap rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — a weighted signal sum over a closed class set, whose every misroute is readable from the signals that fired.
- **Selected:** in-repo deterministic router on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | LLM classifier | A model call on the hot path; nondeterministic routing regressions. |
  | Learned ranker | Gated on held-out utility (OW-Q03); not rejected, not default. |
  | Off-the-shelf intent classifier | Ships a model to decide nine in-repo classes, and its confidence would need the same calibration work anyway. |

- **Fit gap:** a request that fits no class routes to a default rather than inventing a class.
- **Seam:** `src/graphgraph/planning/routing.py`
- **Exit cost:** LOW — swapping the router does not change budget or packet contracts.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unroutable query falls back to a broad default class.
- **Open questions:** OW-Q03, OW-Q06
