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

## 3. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Whole-query retrieval remains the global prior; facets refine later ([query decomposition timing](https://arxiv.org/abs/2606.08577) as design reference).
  - `EvidenceStage: Inferred` — design reference, not a local measurement.
- **[Conditional]** IF confidence is below policy THEN THE SYSTEM SHALL abstain rather than emit a large low-value packet (OW-AC-04).
  - `EvidenceStage: Sampled` — red controls (unanswerable query ⇒ conf ≤0.2, ≤50 real tokens) are still an open gate.
- **[Ubiquitous]** Minimum-evidence success SHALL be reported separately from full raw-neighborhood completeness.
  - `EvidenceStage: Observed` — OW-P0-04.
- **[Ubiquitous]** Exact identifier hits MAY bypass heavy ranking via a revision-aware literal index when unambiguous.
  - `EvidenceStage: Measured` — [empirical-evaluation.md](../../evaluation/empirical-evaluation.md) § Native Exact-Lookup Staging.
- **[Ubiquitous]** A ranking term SHALL NOT be promoted on a bare field-ranked baseline alone; it SHALL be measured inside production `search_nodes`.
  - `EvidenceStage: Measured` — symmetric coupling gained `+0.066` on a field-ranked selection and then moved recall/MRR not at all in production, at 11.9x latency. See [coupling has no production leverage](../../evaluation/graybox-cycles/2026-07-30-coupling-has-no-production-leverage.md).

## 4. ADRs

- **ADR-IR-001:** Lexical matching carries the current labelled task set; the personalized-PageRank term reorders the tail (ranks 4–20) that recall@20 and first-hit MRR cannot see. Building a paraphrase/conceptual task set is a prerequisite for evaluating any field-stage candidate at all — not a follow-up.
- **ADR-IR-002:** Semantic embeddings are an **opt-in** backend. The default offline hash index is lexical in disguise, so a paraphrase claim requires the real model to be installed and its provenance recorded.
- **ADR-IR-003:** Structural constraints (paths, change-impact neighborhoods) are hard filters, not score terms — a wrong answer with a good score is still wrong.

## 5. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `retrieval/` (25 modules); orchestration entry `retrieval/context.py::retrieve_context` |
| **Test surface** | `tests/test_retrieval.py`, `test_retrieval_field_log.py`, `test_retrieval_predicates.py`, `test_retrieval_section_relevance.py`, `test_retrieval_subsystems.py` |
| **Scoping seam** | `retrieval/scoping.py` (test-node classification, path predicates) |

## 6. Measurement seams

| | |
|--|--|
| **Primary metric** | Node recall — threshold **≥0.75** (`direction: higher`) |
| **Secondary metrics** | Edge recall ≥0.65; irrelevant-context ratio ≤0.85 (`direction: lower`) |
| **Source of thresholds** | `benchmarks/context_graph/benchmark_manifest.json` (`thresholds`), tokenizer `cl100k_base` |
| **Conceptual-recall gate** | ≥80% full recall on conceptual tasks with no exact-task regression (OW-AC-03) |
| **Instrument warning** | Expectations are written as labels, not node IDs — score through the harness's own resolver, and pair arms positionally, not by query text. Both mistakes produced plausible, wrong tables once |

## 7. Technology resolution

- **Decision class:** **BUILD** (ranking, expansion, selection) / **ADOPT, optional** (`fastembed` for real semantic recall)
- **Selected:** in-repo retrieval stack; `fastembed>=0.3.0` under the `semantic` extra
- **Standard / protocol:** none; the semantic extra runs a local ONNX model (onnxruntime, not torch, so it stays comparatively light)
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Vector database + pure embedding RAG | Loses the structural constraints that make path and blast-radius queries answerable; a nearest-neighbour set is not a dependence cone |
  | BM25 / lexical search alone | This is effectively the strong baseline already — and on the current labelled tasks it is hard to beat, which is why ADR-IR-001 exists |
  | Graph-database traversal (Cypher) | Server dependency inside the cold-start budget; see [comparisons/neo4j.md](../../research/comparisons/neo4j.md) |
  | Bundling an embedding model by default | Model download plus runtime weight for a gain that is still CI-unverified; kept opt-in and provenance-guarded |

- **Fit gap:** `resolve_backend()` falls back to an offline hash index when the extra is absent. That fallback **does not** provide paraphrase recall — it is lexical behavior under a semantic name, and claims must say which backend produced them.
- **BUILD justification:** differentiator — budgeted, structurally-constrained subgraph retrieval is the system's core contribution.
- **Seam:** `platform/embeddings.py` (`resolve_backend`)
- **Exit cost:** **MEDIUM** for the embedding backend (one seam); **HIGH** for the ranking stack.
- **Operational owner:** us
- **Failure mode:** semantic extra absent ⇒ silent fallback to the hash index, which is why provenance is recorded rather than assumed.
- **Open questions:** OW-AC-03/04, OW-Q03/Q04, OW-P0/P1 — [open-work.md](../../open-work.md); agenda narrative in [optimization-research-agenda.md](../../research/optimization-research-agenda.md)
