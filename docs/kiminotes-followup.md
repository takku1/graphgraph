# Follow-Up to `kiminotes.md`: What the Framing Misses, and What to Spec

Companion to [`kiminotes.md`](kiminotes.md). That document derives a "pure concept"
of a context graph as a spectral dynamical system over the attention operator.
It is internally coherent and the §5 properties are worth keeping. This document
records what the framing leaves out, and turns the salvageable parts into specs
that `graphgraph` can actually build and falsify.

---

## 0. The Load-Bearing Problem: The Operator Is Not Ours

`kiminotes.md` §3 defines vertices as eigenmodes $\phi_i$ of the attention matrix
$A$ at some layer, and edges as resonance $\mathcal{R}(\phi_i,\phi_j)$ mediated by
a learned transition operator $W$.

Every object in that definition lives **inside a forward pass of a model we do not
host**. $A$ is per-layer, per-head, per-sequence, and recomputed on every call. We
have no access to it through a provider API, and even with access it would not be
stable across model versions. The same is true of $W$.

This is not a caveat to note and move past — it invalidates §3, §6, and §7 as
*specifications*. They describe a system nobody in our position can build.

What survives is the **objective**, not the mechanism. §4 asks for a structure that
is informationally sufficient and structurally minimal. §5 gives three properties.
Those are agnostic to who owns the operator.

So the correct restatement of graphgraph's problem is:

> We do not shape the attention geometry. We choose a **token prefix**. Our lever is
> the map from graph to prefix, and our objective is to pick the prefix that induces
> a favorable geometry in a model we cannot inspect.

Everything below follows from taking that seriously. The doc's framework becomes a
description of *what we are indirectly steering*, not *what we are building*.

**Spec 0 — Framing discipline.** Any future doc that reasons about attention
internals must state up front whether it is (a) describing model behavior we infer
from black-box evals, or (b) proposing something we implement. `kiminotes.md`
silently mixes the two. Docs in category (a) belong next to
`llm_internals_position_paper.md` and must not be cited as design authority.

---

## 1. There Is No Agent In The Model

`kiminotes.md` models a dyad: context and next-token prediction. Real usage is a
triad — **agent, packet, repository** — in a closed loop:

```
query → packet → agent reasoning → edit → repository changes → next query
```

The context graph is not a passive map. It is in feedback with an actor that
*modifies the territory the map describes*, and it modifies it partly **because of
what the map showed**. A packet that omits a caller causes an edit that breaks that
caller, which changes the graph, which changes the next packet.

§5's Causal Closure is stated over tokens ($G_t$ computable from $G_{t-1}$ plus
$x_t$). The closure we actually need is over **edits**: $G$ after an edit must be
computable from $G$ before it plus the diff, without a full rescan. That is a
different and much more useful property, and it is one we can test.

**Spec 1 — Edit-closure conformance.**
- Define: for repo state $R$ and edit $\delta$, incremental update $U(G_R, \delta)$
  must equal full rescan $S(R \oplus \delta)$ on node set, edge set, and edge
  attributes — modulo documented, enumerated exceptions.
- Build: a property test that generates random edit sequences (add/delete/rename
  symbol, move file, change import, edit docstring) over a fixture repo, applies
  both paths, and diffs the graphs.
- Acceptance: exact match on nodes/edges for the enumerated edit taxonomy; any
  divergence must be either fixed or added to the documented exception list with a
  rationale. Drift into "we rescan when unsure" is a silent failure of this spec —
  measure and report rescan-fallback rate.
- Ties into `incremental-update-instruction-set.md`.

---

## 2. The Loss Is Not Symmetric, So Mutual Information Is The Wrong Objective

§4 proposes minimizing lost mutual information plus a complexity penalty. Mutual
information is **symmetric in its errors**. Our failure modes are not remotely
symmetric:

| Error | Consequence |
| --- | --- |
| Omit a caller of the edited symbol | Agent ships a break. Cost: a broken build, a bad PR, lost trust. |
| Include an irrelevant node | Agent spends ~15 tokens and ignores it. Cost: negligible. |

The asymmetry is plausibly two orders of magnitude, and it is **relation-dependent**:
a missing `calls` edge into the blast radius is catastrophic; a missing `similar_to`
edge is a mild relevance miss. An MI objective, or any symmetric F1, will happily
trade a critical omission for several avoided inclusions and score it as neutral.

This is not academic. It is the difference between a retrieval system tuned to look
good on benchmarks and one tuned to not break code.

**Spec 2 — Asymmetric packet loss.**
- Define a per-relation recall floor rather than a blended score:
  $$L = \sum_r w_r \cdot \text{FN}_r + c \cdot \text{tokens}, \qquad w_{\text{calls}} \gg w_{\text{similar\_to}}$$
- Set $w_r$ from an elicited cost table, not from fitting to a benchmark. Write the
  table down in this repo with the reasoning for each entry, so it can be argued
  with.
- Add a **hard constraint** the optimizer may not trade against: for
  `blast_radius` queries, direct-caller recall $\geq 0.99$. Budget optimization
  happens *subject to* that constraint, not blended into it.
- Acceptance: the eval harness reports per-relation recall separately and fails the
  build on floor violations, regardless of aggregate score. An aggregate-only
  report is the bug this spec exists to prevent.
- Note: this directly constrains the §2 budget formula in
  `mathematical_formulations.md`, whose $U(n)$ is currently a smooth unconstrained
  tradeoff with no notion of a critical omission.

---

## 3. The Tokenizer Is The Real Quantization Layer

`kiminotes.md` leaves token space in §1 and never comes back. But our entire output
is tokens, and our compression decisions live *exactly* at the tokenizer boundary,
where the doc's continuous framework has nothing to say.

The known case: `gg_lex` lexical ids were expected to be roughly free relative to
`gg` and measured **~10% more expensive**. That is a pure tokenizer-segmentation
effect. No amount of spectral reasoning predicts it; only measurement does. It is a
standing demonstration that the abstraction level in `kiminotes.md` cannot reach the
decisions we actually make.

The unexplored lever: **id assignment is a free variable we currently waste**. Node
ids are chosen for human legibility or insertion order, not for token cost. If ids
were assigned so that high-frequency nodes get single-token identifiers under the
target tokenizer, packet cost drops with zero information loss.

**Spec 3 — Tokenizer-aware id assignment.**
- Build a `tokencost` module: given a tokenizer and a candidate packet, report
  tokens per node, per edge, per id scheme.
- Assign ids by descending node frequency in the packet, drawing from a
  pre-computed single-token id alphabet for the target tokenizer.
- Measure across ≥3 tokenizers (Claude, GPT, Llama families) — an id scheme tuned
  to one and worse on others is a real regression, and we should know the spread
  before shipping.
- Acceptance: ≥8% median token reduction on the existing packet corpus at
  **identical** node/edge content and unchanged answer accuracy on the live-model
  eval. If accuracy moves at all, the win does not count.

---

## 4. A Graph Is Unordered; A Prompt Is A Sequence

`kiminotes.md` treats $G$ as an abstract object. But the packet is a **linearization**,
and there are $n!$ of them for the same graph. Position matters to a transformer —
recency effects, lost-in-the-middle degradation, the tendency to anchor on early
tokens. Two packets with identical information content and identical token counts
can produce different answers purely from ordering.

We currently have no ordering policy. Whatever order the renderer emits is an
accident of traversal, and it is invisible in every metric we track. This is a free
variable with real effect that we are neither controlling nor measuring.

**Spec 4 — Serialization order as a first-class parameter.**
- Make ordering explicit and pluggable. Candidates: PPR-descending; anchor-first
  then BFS; anchor-first with anchors *repeated* at the tail (exploiting recency);
  community-clustered so related nodes are adjacent.
- Evaluate on the live-model harness with everything else held fixed. This is a
  clean A/B — same nodes, same edges, same tokens, only order varies.
- Acceptance: publish the ranking with effect sizes and confidence intervals. If
  the spread across orderings is within noise, **record that as a finding and stop**
  — a negative result here is worth having and closes the question. If the spread
  is material, the best ordering becomes default and the others stay available.
- Prediction worth testing: anchor-first-and-last beats anchor-first-only on
  `blast_radius`, where the agent must hold the anchor in mind across a long list.

---

## 5. Prompt Caching Contradicts The Dynamics

This is the sharpest unexamined tension in `kiminotes.md`.

§3.3 wants a graph that continuously evolves — decay, resonance-driven activation,
new-token injection. Every element wants motion.

KV prefix caching wants the opposite. A cached prefix is worth having *only if it
does not change*. One token differs at position $k$ and everything from $k$ onward
is recomputed. The economic and latency gradient points hard toward **stasis**.

So an idealized graphgraph following §3.3 would be maximally cache-hostile: every
turn perturbs the packet, every turn pays full price. `--stable-skeleton` already
exists and is the right instinct, but it is currently an unmeasured flag rather than
a designed architecture.

The resolution is a **two-tier packet**, and it is worth stating as a real structural
commitment rather than a flag:

| Tier | Content | Cadence | Cache |
| --- | --- | --- | --- |
| **Skeleton** | Top-$k$ PPR architectural nodes; whole-repo shape | Changes only on significant structural drift | Cached prefix, reused across turns and sessions |
| **Delta** | Query-specific anchors, expansion, snippets | Every query | Never cached |

The skeleton absorbs the "global coherence" force from §2. The delta absorbs
"local coherence." The dynamics in §3.3 apply **only to the delta tier**, which is
the honest scope for them.

**Spec 5 — Two-tier caching architecture.**
- Formalize skeleton/delta as the packet structure, not an optional mode.
- Define a **skeleton invalidation policy**: a drift metric over the PPR-ranked
  architectural node set, with an explicit threshold that triggers regeneration.
  Without this, the skeleton either goes stale silently or churns and defeats itself.
- Instrument cache hit rate, and report cost per query with and without the split.
- Acceptance: measurable cost reduction on multi-turn sessions at unchanged answer
  accuracy, plus a documented invalidation threshold justified by observed drift
  rates on real repos — not a guessed constant.

---

## 6. Nothing In The Document Is Falsifiable

§5 presents three properties as things a context graph "must" satisfy. None is
stated in a way that could fail. What would it mean to observe that spectral
sparsity does *not* hold? The doc does not say, so the property does no work.

Each should be paired with an operational test that could come back negative:

| §5 Property | Operational restatement | Falsified if |
| --- | --- | --- |
| **Causal Closure** | Incremental update ≡ full rescan (Spec 1) | Property test finds divergence outside the exception list |
| **Spectral Sparsity** | PPR mass concentrates: top-$k$ nodes carry $\geq \alpha$ of retrieval-relevant mass on real repos | Measured mass curve is flat — meaning aggressive truncation *must* lose signal, and our budget model is unsound |
| **Resonance Locality** | Answer accuracy decays smoothly with graph distance from the true anchor | Accuracy is flat or non-monotone in hop distance — meaning graph distance is not a valid relevance proxy and expansion-by-hops is the wrong retrieval primitive |

The middle and bottom rows are the interesting ones. Both are load-bearing
assumptions in the current implementation, both are currently unmeasured, and a
negative result on either would require real redesign rather than tuning. That is
exactly what makes them worth running early.

**Spec 6 — Property falsification suite.**
- Implement all three as measurements over a corpus of ≥5 real repos of varying
  size and language.
- Report the actual curves, not pass/fail. The shape of the mass-concentration
  curve *is* the empirical basis for the $\lambda$ constants in
  `mathematical_formulations.md` §2, which are currently asserted per query class
  without derivation.
- Acceptance: a findings doc with the measured curves, and either a confirmation
  that the current constants are consistent with them or a revised set derived
  from them.

---

## 7. What To Keep From `kiminotes.md`

Discounting the framework should not discount the document. Genuinely useful:

- **§2's three-force tension** (local coherence / global coherence / computational
  bound) is the right decomposition, and it maps cleanly onto the skeleton/delta
  split in Spec 5. This is the doc's best contribution.
- **§4's "informationally sufficient but structurally minimal"** is the correct
  objective *shape*, even though MI is the wrong instantiation (Spec 2).
- **§5's property list** is the right set of properties, once made falsifiable
  (Spec 6).
- **§6's negative definitions** — not a knowledge graph, not a co-occurrence graph,
  not a parse tree — are sharp and worth quoting when scoping against
  `graphify` and `neo4j` comparisons.

What to discard: §3 in full, and the §7 conclusion, which restates §3's mechanism
as though it were achievable.

---

## Priority

Ordered by information gained per unit of work:

1. **Spec 6** (falsification suite) — everything else is tuning on unverified
   assumptions until this runs. Highest value, and it can invalidate other specs
   before we invest in them.
2. **Spec 2** (asymmetric loss) — changes what we optimize for. Cheap to state,
   and it reframes existing eval output.
3. **Spec 1** (edit closure) — correctness property with a clear test; protects the
   incremental path that everything in the agent loop depends on.
4. **Spec 5** (two-tier caching) — largest cost win, but depends on Spec 6's
   mass-concentration curve to size the skeleton honestly.
5. **Spec 4** (serialization order) — cheap A/B, possibly a clean negative result,
   which is itself worth banking.
6. **Spec 3** (tokenizer ids) — real but bounded win; do after the correctness work.
