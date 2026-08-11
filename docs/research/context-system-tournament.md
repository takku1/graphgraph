# Context-System Research Tournament

## Test every proposal, select the simplest empirical winner, then implement it

**Status:** governing research protocol. This document defines how current and
incoming context-system research is converted into tests. It does not promote
any proposed mechanism to production.

The executable source of status is
[`eval/context-system-research.json`](../../eval/context-system-research.json),
validated by `src/graphgraph/research/registry.py` and
`tests/test_research_registry.py`. Prose and registry disagreement fails the
research gate; it is never resolved by silently choosing the more favorable
status.

The repository contains several overlapping research directions: graph
diffusion, adaptive budgets, multiresolution coverage, semantic retrieval,
packet compression, stable prefixes, temporal memory, native attention bias,
and iterative agent control. More research documents are expected. The correct
response is not to merge all ideas into one maximal architecture.

> Every new claim enters a common experimental registry. Competing mechanisms
> are implemented behind the same interface, tested at equal budgets, and
> promoted only when they beat the incumbent on preregistered gates.

“Best” means the best measured Pareto tradeoff for a declared operating regime,
not the most novel or complex design.

## 1. Non-negotiable rules

1. **Research is input, not authority.** A paper, design document, or persuasive
   argument creates a candidate and a hypothesis. It cannot change the default.
2. **Benchmark before integration.** Prototype candidates in a simulator or
   experimental pass before modifying the production planner.
3. **Use the same graph and budget.** Retrieval candidates must receive the same
   extracted graph, query, freshness state, token ceiling, and latency ceiling.
4. **Separate component wins from system wins.** A faster diffusion kernel is
   not automatically a better end-to-end context system.
5. **Prefer the simpler equivalent.** If confidence intervals overlap and no
   important worst-case metric improves, retain the lower-complexity incumbent.
6. **Protect catastrophic cases.** A mean improvement cannot hide losses on
   policies, bridge nodes, negative queries, or worst-decile task recall.
7. **Do not tune on answer evidence.** Gold nodes, patches, and expected paths
   are available only to the evaluator after packet construction.
8. **No unscored passes.** Missing ground truth, skipped model calls, invalid
   packets, or stale graphs are reported as unscored/pending, never success.
9. **Record losers.** Rejected candidates and their failure regimes remain in
   the registry so the same idea is not repeatedly rediscovered.
10. **Promotion is reversible.** A winner launches behind a feature flag and
    retains an automatic fallback until broader evidence accumulates.

## 2. Research intake: turn prose into a claim ledger

Every indexed research document is processed into atomic records. Incoming
documents from another agent follow the same path.

### 2.1 Claim record

Each falsifiable claim receives:

| Field | Meaning |
| --- | --- |
| `claim_id` | Stable identifier, independent of section numbering |
| `source` | Document and heading containing the claim |
| `status` | `idea`, `specified`, `prototype`, `measured`, `rejected`, `promoted` |
| `mechanism` | What causes the claimed effect |
| `operating_regime` | Query types, project sizes, graph conditions, and model boundary |
| `baseline` | Strongest relevant incumbent, not a deliberately weak comparison |
| `primary_metric` | One preregistered metric that decides the claim |
| `guardrails` | Metrics that must not regress |
| `minimum_effect` | Smallest improvement worth the added complexity |
| `experiment_ids` | Tests capable of supporting or falsifying it |
| `evidence` | Immutable result/receipt references |
| `decision` | Promote, retain for a niche, revise, or reject |

Statements that are architectural preferences rather than empirical claims are
marked `normative`. Descriptions of existing code are marked `implemented` and
verified against source/tests. Neither is mixed with performance hypotheses.

### 2.2 Candidate record

A claim may have several implementations. Each candidate records:

- algorithm and exact formula;
- objective, domain, constraints, and units for every formula;
- the exact small-instance oracle or proof obligation;
- invariants and metamorphic relations that do not need answer labels;
- optimizer and, where claimed, its approximation or regret bound;
- known counterexamples and objective-mismatch tests;
- deterministic configuration and random seed policy;
- preprocessing, memory, update, query, and token costs;
- dependencies and hardware assumptions;
- supported graph types and failure preconditions;
- approximation or stopping tolerances;
- fallback behavior; and
- implementation-complexity estimate.

This prevents results for “PPR,” “hierarchy,” or “semantic retrieval” from
becoming ambiguous labels for materially different systems.

### 2.3 Formula-first implementation contract

Research code expresses a candidate as data plus a pure scoring/transition
function behind the common stage interface. The evaluator, budget accounting,
oracle, receipts, and datasets remain fixed while formulas are exchanged. A
formula is not compiled into production branches until it has:

1. passed dimensional, boundary, and invariant checks;
2. been compared with the exact oracle wherever finite enumeration is viable;
3. survived adversarial and metamorphic counterexample search;
4. beaten strong static `if`/threshold rules at equal cost; and
5. cleared held-out and cross-model gates.

Static rules remain necessary fallbacks and baselines. They are not the
research substrate because interleaving a new theory with production control
flow makes its causal effect and mathematical limit impossible to isolate.

### 2.4 Experiment record

Every experiment specifies its dataset snapshot, graph hash, task split, model
version, prompt, budget, candidates, metrics, statistical test, stop condition,
and artifact paths before it runs. Results are append-only.

## 3. Initial source inventory

The first ledger extraction should cover at least these research families. New
indexed documents are automatically added to the intake queue.

| Source family | Claims to extract first |
| --- | --- |
| [Global project attention](global-project-attention.md) | complete multiresolution cover, exact-near/compressed-far field, value-of-refinement, dynamic residual updates |
| [Dynamic surface math](dynamic-surface-mathematics.md) | spreading activation, turn decay, density throttle, prefix stability |
| [Mathematical formulations](mathematical-formulations.md) | PPR, information-gain budget, relation quota, hub penalty |
| [Adaptive planning math](adaptive-planning-mathematics.md) | query-class budget and planning rules |
| [Tensor context architecture](tensor-context-representation.md) | CSR layout, spatial attention bias, temporal layer updates |
| [LLM-native context graph](llm-native-context-representation.md) | packet ladder, lexical/semantic hybrid retrieval, typed temporal graph semantics |
| [Advanced context engineering](context-engineering.md) | compiler passes, packet coarsening, inference, orchestration |
| [Semantic locality](semantic-locality-and-llm-efficiency.md) | structural locality and LLM efficiency claims |
| [Context maximization](context-graph-maximization.md) | serialization floors, full-corpus and graph baselines, hybrid fact injection |
| [Optimization roadmap](optimization-research-agenda.md) | ranking, fusion, facet exploration, and early-termination candidates |
| [Metric and component gaps](../evaluation/metric-validity-gaps.md) | downstream code, ordering, multi-turn, scale, and tokenization tests |
| [kiminotes](external-mechanism-notes.md) and [follow-up](external-mechanism-notes-followup.md) | external research mechanisms not already represented above |

The intake is complete only when every empirical or mathematical claim is
either linked to an experiment, explicitly marked out of scope, or identified
as a duplicate of another claim. A document-level “tested” label is not enough.

## 4. Factor the system before comparing it

Testing every full combination would be combinatorial. Divide candidates into
replaceable stages with stable input/output contracts.

| Stage | Common input | Common output | Initial candidate family |
| --- | --- | --- | --- |
| Anchor | query + graph index | seed distribution | lexical, BM25, embeddings, reciprocal-rank fusion |
| Propagate | seeds + typed graph | influence field | BFS, spreading activation, PPR, heat kernel, local solver |
| Represent | field + hierarchy | exact/aggregate cover | flat top-$k$, containment hierarchy, graph communities, landmarks |
| Select | candidates + budgets | packet plan | fixed cap, knapsack, submodular greedy, value-of-refinement |
| Render | packet plan | prompt/memory payload | `gg`, `gg_lex`, arrows, hybrid facts, stable global-to-local ordering |
| Update | graph delta + cached state | new valid state | full rebuild, exact splice, residual propagation, lazy aggregate repair |
| Iterate | model state + receipt | next refinement or halt | one-shot, fixed turns, analytic halt, learned controller |

First hold all but one stage fixed and screen mechanisms within the stage. Then
combine the surviving candidates. This identifies causal contributions and
avoids attributing an anchor improvement to a renderer.

Interactions still matter. After stage screening, run a fractional factorial
or constrained Bayesian search over the top two candidates per stage. The final
champion must win as an assembled system.

## 5. The implementation tournament

### Round 0 — specification and kill tests

Cost: minutes, no model calls.

A candidate is eliminated or returned for revision if it:

- cannot state its invariant and failure behavior;
- uses expected answers during retrieval;
- cannot emit deterministic receipts;
- violates graph freshness or provenance rules;
- has unbounded output under an ordinary hub case;
- cannot operate within the common stage interface; or
- duplicates an incumbent without a plausible measurable advantage.

### Round 1 — exact synthetic laboratory

Cost: seconds to minutes.

Run chains, hubs, bridges, diamonds, disconnected components, semantic-only
links, policy outliers, renamed symbols, deletions, and community splits. Use
small graphs with exact full-field computation.

Required gates:

- invariants and packet validation pass;
- no stale current evidence;
- monotone reduction of the preregistered objective with increasing budget;
- separate reporting for non-optimized metrics, with no implied monotonicity;
- project coverage/mass accounting is internally consistent;
- exact-oracle error is no worse than the simplest relevant baseline; and
- peak memory/output remains under the round ceiling.

### Round 2 — deterministic real-project evidence

Cost: minutes to hours, no paid model required.

Use repository-held-out evidence-containment, affected-test, path, blast-radius,
subsystem, global-summary, and negative tasks. Run at multiple project sizes and
fixed budgets.

Primary measurements:

- weighted node/edge/path/facet recall;
- worst-decile recall and catastrophic miss count;
- irrelevant evidence ratio;
- proxy and tokenizer-specific tokens;
- cold/warm latency and memory;
- receipt calibration against evidence misses; and
- result stability under paraphrase and irrelevant-component injection.

Only the non-dominated candidates advance. A candidate that adds substantial
complexity must clear a predeclared minimum effect, not merely score 0.1% higher.

### Round 3 — dynamic maintenance

Cost: hours.

Replay commit sequences and controlled graph mutations. Compare incremental
state to a from-scratch reference after every edit.

Required measurements:

- field/packet delta error;
- stale-evidence exposure rate;
- update work relative to rebuild;
- affected-region recall;
- p50/p95/p99 update latency;
- cache/hierarchy repair debt; and
- rebuild frequency after hub changes and refactors.

An incremental candidate cannot advance based on speed alone; its error and
staleness must remain inside declared tolerances.

### Round 4 — frozen-model interpretation

Cost: controlled model calls.

Before asking for patches, test whether a frozen model can correctly interpret
each packet representation. Include lookup, relation direction, multi-hop path,
aggregation, contradiction, absence, and evidence-citation tasks. Randomize
evidence position to measure lost-in-the-middle sensitivity.

This round selects the renderer independently from retrieval quality.

Run this round as a transfer matrix, not a single-model bakeoff: preregister at
least two unrelated closed-provider families and two unrelated open-weight
families when resources permit, multiple context regimes, prompt-only and tool
protocols, and at least two tokenizers. First compare candidates within each
model. Then estimate cross-model effects. Semantically equivalent packet plans
may use thin protocol-specific serializers, but the core graph, cover,
objective, and receipt must be identical.

### Round 5 — downstream agent tasks

Cost: highest; run only tournament finalists.

Use repository completion and issue-repair tasks with fixed model, prompt,
tools, turns, and total cost. Measure test/compile success, accepted patch rate,
unnecessary edits, time to correct localization, total tokens, latency, and
abstention quality.

Promotion requires either:

- a statistically credible downstream gain with no guardrail regression; or
- an equivalent downstream score at a materially lower total cost/latency.

A candidate promoted as model-agnostic must also clear every preregistered
family's guardrails and must not derive its entire gain from one provider. A
model-family-specific win is a scoped adapter result, not the global default.

### Round 6 — shadow default and rollback

Run the champion beside the incumbent on ordinary local use without changing
the returned result. Compare receipts and log disagreements. Promote behind a
feature flag only after disagreement review. Keep the prior implementation as
fallback until the new path survives a declared observation window.

## 6. Successive halving and budget discipline

Allocate research compute asymmetrically:

1. run every specified candidate on cheap kill tests;
2. retain at most the non-dominated half after synthetic tests;
3. retain at most two or three per stage after deterministic real-project tests;
4. spend model budget only on those finalists; and
5. run expensive issue repair only on complete-system champions.

Candidates must be compared at several resource points rather than one cap:

- tiny: interactive direct lookup;
- small: normal agent turn;
- medium: complex blast radius or subsystem task;
- large: deliberate research/deep-context run.

The output is a Pareto surface by operating regime. There may legitimately be
different champions for direct lookup, global summaries, and dynamic change
analysis. The router can use multiple winners only after each has independently
passed its regime gate.

## 7. Baselines that every “global attention” system must beat

The following baselines prevent the tournament from proving only that a complex
system beats an obsolete one:

1. exact full graph/full corpus where it fits;
2. no project context;
3. lexical/BM25 top-$k$;
4. embedding top-$k$;
5. fixed one- and two-hop graph expansion;
6. flat query-personalized PPR;
7. current production GraphGraph planning and rendering;
8. current production plus a larger budget; and
9. a simple hierarchical baseline: exact local nodes plus containment summaries.

The last baseline is particularly important. It reveals whether learned
communities, low-rank kernels, or adaptive control add value beyond ordinary
package/file hierarchy.

## 8. First candidate set to implement

Do not begin with native model attention or a learned end-to-end controller.
The first tournament should use transparent, deterministic components that can
be checked against exact oracles.

### Incumbent I0

Current GraphGraph anchors, planner, PPR/spreading routes, budget logic, and
packet formats.

### Candidate C1 — simplest multiresolution cover

- existing anchors;
- current typed PPR;
- exact local frontier;
- deterministic file/package containment hierarchy for the far field;
- explicit bridge/test/policy exception reserve;
- fixed error thresholds;
- one-shot packet.

This is the recommended first prototype because it directly tests the novel
coverage-and-resolution claim while reusing current machinery.

The first concrete variant, `C1-PATH-L2MASS-001`, used a bounded-arity path
hierarchy and greedily minimized aggregate L2 reconstruction error plus
$0.01$ times unresolved mass. At equal serialized cost it passed the
development screen on GraphGraph and Requests but failed the frozen Chess and
Express transfer projects. It is therefore a recorded loser as a cross-project
champion. The hierarchy, renderer, and evaluator remain reusable; changing the
formula or weight creates a new candidate and requires a new held-out split.

Two preregistered coefficient sweeps then tested whether the loss was merely a
bad weight. It was not. A mass-only penalty cancels algebraically on
internal-to-internal splits, and weights from `0.001` through `1.0` produced no
cross-project champion. Replacing it with mass times normalized log cell size
did reward every refinement, but all eight weight/budget configurations still
had negative worst-project gain and violated the exact-recall guardrail.
Coefficient tuning for this objective family is stopped.

The next registered variant is `C1-HYBRID-RESERVE-003`: impose a hard exact
token reserve first, treat those entities as sparse exceptions subtracted from
far-field aggregates, and optimize only the residual budget. This is a
structural change, not another post-hoc weight.

### Candidate C2 — local diffusion variant

Replace full PPR computation with residual/local push under the same cover and
measure localization, error, and speed.

### Candidate C3 — heat-kernel variant

Replace PPR with heat-kernel diffusion and sweep the diffusion time. It may
favor smaller coherent neighborhoods but must retain global/exception coverage.

### Candidate C4 — semantic landmark residual

Add diverse semantic landmarks and an explicit residual to C1. Test only after
C1 establishes whether multiresolution representation itself is useful.

### Candidate C5 — adaptive refinement

Add budgeted analytic value-of-refinement and iterative expansion to the best
of C1–C4. Compare exact dynamic programming on small hierarchies, one-step
greedy, bounded lookahead/knapsack approximations, and fixed thresholds before
training any controller. The one-step rule is retained as a rejected/limited
candidate: Phase 0 found a six-leaf, five-unit case where it has $42.67\%$ more
L2 regret than the exhaustive optimum. It may still win on runtime, but cannot
claim optimality.

### Deferred candidates

- learned hierarchy construction;
- end-to-end learned routing/stopping;
- graph attention tensors inside an open model;
- provider-specific KV-cache manipulation; and
- GPU-native dense project kernels.

These are scientifically interesting but add confounders before the external
field approximation has been validated.

## 9. Champion decision rule

For an operating regime $r$, candidate $c$ is promotable only if:

$$
Q_c - Q_I \ge \delta_Q,
$$

or

$$
|Q_c-Q_I| < \delta_{eq}
\quad\text{and}\quad
C_c \le (1-\delta_C)C_I,
$$

with confidence intervals satisfying the preregistered test. $Q$ is the primary
quality metric and $C$ is total cost. In both cases all guardrails must pass:

$$
\begin{aligned}
\text{worst-decile recall}_c &\ge \text{floor}_r,\\
\text{catastrophic misses}_c &\le \text{ceiling}_r,\\
\text{stale exposure}_c &= 0\ \text{on deterministic gates},\\
\text{packet validity}_c &= 1,\\
\text{receipt calibration}_c &\ge \text{minimum}_r.
\end{aligned}
$$

If several candidates qualify, choose in this order:

1. fewer catastrophic failures;
2. better held-out downstream quality;
3. lower total model + retrieval cost;
4. lower p95 latency and memory;
5. simpler implementation and fewer dependencies; and
6. easier auditability and rollback.

No undocumented weighted average may override these rules after results are
known.

## 10. Deliverables from each research cycle

Each cycle ends with:

- updated atomic claim ledger;
- candidate configurations and source hashes;
- frozen task and repository splits;
- raw packets, receipts, timings, and model traces;
- comparison report including negative results;
- Pareto plots by project size and query class;
- ablation and failure analysis;
- explicit champion/no-champion decision; and
- a narrow work order only for the winning implementation.

If no candidate clears the incumbent, the correct result is **no change**. The
research has still succeeded by reducing uncertainty.

### Candidate F1 — symmetric field coupling

The `represent` stage was being tuned over a substrate that carries no
far-field mass. `EXP-GPA-COUPLING` held the hierarchy, tasks, seeds, budgets,
and metrics fixed and exchanged only the edge coupling that diffuses the
query-conditioned field. The incumbent directed coupling is degenerate on
three of four projects — median support `0.0107%`–`0.0291%` and **zero** mass
outside the top 64 entities — because 62.9% of active entities are directed
sinks. Symmetric coupling is non-degenerate on four of four (median support
`98.46%`–`99.95%`, 62.5% of mass outside the top 64).

This does not explain the recorded C1 pass/fail split: GraphGraph passed at
`0.0107%` support while Chess failed at `0.0221%`. What it does establish is
that on most projects `EXP-GPA-C1-P1` and `EXP-GPA-C1-FORMULA-SWEEPS` compared
cover formulas over an empty far field, so their formula-level conclusions do
not isolate the formula. `C1` and `C1-HYBRID-RESERVE-003` must be re-measured
under `F1-SYMMETRIC-COUPLING` before any cover verdict is final. Full
measurement:
[the consolidated influence-field measurement](../evaluation/graybox-cycles/README.md#influence-field-experiment).

Non-degeneracy is a precondition, not a result. Whether a multiresolution
representation over a real field beats an equal-token flat packet is
`EXP-GPA-HYBRID-RESERVE`, still pending.

Re-run completed: `EXP-GPA-RECOUPLED` and `EXP-GPA-HYBRID-RESERVE`. On a
substrate that now supplies a real far field (aggregate mass `0.0` → `0.43`–
`0.61`, refinements `0` → `5`–`7`), the representation still loses at equal
tokens — worst-project median resolution gain `+0.0000` against a required
`+0.02`. An aggregate cell of `k` members is worth `1/k` where an exact line is
worth `1`, at comparable token cost, so aggregation only pays when the field
cannot rank. **`C1-HYBRID-RESERVE-003` is not promotable and its experiment is
recorded `failing`.**

The same run produced an unlooked-for result: symmetric coupling improves the
equal-token flat baseline itself, mean exact recall `0.5035` → `0.5694`, 32 of
72 paired cases improved against 3 regressed. The value of this research line
so far is a better *field*, not a better *representation*. See
[the consolidated influence-field measurement](../evaluation/graybox-cycles/README.md#influence-field-experiment).

## 11. Immediate next work order

0. **Build a paraphrase/conceptual eval task set before tuning any field
   stage again.** `EXP-GPA-COUPLING-PROD` measured every coupling through
   production `search_nodes` and found no change in recall or first-hit MRR —
   and disabling personalized PageRank entirely scores identically. All 21
   ranked lists do change, so the term is active; it reorders the tail below
   the first hit. The current labelled tasks name their target symbol, so
   lexical matching decides the head and no field-stage candidate is
   detectable. Until tasks exist whose queries share no tokens with their
   answers, field work cannot be evaluated, and `F1-SYMMETRIC-COUPLING` is
   rejected on production evidence. See
   [the terminal leverage finding](../evaluation/graybox-cycles/README.md#influence-field-experiment).
1. Keep every new claim and candidate synchronized with the executable
   registry and its evidence paths.
2. Preserve the Phase 0 exact oracle as an evaluator-only ceiling; never feed
   oracle mass into retrieval.
3. Expand adversarial formula search beyond the recorded greedy and
   L1-versus-L2 counterexamples.
4. Implement the common stage interfaces for C1–C3 without altering the
   production default.
5. Freeze equal-token, equal-latency Round 2 tasks and repository-held-out
   splits before tuning.
6. Preregister the Round 4–5 model/provider/tokenizer transfer matrix and
   protocol adapters before buying model runs.
7. Implement only candidates that clear their current round; if none beats I0,
   record **no change**.

This sequence finds the best implementation by evidence before committing to a
large architecture. It also allows genuinely new research to beat the current
proposal rather than being forced into it.
