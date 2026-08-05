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

## Verdict

Both obvious fixes are unsafe: they trade a false-negative bug (vetoing a
real answer) for a false-positive one (answering over nothing), and this
project's own values rank the second failure worse ("the dangerous direction
is a confident answer over nothing" — `tests/test_retrieval.py`). Neither
patch was shipped; the repository is unchanged by this cycle except for this
record. `fastembed` was installed in the local dev environment only (not a
project dependency change).

## What a real fix needs

Not a threshold on any single score. Candidates worth trying, in order of
how directly they attack the actual failure (a near-miss on individual
terms beating a genuine paraphrase on the whole facet):

1. **Compound-facet-aware re-ranking of semantic candidates**, not a bare
   top-K cosine cutoff: require the union of top semantic hits to cover
   the query's required facet terms the way `facet_coverage` already does
   for lexical evidence, instead of trusting one node's raw score.
2. **Margin/contrastive scoring** — score relative to the query's own
   corpus-wide score distribution (e.g. z-score or percentile) rather than
   an absolute cosine value, since "0.76" means different things on
   different corpora and query lengths.
3. A dedicated **adversarial-vs-conceptual calibration set** (this cycle's
   red-control + `eval/retrieval-v1/locus.json` conceptual tasks, scored
   together) before promoting any threshold — exactly the kind of paired
   task set OW-AC-03/04 already call for and do not yet have.

## Coverage — what this cycle did not test

- Whether a larger/different embedding model (not `bge-small`) separates
  these cases better — only one model was tried.
- Any margin/contrastive scoring approach — only absolute-value thresholds
  were tested, and both failed, but a relative approach was not built.
- The other three fixture repos in `eval/retrieval-v1/` (express, flask,
  ripgrep) — only the locus conceptual split and the in-repo red control
  were exercised.
