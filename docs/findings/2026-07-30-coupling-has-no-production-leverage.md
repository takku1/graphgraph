# The field has no measurable leverage on production ranking

`EXP-GPA-COUPLING-PROD` · claim `GPA-COUPLING-RANKING-001` · 2026-07-30

[The recoupled verdicts](2026-07-30-recoupled-cover-verdicts.md) measured a
`+0.066` exact-recall gain for symmetric coupling on a *pure field-ranked*
selection, and explicitly declined to promote it until it was measured inside
production `search_nodes`. It has now been measured there. It does not survive.

## Result

21 real labelled eval tasks, scored through production `search_nodes` with the
eval harness's own resolver and MRR/NDCG functions. Only the PageRank term's
edge orientation changes; lexical scoring and the degree boost still read the
project's real edges.

| coupling | tasks | mean recall | mean MRR | mean NDCG@10 | paired NDCG delta | NDCG better/worse | median ms |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: |
| directed | 21 | 0.6905 | 0.6905 | 0.6704 | +0.0000 | 0/0 | 182 |
| symmetric | 21 | 0.6905 | 0.6905 | 0.6726 | +0.0021 | 1/0 | 2161 |
| reverse | 21 | 0.6905 | 0.6905 | 0.6726 | +0.0021 | 1/0 | 198 |

Recall and MRR are unchanged to four decimal places. NDCG@10 moves `+0.0021`,
carried by a single task of 21. Symmetric coupling costs **11.9x** latency
(182 ms → 2161 ms) for that.

## The stronger diagnostic

Disabling personalization entirely — falling back to global PageRank — scores
**identically**: recall `0.6905`, MRR `0.6905`, NDCG@10 `0.6726`. On this task
set the personalized-PageRank term does not change which expected nodes are
retrieved, nor the rank of the first hit.

This is not an unwired knob. Verified: **all 21 ranked lists change** under
symmetric coupling, and all 21 change again when PPR is disabled. The field
demonstrably reorders results — it reorders the *tail*. The expected answers
are found by lexical matching at ranks 1–3, and PPR shuffles positions 4–20,
which recall@20 and first-hit MRR cannot see.

## Consequence for the research line

The global-attention line has spent its effort on the influence field. On the
labelled tasks this project actually gates against, the field has no measurable
effect on retrieval outcomes. Improving it is optimizing a term with
approximately zero marginal influence.

`F1-SYMMETRIC-COUPLING` is therefore **measured but not promotable**: it clears
the substrate gate ([the coupling finding](2026-07-29-influence-field-coupling.md)),
improves a bare field-ranked baseline, and buys nothing where it would ship.

## Two instrument bugs found on the way here

Both produced plausible-looking tables that were wrong, and both are why this
result should be trusted only as far as its red tests go.

1. **All arms scored 0.0000.** Eval expectations are written as labels
   (`handle_select_symbols`), not node IDs (`src_..._py__handle_select_symbols`).
   Literal matching scores every arm at zero. Fixed by using the harness's own
   `_resolve_node_expectation_ids`.
2. **The directed arm differed from itself** (`+0.0238`, 1 better / 0 worse).
   Three query strings repeat across the task files, so a baseline dict keyed
   on query text silently paired rows against the wrong task. Fixed by pairing
   positionally; the directed arm now reads `+0.0000`, `0/0`, which is the
   red test this table has to pass before any other row means anything.

## Caveats

- 21 tasks on one repository. This is a small, lexically easy task set: most
  queries contain the target symbol's name, which is exactly the regime where
  lexical matching dominates and a diffusion prior cannot help.
- The result therefore does **not** show that PPR is useless in general. It
  shows the current labelled tasks cannot detect its contribution. A task set
  built from paraphrase and conceptual queries — where the query shares no
  tokens with the answer — is the honest place to re-measure.
- Building that task set is worth more than any further field tuning: without
  it, no field-stage candidate can be evaluated at all.
