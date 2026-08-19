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
- **[Conditional]** IF the query does not already name a second document THEN THE SYSTEM SHALL issue one follow-up retrieval seeded by the names hop one introduces, as checked by `benchmarks/external/hotpotqa.py`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF the query already names a document beyond the top-ranked one THEN THE SYSTEM SHALL NOT force a second-hop anchor, because ranking already reaches both and a forced anchor evicts a correct one.
  - `EvidenceStage:` Measured

## 5. Architectural Decisions (ADRs)

- **ADR-AD-001:** Personalized PageRank reorders the tail; it is not the primary exact-lookup path.
- **ADR-AD-002:** Several searches per query are intentional, not accidental duplication. The calls carry different query texts, limits, and exact flags; a per-call memoization cache measured a 0% hit rate on a real trace. Reducing them is a pipeline restructure, not a caching fix.
- **ADR-AD-003:** Working-tree modification state personalizes ranking, so any A/B of this phase must hold git state constant across both arms. Comparing a stashed arm against a dirty arm measures the stash, not the change.
- **ADR-AD-004 (2026-08-19):** A second hop is a second *query*, not a ranking correction. Ranking is complete before expansion runs, so a document reachable only by traversal can enter the packet but never rank (ADR-SRT-008). Four attempts to fix that inside the ranked pool — boolean connectivity promotion, selectivity-gated promotion, a connectivity term blended into the score, and a reserved slot for the most specifically bridged document — were each measured against a 0.57 exact-match baseline on HotpotQA and each scored worse (0.42, 0.54–0.56, 0.41, 0.49).

  Instrumenting the third says why the whole class fails: the ranked pool arrives with its top candidates **tied at 59.7 while the correct second-hop document scores about 15**. No bounded corroborating signal reaches across that gap, and an unbounded one destroys the queries that already work.

  What does work is issuing one follow-up retrieval seeded by the proper names hop one introduces — the answering paragraph normally cites the second entity outright, so finding it is an ordinary high-scoring lookup with no gap to cross. It is gated off when the query already names a second document, because in that case ranking finds both entities unaided and a forced anchor evicts a correct one; ungated the mechanism won 6 questions and lost 11, and every loss had that shape.

  Measured on 1,000 held-out HotpotQA questions: exact match **0.5400 → 0.5800**, bridge questions **0.4404 → 0.4961**, comparison questions 0.8772 → 0.8640, McNemar exact two-sided **p = 0.00002**. The comparison cost is real and is not tuned away, because fitting the gate further against this sample would be overfitting rather than repair.

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
