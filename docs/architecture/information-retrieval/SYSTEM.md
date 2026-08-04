# Information Retrieval (L1)

> **Package:** `retrieval/`  
> **Child:** [confidence-and-routing.md](./confidence-and-routing.md)  
> **Related:** [../query-planning/SYSTEM.md](../query-planning/SYSTEM.md)

## 1. Intent

Given a query and graph IR, produce a **task-local subgraph** under token/latency budgets: **retrieval anchors**, expansion, faceted evidence, connected selection, pruning, quality receipts.

Academic framing: **ad hoc IR over a code/document graph** with hard structural constraints (paths, **change-impact neighborhoods**), not free-text RAG alone.

## 2. Pipeline stages

| Stage | Academic term | Modules (map) |
|-------|---------------|---------------|
| Anchor discovery | Seed / retrieval anchors | `anchors.py`, `search.py` |
| Expansion | Graph neighborhood / dependence cone | `expansion.py`, graph traversal |
| Facets | Multi-aspect evidence | `facets.py`, `reservations.py` |
| Selection | Budgeted subgraph / knapsack | `selection.py`, `tree_knapsack.py` |
| Pruning / scoping | Constraint filters | `pruning.py`, `scoping.py` |
| Ranking | Scoring / LTR candidates | `search.py`, `relevance.py` |
| Quality | Calibration signals | `quality.py` |
| Orchestration | Context compilation | `context.py` (`retrieve_context`) |
| Affected tests | Test impact attribution | `test_recommendations.py` |
| Relations micro-IR | Exact relation queries | `relations.py` |

## 3. Invariants

- **[Ubiquitous]** Whole-query retrieval remains the global prior; facets refine later ([query decomposition timing](https://arxiv.org/abs/2606.08577) as design reference).
- **[Conditional]** IF confidence is below policy THEN THE SYSTEM SHALL abstain rather than emit a large low-value packet (OW-AC-04).
- **[Ubiquitous]** Minimum-evidence success SHALL be reported separately from full raw-neighborhood completeness.
- **[Ubiquitous]** Exact identifier hits MAY bypass heavy ranking via revision-aware literal index when unambiguous.

## 4. Open work

OW-AC-03/04, OW-Q03/Q04, OW-P0/P1 — [open-work.md](../../open-work.md).  
Agenda narrative: [../../research/optimization-research-agenda.md](../../research/optimization-research-agenda.md).
