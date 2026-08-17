# Structural Retrieval (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Discover anchors, expand a structurally constrained neighborhood, and select a budgeted subgraph; does not own semantic embedding, packet encoding, or query-class assignment.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One retrieval Module with explicit phase seams already extracted under Maintainability.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `query_text`, `query_plan`
- **Outputs:** `task_subgraph`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Exact identifier hits SHALL bypass heavy ranking via a revision-aware literal index when unambiguous, as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a multi-anchor class admits a lexically similar candidate that touches no structural edge and is unprotected THEN THE SYSTEM SHALL drop that candidate, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a ranking term is proposed THEN it SHALL be measured inside production `search_nodes` rather than a bare field-ranked baseline, as checked by `tests/test_retrieval_field_log.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Node recall on the labelled structural suite SHALL stay at or above 0.75 as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-SRT-001:** Personalized PageRank reorders the tail; it is not the primary exact-lookup path.
- **ADR-SRT-002:** Facets refine after whole-query retrieval; they do not replace it.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/__init__.py`, `src/graphgraph/retrieval/activation.py`, `src/graphgraph/retrieval/anchors.py`, `src/graphgraph/retrieval/budgeting.py`, `src/graphgraph/retrieval/grounding.py`, `src/graphgraph/retrieval/context.py`, `src/graphgraph/retrieval/document_status.py`, `src/graphgraph/retrieval/expansion.py`, `src/graphgraph/retrieval/facets.py`, `src/graphgraph/retrieval/findnodes.py`, `src/graphgraph/retrieval/git_utils.py`, `src/graphgraph/retrieval/models.py`, `src/graphgraph/retrieval/obligations.py`, `src/graphgraph/retrieval/phase_support.py`, `src/graphgraph/retrieval/predicates.py`, `src/graphgraph/retrieval/pruning.py`, `src/graphgraph/retrieval/quality.py`, `src/graphgraph/retrieval/relations.py`, `src/graphgraph/retrieval/relevance.py`, `src/graphgraph/retrieval/reservations.py`, `src/graphgraph/retrieval/scoping.py`, `src/graphgraph/retrieval/search.py`, `src/graphgraph/retrieval/selection.py`, `src/graphgraph/retrieval/subsystems.py`, `src/graphgraph/retrieval/test_recommendations.py`, `src/graphgraph/retrieval/text.py`
- **Test Surface Seam:** `tests/test_abstention_red_controls.py`, `tests/test_adversarial_ambiguity.py`, `tests/test_relations.py`, `tests/test_retrieval.py`, `tests/test_retrieval_field_log.py`, `tests/test_retrieval_phase_characterization.py`, `tests/test_retrieval_predicates.py`, `tests/test_retrieval_section_relevance.py`, `tests/test_retrieval_subsystems.py`, `tests/test_tree_knapsack.py`

## 7. Measurement Seams

- **Primary Metric:** `node_recall` (target `>=0.75`, `direction: higher`); conceptual full recall `>=0.80` is the OW-AC-03 gate
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** anchor route, facet coverage, answerability confidence, omitted-neighbor counts.
- **Branching Policy:** isolated candidate; no exact-task regression; conceptual recall is the promotion gate, not a silent side metric.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — budgeted, structurally constrained subgraph retrieval is the system's core contribution. A vector database returns a nearest-neighbour set, not a dependence cone.
- **Selected:** in-repo retrieval stack on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Vector database plus pure embedding RAG | Loses path and blast-radius constraints. |
  | BM25 / lexical search alone | The strong baseline already; cannot answer dependence queries. |
  | Graph-database traversal (Cypher) | Server dependency inside the cold-start budget. |

- **Fit gap:** held-out conceptual recall still needs corpora that are not on disk (OW-AC-03). Local dirty misses abstain; scoped `doc_summary` reads keep their document hits.
- **Seam:** `src/graphgraph/retrieval/context.py::retrieve_context`
- **Exit cost:** HIGH — ranking, expansion, and selection are the hot path.
- **Cost model:** in-process CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** low-confidence dirty misses abstain; a scoped document read that found its paragraph is not treated as a dirty miss.
- **Open questions:** OW-AC-03, OW-AC-04, OW-Q04, OW-P0-03, OW-P0-04
