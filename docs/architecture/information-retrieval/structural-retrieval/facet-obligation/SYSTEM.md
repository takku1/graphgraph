# Facet Obligation (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Derive per-facet evidence obligations from the query and reserve anchors that discharge them; does not decide feasibility, rank the root candidate set, or apply the final token budget.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One obligation-and-reservation phase over ranked candidates.

## 3. Interface Contracts

- **Inputs:** `anchor_outcome`
- **Outputs:** `facet_reservations`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN reservation finds an anchor for an unsatisfied facet THE SYSTEM SHALL seat it by displacing the weakest ranked anchor rather than truncating the reservation away, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a query's facets are already satisfied THEN THE SYSTEM SHALL leave the ranked budget untouched, so facet handling cannot demote an already-correct answer.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A reservation admitted on evidence distributed across several nodes SHALL be tagged so the protecting stage recognizes it and does not prune it as unsupported padding.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The reservation bound SHALL act only as a ceiling, not as a fitted constant; reservation stops once each facet's obligation is covered.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-FO-001:** Facets refine after whole-query retrieval; they do not replace it.
- **ADR-FO-002:** Displacement, not holdback. An unconditional holdback that shrank the ranked limit whenever facets existed bought one conceptual task but demoted a correct answer from rank 1 to rank 7 on another. Displacement only fires when reservation actually found something, so satisfied queries keep their full budget.
- **ADR-FO-003:** The reserving stage and the protecting stage must agree on what counts as facet evidence. They previously used different predicates, so one stage deliberately seated an anchor the next stage immediately dropped.
- **ADR-FO-004:** The reservation bound was swept over {2, 4, 12} and produced byte-identical results on all 22 held-out tasks. It ships at 4 as a ceiling so a twelve-facet query cannot evict the entire ranked root set, not as a tuned value.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/facets.py`, `src/graphgraph/retrieval/obligations.py`, `src/graphgraph/retrieval/reservations.py`
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_conceptual_heldout.py`, `tests/test_adversarial_ambiguity.py`

## 7. Measurement Seams

- **Primary Metric:** `node_recall` (target `>=0.75`, `direction: higher`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** facet coverage, reservation count, displaced ranked anchors, distributed-evidence tags.
- **Branching Policy:** isolated candidate; conceptual recall is the promotion gate, not a silent side metric.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — discharging per-facet evidence obligations against a dependence graph is specific to this system's answerability contract and has no library equivalent.
- **Selected:** in-repo facet and reservation modules on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Learned re-ranker over embedding scores | Four hand-tuned single-signal formulations were falsified on this fixture; a learned ranker needs labelled data this project does not yet have. |
  | Query expansion without reservation | Restores recall by enlarging the packet, which contradicts the token-cost axis. |
  | Greedy submodular maximization under a knapsack constraint | The principled form of what reservation approximates: facet coverage is a monotone submodular set function, so cost-benefit greedy has a standard `1 - 1/e` guarantee. Not adopted yet only because it is ranking-affecting and gated on the eval harness — tracked as `RF-04`, not declined. |
  | Proportional diversification (PM-2 / xQuAD) | The IR-native statement of "one anchor per facet, proportional to facet demand". Rejected as a drop-in because both assume a flat candidate list and neither carries the connectivity constraint this packet needs. |

- **Fit gap:** reservations are appended in arrival order, so a recovered answer can land at the bottom of the packet. Ordering by facet evidence strength is untried and tracked as `R-004`.
- **Seam:** `src/graphgraph/retrieval/reservations.py`
- **Exit cost:** HIGH — reservation interacts with both ranking and pruning.
- **Cost model:** in-process CPU.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** reserving nothing returns the ranked set unchanged.
- **Open questions:** OW-AC-03, OW-Q03, R-004
