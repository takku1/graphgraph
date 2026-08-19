# Anchor Discovery (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Produce grounded retrieval starts and ranked candidates with receipts; does not decide feasibility, expand the neighborhood, or apply the token budget.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One execution-order phase over the anchor and search modules.

## 3. Interface Contracts

- **Inputs:** `prepared_request`
- **Outputs:** `anchor_outcome`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Exact identifier hits SHALL bypass heavy ranking via a revision-aware literal index when unambiguous, as checked by `components/information-retrieval/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a ranking term is proposed THEN it SHALL be measured inside production `search_nodes` rather than a bare field-ranked baseline, as checked by `tests/test_retrieval_field_log.py`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a query names an identifier whose split and joined spellings differ THEN THE SYSTEM SHALL reconstruct the joined form before the exact-seed check, so a prose-spelled variant does not fall back to full-graph power iteration, as checked by `tests/test_graph_core.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Personalized PageRank topology derived from active edges and damping SHALL be cached per graph mutation revision rather than rebuilt per call.
  - `EvidenceStage:` Measured

## 5. Architectural Decisions (ADRs)

- **ADR-AD-001:** Personalized PageRank reorders the tail; it is not the primary exact-lookup path.
- **ADR-AD-002:** Several searches per query are intentional, not accidental duplication. The calls carry different query texts, limits, and exact flags; a per-call memoization cache measured a 0% hit rate on a real trace. Reducing them is a pipeline restructure, not a caching fix.
- **ADR-AD-003:** Working-tree modification state personalizes ranking, so any A/B of this phase must hold git state constant across both arms. Comparing a stashed arm against a dirty arm measures the stash, not the change.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/anchor_search.py`, `src/graphgraph/retrieval/anchors.py`, `src/graphgraph/retrieval/search.py`, `src/graphgraph/retrieval/activation.py`, `src/graphgraph/retrieval/findnodes.py`, `src/graphgraph/retrieval/git_utils.py`, `src/graphgraph/retrieval/grounding.py`
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_retrieval_field_log.py`, `tests/test_retrieval_phase_characterization.py`

## 7. Measurement Seams

- **Primary Metric:** `retrieval_query_warm_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** anchor route, exact-vs-ranked path, search call count, PPR seed count.
- **Branching Policy:** isolated candidate; latency may not improve at the cost of node recall.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — anchor grounding against a dependence graph under a revision-aware index is the system's core retrieval contribution; a nearest-neighbour library returns neither receipts nor structural starts.
- **Selected:** in-repo anchor and search stack on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | BM25 / lexical search alone | The strong baseline already; cannot answer dependence queries. |
  | Vector database nearest-neighbour | Returns a similarity set, not grounded starts with provenance. |
  | Forward-Push + Monte Carlo PPR (FORA, VLDB 2017) | The state of the art this leaf's hand-rolled localization approximates. FORA pushes until residuals fall below a threshold then Monte-Carlo samples the tail, giving **sublinear cost with a controllable error bound** — where the current localized approximation has no stated error guarantee at all. Tracked as `RF-06`. |
  | TopPPR (SIGMOD 2018) | Top-*k* PPR with a precision guarantee, which is the shape this leaf actually needs — it wants the best *k* anchors, not the full vector. Same frontier. |
  | Incremental PPR index maintenance (SIGMOD 2023) | Directly relevant because this graph is incrementally spliced: maintains PPR under graph updates instead of invalidating a whole topology cache on every mutation revision. |

- **Fit gap:** candidate-pool size feeding PageRank is still unbounded for broad queries; shrinking it is ranking-affecting and gated on the eval harness rather than done opportunistically.
- **Seam:** `src/graphgraph/retrieval/anchor_search.py`
- **Exit cost:** HIGH — ranking is the retrieval hot path.
- **Cost model:** in-process CPU; PageRank dominates warm query time.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unavailable literal index degrades to ranked search rather than failing the query.
- **Open questions:** OW-Q04, OW-AC-08
