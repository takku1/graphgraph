# Structural Retrieval (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Discover anchors, expand a structurally constrained neighborhood, and select a budgeted subgraph; does not own semantic embedding, packet encoding, or query-class assignment.

## 2. Sub-System Decomposition

- **[Request Feasibility](./request-feasibility/SYSTEM.md)** — normalize the request and decide whether corpus evidence permits retrieval at all.
- **[Anchor Discovery](./anchor-discovery/SYSTEM.md)** — produce grounded starts and ranked candidates with receipts.
- **[Facet Obligation](./facet-obligation/SYSTEM.md)** — derive per-facet evidence obligations and reserve anchors that discharge them.
- **[Neighborhood Expansion](./neighborhood-expansion/SYSTEM.md)** — walk structural edges outward from seated anchors under a hop bound.
- **[Budgeted Selection](./budgeted-selection/SYSTEM.md)** — prune unsupported candidates and fit the surviving subgraph inside the token budget.
- **[Result Quality](./result-quality/SYSTEM.md)** — score the assembled result and derive affected-test recommendations.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `query_text`, `query_plan`
- **Outputs:** `task_subgraph`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Node recall on the labelled structural suite SHALL stay at or above 0.75 as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** `retrieve_context` SHALL remain the public orchestration facade over these phases, as checked by `tests/test_retrieval_phase_characterization.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN a phase abstains or reports incomplete evidence THE SYSTEM SHALL preserve the current status, control reason, and zero/non-zero packet behavior, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a phase extraction changes retrieval output THEN THE SYSTEM SHALL reject the change even when structural complexity decreases, as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Measured

## 5. Architectural Decisions (ADRs)

- **ADR-SRT-001:** Personalized PageRank reorders the tail; it is not the primary exact-lookup path.
- **ADR-SRT-002:** Facets refine after whole-query retrieval; they do not replace it.
- **ADR-SRT-003:** Split by independently failing evidence phases, not helper size.
- **ADR-SRT-004:** Carry explicit immutable phase records rather than a shared mutable context dictionary.
- **ADR-SRT-005:** No ranking or threshold changes are permitted as part of a decomposition change; empirical algorithm changes belong to OW-Q03 and OW-Q04.
- **ADR-SRT-006:** The retrieval phase contracts live here, under the domain they implement, rather than under Maintainability where the refactoring that produced them was tracked. Organizing contracts by the project that created them forced a reader to consult two subtrees to understand one pipeline. Maintainability retains the cross-cutting code-health gates and no longer owns a domain pipeline.
- **ADR-SRT-007 (formal identification, 2026-08-19):** The composite this subtree solves has a name in the literature. Taken together — cover every query facet, using nodes that induce a *connected* subgraph, under a token budget, maximizing retrieved evidence — Facet Obligation + Neighborhood Expansion + Budgeted Selection is an instance of **Connected Budgeted Maximum Coverage (CBC)**, equivalently a node-weighted **Group Steiner Tree** with prizes: facets are the groups, graph nodes are the sets covering them, tokens are the costs, and the dependence-cone requirement is the connectivity constraint. The keyword-search-over-graphs form is the **Quadratic Group Steiner Tree Problem**. Both are NP-hard and both admit polylogarithmic approximation with published guarantees.

  This project currently solves that composite with three independent greedy heuristics that never write the objective down: reserve-one-anchor-per-facet, bounded k-hop, then a knapsack fit. Each stage optimizes its own local criterion, which is exactly why the two documented failures were *inter-stage* — reservation seating anchors the pruner then removed, and expansion starving reservation of budget. A single declared objective would have made both a constraint violation rather than an emergent surprise.

  No algorithm change is authorized by this ADR. It records that the heuristics currently carry **no approximation guarantee and no written objective function**, names the formalism that would supply both, and opens `RF-04`. Adopting an approximation algorithm is gated on the retrieval eval harness like any other ranking-affecting change (ADR-SRT-005).
