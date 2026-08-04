# Fixing the field did not rescue the cover — it raised the baseline

`EXP-GPA-RECOUPLED` · `EXP-GPA-HYBRID-RESERVE` · claims
`GPA-COUPLING-RANKING-001`, `GPA-FIELD-COUPLING-001` · 2026-07-30

[The coupling finding](2026-07-29-influence-field-coupling.md) showed the
incumbent directed field is empty on three of four projects, so Phase 1 could
not have isolated the cover formula. This re-runs both the C1 greedy cover and
the shipped `hybrid_reserve_v1` with the evaluator, tasks, seeds, budgets, and
equal-token flat baseline held at their Phase 1 values, exchanging only the
edge coupling.

Two independent results came out, and they point in opposite directions.

## Result 1 — the representation loses, under both couplings

| arm / coupling | worst-project median resolution gain | promotable |
| --- | ---: | :---: |
| C1-cover / directed | +0.0000 | no |
| C1-cover / symmetric | −0.0399 | no |
| hybrid-reserve / directed | +0.0000 | no |
| hybrid-reserve / symmetric | +0.0000 | no |

Promotion requires a worst-project gain of `+0.02`. The best observed is
`+0.0002`, two orders of magnitude short.

Symmetric coupling does make the far field real — aggregate mass moves from
`0.0000` to `0.43–0.61` and refinements from `0` to `5–7`, so the
multiresolution machinery is finally doing work. It still does not win.

The reason is arithmetic. An aggregate cell of `k` members resolves a contained
entity to `1/k`, while one exact line resolves it to `1`. A cover line and a
node line cost roughly the same tokens. So aggregation only pays when the field
cannot rank well enough to choose *which* entities to spend those tokens on.
Measured, the aggregate cells buy a mean resolution credit of `+0.028`
(directed) and `+0.012` (symmetric) — real, but far below the cost of the
exact entities they displace.

**Correcting an earlier reading of this data.** My first pass scored the
reserve on exact recall alone, which gives its aggregate cells no credit and
deviates from the preregistered primary metric (resolution recall). On that
wrong metric the reserve had 0 wins in 144 rows. On the correct metric it wins
40 / loses 13 under directed and wins 21 / loses 24 under symmetric — high
variance around a median of ~0, not a uniform loss. The promotion verdict is
unchanged; the characterisation is.

## Result 2 — symmetric coupling is a better *retrieval* field

This was not what the experiment was aimed at. The equal-token flat baseline is
ranked by the same field, so it moves too:

| coupling | flat baseline mean exact recall | median |
| --- | ---: | ---: |
| directed | 0.5035 | 0.2667 |
| symmetric | **0.5694** | **0.5000** |

Paired across 72 cases: **32 improved, 3 regressed**, mean `+0.066`. The
reserve's own exact recall rose in step, `0.4319 → 0.5206`.

So the reserve "wins less often" under symmetric coupling not because the field
got worse, but because the bar rose. I had hypothesised the opposite — that
symmetrization would restore support at the cost of precision through hub bias.
The data rejects that: it improves both arms.

## What this licenses

- **The multiresolution representation is not promotable.** It has now been
  measured on a substrate that supplies a real far field, and still loses at
  equal tokens. `EXP-GPA-HYBRID-RESERVE` is recorded `failing`.
- **Symmetric coupling is promising for retrieval, and is not yet promotable
  either.** It was measured on a pure field-ranked selection, *not* on
  production `search_nodes`, which combines PPR with lexical, semantic, and
  kind signals and switches to localized PPR above 512 nodes. The gain may not
  survive that combination. Measuring it there is the next experiment.

## Cost

On the live 9,328-node / 34,372-edge graph, symmetric coupling costs one
edge-list rebuild (63 ms, now memoised on graph revision — 9,569× on repeat)
plus roughly 6× PPR time (24 ms → 154 ms warm). Materially more expensive, but
not disqualifying for an interactive path.

## Caveats

- The four frozen Phase 1 graphs are a small sample, and `requests` behaves
  differently from the other three under every coupling.
- `make_tasks` expectations are the same gold labels Phase 1 used; any bias in
  them is inherited, not controlled.
- Resolution recall credits `1/k` uniformly. It does not model whether an agent
  can actually *act* on a cell of size `k`, which is the thing the
  representation is ultimately claiming to help with.
