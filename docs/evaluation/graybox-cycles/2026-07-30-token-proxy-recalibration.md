# The token proxy was uncalibrated, and it was not a constant offset

2026-07-30 · affects every token figure recorded before this date

`graphgraph.packets.estimate_tokens` is the unit that every budget, packet
format choice, and token-saving claim in this project is denominated in. Until
today it was a bare `\w+|[^\s\w]` word count.

That charges **one token** for
`src_graphgraph_retrieval_context_py__retrieve_context`, where a real byte-pair
tokenizer charges **eleven**.

## What was wrong

Measured against `tiktoken` (`o200k_base` and `cl100k_base`) over 108 rendered
packets spanning nine formats and six selection sizes:

| | mean \|error\| | max \|error\| | cross-format spread |
| --- | ---: | ---: | ---: |
| old word count | 26.50% | 62.50% | **47.20%** |
| calibrated | **2.78%** | **11.93%** | **7.04%** |

The cross-format spread is the damaging number. A uniform bias would be
harmless for comparisons — every format wrong by the same factor still ranks
correctly. A 47% *spread* does not:

- **The cheapest-format ranking inverts.** By the old proxy `semantic_arrow`
  (1,543) looked far cheaper than `sql` (2,866). By real tokens `sql` (3,163) is
  cheaper than `semantic_arrow` (3,397). Identifier-heavy formats were
  under-counted by up to 2.2x because bare node IDs cost one token each.
- **It could not see the `gg` versus `gg_lex` tradeoff at all.** Both scored
  3,146. In real tokens they differ by 5.6%. That is precisely the tradeoff the
  project has been eval-gating.

## The calibration

A two-parameter model: a step cost per identifier piece, plus a much cheaper
cost per punctuation mark. Punctuation costs about an eighth of a word piece
because byte-pair tokenizers merge runs like `@ : / .` into their neighbours —
a measured property, not a tuned knob.

Model selection was done on a **held-out tokenizer** (fit on `o200k`, scored on
the unseen `cl100k`), and preferred this form over 1-, 2-, 3-, and 13-parameter
alternatives on mean error, worst-case error, and cross-format spread. The
13-parameter unconstrained per-length fit was rejected outright despite
competitive mean error, because it assigned **negative token costs**.

Both constants are least-squares derived.
`benchmarks/context_graph/calibrate_token_proxy.py` re-derives them by importing
the shipped functions — so the fit cannot drift from the estimator — and prints
`DRIFT:` with replacement values when a renderer change invalidates them.

`token_units()` was added alongside: unrounded and exactly additive over
newline-joined fragments. Any code accumulating a packet line by line must sum
that and round once. Summing `estimate_tokens` per line drifts from the same
packet rendered whole, which silently broke incremental budget accounting the
moment rounding was introduced.

## What this invalidates, and what it does not

**Still valid:** anything measured directly with a real tokenizer. The gray-box
evaluation's 15.6x / 93.6% compression figure (1,244 versus 19,371 tiktoken)
was measured that way and stands.

**Now unreliable:** any figure denominated in `estimate_tokens` and recorded
before this date. That includes packet-format comparisons, budget thresholds,
and percentage token-saving claims in
[engineering](../../guides/engineering-practices.md) and
[the 2.0 paper draft](../../research/manuscript-graphgraph-2.md). Large-magnitude claims
(compression against verbose JSON) survive a 26% error comfortably; specific
percentages and any *cross-format* comparison do not, and should be re-measured
before being repeated.

**Needs restating:** the earlier "calibrated within 1.5%" result in
[metric/component logic gaps](../metric-validity-gaps.md) compared the
*planner's* proxy against the *rendered packet's* `estimate_tokens`. Both sides
were the same word count, so it measured internal self-consistency, never
agreement with a tokenizer. It was not wrong on its own terms; it does not mean
what a reader would take it to mean.

## Known limitation

The calibrated proxy is **blind to whitespace**. Both splitters discard spaces,
so `--json --pretty` measures +26.7% in real tokens and +0.0% here. This is
acceptable for its job — packets are uniformly single-space separated and this
number sizes packet budgets — but it means the proxy cannot judge a layout or
pretty-printing decision.

Adding a whitespace term was tried twice, as a character-run count and as an
indented-line count. Both fits assigned it a **negative coefficient** and
worsened worst-case error, the same failure mode as the rejected 13-parameter
model. It was therefore rejected and documented rather than shipped.
