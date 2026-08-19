# Budget and Token-Cost Model (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Decide how many nodes a query may spend, from a per-class complexity prior adjusted by measured graph shape and priced against the fitted per-packet token surface; does not choose the query class, pick the packet, or assemble the plan.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One regularized budget optimum priced by one fitted token surface.

## 3. Interface Contracts

- **Inputs:** `query_text`, `query_route`
- **Outputs:** `expansion_budget`, `token_cost_model`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF the caller supplies an explicit node budget THEN THE SYSTEM SHALL honor it for every query class rather than clamp it down to an internal cap.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a packet has no calibrated token surface THEN THE SYSTEM SHALL fall back to the default packet's surface rather than price it at zero.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A recommended node budget SHALL be derived from measured graph shape and the class complexity prior, not from a single fixed constant.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Token-surface coefficients SHALL be re-derived by the calibration fit rather than hand-tuned when packet syntax changes.
  - `EvidenceStage:` Unknown

## 5. Architectural Decisions (ADRs)

- **ADR-BM-001:** The budget is the closed-form optimum of a regularized utility — diminishing recall against a linear token penalty — rather than a hand-set cap per class, so the shape adjustments are inputs to one formula instead of a table of exceptions.
- **ADR-BM-002:** An explicit `--max-nodes` is the caller's budget and is never clamped down. Raising it is an agent's primary recovery move when an answer comes back incomplete; the earlier downward clamp made every value at or above the internal cap produce an identical budget.
- **ADR-BM-003:** Per-packet token costs are an ordinary least-squares surface fit over real project subgraphs and validated leave-one-project-out. The surface is a planning proxy: it is refit when packet syntax changes, never hand-adjusted to make a decision come out.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/planning/budgets.py`, `src/graphgraph/planning/shape.py`, `src/graphgraph/planning/stats.py`, `src/graphgraph/planning/token_cost.py`
- **Test Surface Seam:** `tests/test_planning.py`

## 7. Measurement Seams

- **Primary Metric:** `plan_latency_us` (median plan build over the gate's query set, `direction: lower`)
- **Evaluation Gate Path:** `components/query-planning/measure.sh`
- **Correctness Backpressure:** `components/query-planning/checks.sh`
- **Telemetry Surface:** base and recommended budget, complexity prior and shape multipliers applied, marginal node/edge token cost, under-extraction warning.
- **Branching Policy:** isolated candidate; budget recommendations stay candidate-only until the packet-winner agreement of the refit surface is re-measured.
- **Known granularity gap:** this leaf currently shares the component-level `plan_latency_us` gate; the surface's out-of-sample error and packet-winner agreement are measured by the refit script, not by `measure.sh`. Recorded as an open granularity gap rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — a closed-form optimum and a three-coefficient linear surface. The fit itself is the reviewable artifact, and a regression library would add a dependency to evaluate a polynomial at runtime.
- **Selected:** in-repo budget model on Python 3.10, stdlib `math` only; coefficients fit offline
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | numpy / scikit-learn at runtime | Imported on every plan to evaluate three multiplications; the fit is offline. |
  | A fixed node cap per class | Measured worse: ignores graph size and density, so the same cap over- and under-spends on different repositories. |
  | Calling a real tokenizer during planning | Puts a tokenizer on the hot path for an estimate the surface already predicts within its measured error. |

- **Fit gap:** the surface is fit on real project subgraphs and does not extrapolate to packet formats it has never seen; those fall back to the default surface.
- **Seam:** `src/graphgraph/planning/token_cost.py`
- **Exit cost:** MEDIUM — recorded budget and token-proxy figures are denominated in this surface.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an uncalibrated packet is priced with the default surface rather than at zero cost.
- **Open questions:** OW-Q05, OW-Q06
