# Request Feasibility (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Normalize a retrieval request and decide whether corpus evidence permits retrieval at all; does not rank candidates, expand neighborhoods, or choose a packet format.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One feasibility phase over existing evidence predicates.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `query_text`, `query_plan`
- **Outputs:** `prepared_request`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a facet term is absent from the corpus in every lexical form THEN THE SYSTEM SHALL treat the request as provably unanswerable, as checked by `tests/test_abstention_red_controls.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a facet's terms are present but scattered across several nodes THEN THE SYSTEM SHALL NOT veto the request, because distributed evidence is what a paraphrase looks like rather than an absence.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF only generic definition-shaped words are missing THEN THE SYSTEM SHALL NOT treat that as proof of absence, as checked by `tests/test_conceptual_heldout.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN a scoped document read locates its paragraph THE SYSTEM SHALL NOT classify the request as a dirty miss.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-RF-001:** Absence is proven only by a dictionary lookup showing a term occurs nowhere in the corpus in any form. Four earlier attempts tried to find a score strong enough to *override* the veto; all four were falsified because no single embedding-derived signal separates a real match from an adversarial near-miss. The fix narrowed what the veto is entitled to treat as proof instead of adding another threshold.
- **ADR-RF-002:** This phase scores and thresholds nothing. It answers a membership question, which is why it is robust where calibrated alternatives were not.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/request_feasibility.py`, `src/graphgraph/retrieval/predicates.py`, `src/graphgraph/retrieval/document_status.py`, `src/graphgraph/retrieval/scoping.py`, `src/graphgraph/retrieval/text.py`
- **Test Surface Seam:** `tests/test_abstention_red_controls.py`, `tests/test_adversarial_ambiguity.py`, `tests/test_conceptual_heldout.py`, `tests/test_retrieval_predicates.py`, `tests/corpus/conceptual-disjoint/bilinear.py`, `tests/corpus/conceptual-disjoint/evidence.py`, `tests/corpus/conceptual-disjoint/lens.py`, `tests/corpus/conceptual-disjoint/pipeline.py`

## 7. Measurement Seams

- **Primary Metric:** `node_recall` (target `>=0.75`, `direction: higher`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** feasibility verdict, provably-absent facet terms, control reason.
- **Branching Policy:** isolated candidate; a change that increases abstention on answerable queries reverts even if it improves red-control behavior.
- **Known granularity gap:** this leaf shares the component-level `node_recall` gate. An abstention-specific precision/recall metric is tracked as `OW-AC-04`, not fabricated here.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — deciding that evidence cannot answer a request, rather than returning a confident wrong neighborhood, is a core product claim and has no off-the-shelf equivalent.
- **Selected:** in-repo feasibility predicates on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Embedding-similarity threshold | Falsified four times on this corpus; the real red control scored higher than genuine queries. |
  | Always attempt retrieval, filter later | Produced 14–48 node packets of confident wrong context on conceptual misses. |

- **Fit gap:** a red-control query built entirely from short or definition-shaped words cannot be proven absent, so it is not vetoed. Recorded as `R-003`.
- **Seam:** `src/graphgraph/retrieval/request_feasibility.py`
- **Exit cost:** MEDIUM — the veto sits ahead of every retrieval path.
- **Cost model:** in-process CPU; dictionary lookups against a cached token index.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unavailable token index declines to veto rather than abstaining, preferring a ranked answer over a false abstention.
- **Open questions:** OW-AC-04, R-003
