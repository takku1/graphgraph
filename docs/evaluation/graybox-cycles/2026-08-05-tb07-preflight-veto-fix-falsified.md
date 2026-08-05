# T-B07 preflight-veto fix — two hypotheses tried, both falsified — 2026-08-05

**Ticket:** `.scratch/wayfinder-map/MAP.md` T-B07, flagged "the highest-value
retrieval fix on the board" — the `direct_lookup`/`reverse_lookup` facet
feasibility preflight in `retrieval/context.py` vetoes conceptual/paraphrased
queries before semantic evidence is ever consulted, even when the answer is
in the graph.

**Method:** built a real held-out fixture (`takku1/locus@76d80f9`, the exact
commit `eval/retrieval-v1/locus.json` is oracled against) and ran two
candidate fixes against it plus the project's own existing red-control test
(`tests/test_retrieval_section_relevance.py::test_random_plausible_and_near_miss_negatives_fail_closed_with_semantic_seeds`),
which requires "distributed retry coordinator" to keep abstaining even when
handed a plausible-looking seed (`RETRY` = `retry_request`).

## Hypothesis 1 — let caller-supplied `seed_ids` bypass the veto

`retrieve_context` already accepts `seed_ids`, populated upstream by
`QuerySourcePlanner` from a semantic index when lexical search is weak, but
consumed only *after* the preflight's early return — so a semantic seed
never gets a chance to rescue a query the strict lexical facet check vetoes.

**Falsified.** The near-miss red control passes `seed_ids=("RETRY",)`
specifically to prove a caller-asserted seed must not weaken abstention by
itself, and it still expects `result.starts == ()`. Any unconditional
"seed present -> skip veto" rule breaks this by construction — the red
control's whole point is that a plausible-looking seed can be wrong.

## Hypothesis 2 — corroborate with the pipeline's own ranked search

Idea: before vetoing, run `search.search_nodes(query)` (the same ranking
that answers real queries) and skip the veto if it returns a credible
code-like top hit.

**Falsified — score has no safe threshold.** Reproduced against both
fixtures with the actual scorer:

| Query | Candidate | `search_nodes` score |
|---|---|---:|
| LOC-TEST-C01 ("...sure it is that a conclusion holds?") | `EvidenceStage` (correct) | 8.37 (rank 14/270) |
| Red control: "distributed retry coordinator" | `RETRY` (must stay vetoed) | **11.46** |
| Red control: "Kubernetes gRPC service-mesh retry coordinator" | `RETRY` (must stay vetoed) | 9.96 |

The near-miss false positive outscores the genuine paraphrase match. No
single score cutoff admits one and excludes the other.

**Also tried: real embeddings, not lexical score.** Installed `fastembed`
(`BAAI/bge-small-en-v1.5`, previously absent from this environment — hash-only
fallback was active) and built a genuine embedding index over the locus
fixture (14,968 nodes, 976s cold build on this machine) plus a small index
over the red-control fixture:

| Query | Candidate | cosine |
|---|---|---:|
| LOC-TEST-C01 | `concept_evidence_stage` (correct, rank 6) | 0.717 |
| LOC-TEST-C05 ("...fewer scalar products than the obvious triple loop?") | `strassen_2x2` (wrong sibling; `strassen_recursive` absent from top 8) | 0.760 |
| Red control: "distributed retry coordinator" | `RETRY` (must stay vetoed) | **0.758** |
| Red control: "quasar papaya mutex" (nonsense, must stay vetoed) | noise floor | 0.53–0.57 |

Same failure shape with real embeddings: the adversarial near-miss (0.758)
lands *above* several genuine conceptual matches (0.66–0.72) and inside the
same range as others (0.76). `bge-small` was evidently not enough to
separate "this vocabulary is semantically close" from "this is actually
implemented" on short code-identifier text — the red control's queries were
built to be exactly this kind of adversarial near-miss.

## Update, 2026-08-05 (later same day) — margin scoring and facet-coverage re-ranking, both also falsified

Follow-up session tried the two candidates this record's original "what a
real fix needs" section proposed, using the same locus semantic index (now
persisted) plus a properly sized adversarial sample instead of the single
red-control query above. Four additional plausible-but-absent queries were
constructed in the same adversarial style as the project's own red control
(a real system concept, phrased naturally, that locus genuinely does not
implement: distributed retry coordination, Kubernetes service mesh, OAuth
token refresh, websocket heartbeat) and scored alongside all seven
`LOC-TEST-C0*` conceptual tasks and the corpus's own red control
(`LOC-TEST-R01`, "GraphQL subscription transport", `expected_answerable:
false`).

**Hypothesis 3 — margin over the query's own top-K score distribution.**
`top1_score - mean(top30_scores)` on a single spot check (R01 alone) looked
promising: genuine matches clustered at 0.035-0.039, R01 at 0.022. Adding
the four adversarial queries broke it immediately:

| Query | Genuine? | margin(top1 vs mean-of-30) |
|---|---|---:|
| C02 | yes | 0.0266 |
| R01 (red control) | no | 0.0218 |
| ADV-1 "distributed retry coordinator" | no | **0.0369** |
| C01 | yes | 0.0349 |
| C03 | yes | 0.0357 |
| ADV-3 "OAuth token refresh" | no | **0.0436** |
| C05 | yes | 0.0385 |

Sorted, the two classes overlap across the entire middle of the range
(genuine min 0.0266, absent max 0.0436) — no threshold separates them.
ADV-1 and ADV-3 score *higher* than three of the seven genuine matches.
`margin(top1 - top2)` was tried too and shows the same overlap.

**Hypothesis 4 — require semantic candidates to also carry lexical facet
coverage** (the "compound-facet-aware re-ranking" idea from the original
list below): for each query, extract `query_facets()`'s required terms, take
the *best* lexical-term-coverage fraction achieved by any of the top-15
semantic candidates (not just the top-1, since the correct symbol is often
buried — `EvidenceStage` was rank 6 for C01, `LocusEngine` rank 3 for C06).
This is strictly more informed than either prior hypothesis: it should be
the "combine both signals properly" answer.

It is not. `LOC-TEST-R01` — the project's own real, corpus-native red
control — scored `best_frac_top15 = 0.40`, the **highest of all twelve
samples**, genuine or adversarial. Several genuine queries (C02, C04, C05,
C06) scored `0.00` because `query_facets()` extracted zero required terms
for those phrasings in the first place, so there was nothing for any
candidate to cover. The signal is not merely noisy here; on this fixture it
points backwards.

## Verdict (revised)

Three independent fix hypotheses, four scoring formulations, tried against
both a toy adversarial fixture and a proper adversarial sample on the real
held-out corpus: absolute lexical score, absolute cosine similarity, margin/
relative cosine scoring, and semantic-candidate lexical-coverage re-ranking.
All four failed with concrete counter-examples, not just "insufficient
evidence." This is stronger than the original verdict below, not merely a
repeat of it: T-B07 is not "under-explored," it is a genuinely hard
calibration problem on this fixture/model combination, and no patch was
shipped for it in either session. `fastembed` remains a local dev-environment
install only.

**What would still be worth trying, now that four single/paired-signal
formulations are eliminated:** a learned re-ranker or cross-encoder trained
on labelled pairs (not a hand-picked formula over embeddings already
computed independently per-candidate); or accepting a materially larger/
different embedding model and re-running this exact twelve-query protocol
before trying another hand-tuned formula, since it is not yet known whether
`bge-small` specifically is the ceiling or whether the *approach* (any
single/paired embedding-derived signal) is.

---

## Original verdict (superseded in scope, not overturned)

Both obvious fixes are unsafe: they trade a false-negative bug (vetoing a
real answer) for a false-positive one (answering over nothing), and this
project's own values rank the second failure worse ("the dangerous direction
is a confident answer over nothing" — `tests/test_retrieval.py`). Neither
patch was shipped; the repository is unchanged by this cycle except for this
record. `fastembed` was installed in the local dev environment only (not a
project dependency change).

## What a real fix needs (original list — items 1 and 2 now tried and falsified above)

1. ~~**Compound-facet-aware re-ranking of semantic candidates**~~ — tried
   2026-08-05 as Hypothesis 4 above; falsified (`LOC-TEST-R01` scored
   highest of all twelve samples).
2. ~~**Margin/contrastive scoring**~~ — tried 2026-08-05 as Hypothesis 3
   above; falsified (adversarial queries score inside the genuine range).
3. A dedicated **adversarial-vs-conceptual calibration set** — this update
   built exactly that (7 conceptual + 5 adversarial/red, scored together)
   and it is what falsified items 1 and 2. Worth preserving as a fixture
   for whoever tries a learned re-ranker next, rather than rebuilding it.

## Coverage — what this cycle did not test

- Whether a larger/different embedding model (not `bge-small`) separates
  these cases better — only one model was tried, across both sessions.
- A learned re-ranker/cross-encoder rather than a hand-derived formula over
  independently-computed embedding scores.
- The other three fixture repos in `eval/retrieval-v1/` (express, flask,
  ripgrep) — only the locus conceptual split and red control were exercised.
- Whether the four adversarial queries built this session are representative
  in difficulty of the kind of near-miss a real user would type, versus
  being unusually hard by construction.
