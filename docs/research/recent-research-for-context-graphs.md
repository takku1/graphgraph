# Recent AI Concepts for GraphGraph

## Research intake, candidate experiments, and explicit non-goals

**Status:** Research intake and decision note. This document does not describe
promoted production behavior.

**Review date:** 2026-08-02. Sources include recent 2025-2026 work and older
foundational papers needed to interpret it. New preprints are treated as
hypothesis sources, not design authority.

## 1. Decision in one page

GraphGraph should not become a neural Mixture-of-Experts (MoE) system, an LLM
inference engine, or a general agent framework. It owns a different boundary:

```text
repository state + query
    -> typed graph evidence
    -> bounded retrieval and selection
    -> mechanically validated context packet
    -> external agent/model
```

Several recent AI ideas are nevertheless useful when translated into this
boundary:

1. **Sparse expert routing** becomes selecting a small set of typed retrieval
   strategies or evidence sources for each query facet.
2. **Speculative decoding** becomes constructing a cheap candidate packet,
   verifying it internally, and expanding to the full retrieval path when the
   candidate fails a structural or coverage gate.
3. **Adaptive RAG and context compression** become query- and risk-dependent
   packet budgets, while preserving exact evidence for high-cost omissions.
4. **Agentic context engineering** becomes versioned, incremental context and
   memory updates with receipts, never untracked prompt rewriting.
5. **Agent memory graphs** become a provenance-separated memory layer projected
   into the normal GraphGraph IR, never a replacement for source-derived facts.
6. **Context-description languages** become a machine-readable manifest of what
   was included, excluded, conditional, refreshed, and carried across turns.
7. **Recent coding-context benchmarks** strengthen the case for task-specific
   retrieval, abstention tests, and process-level evaluation rather than one
   aggregate retrieval score.

The immediate recommendation is to test these as interchangeable candidates
under the existing [research tournament](context-system-tournament.md).
Do not add new frameworks or production branches before equal-budget results
show a meaningful win.

## 2. The boundary that prevents category errors

GraphGraph chooses evidence and a token prefix for a model it normally does not
host or inspect. It cannot see model attention heads, activation probabilities,
draft-token acceptance, gradients, or GPU load. The repository already states
this boundary explicitly in [the kiminotes follow-up](external-mechanism-notes-followup.md).

This means a paper's objective may transfer while its mechanism does not. For
example, DSpark's objective of avoiding wasted verification is relevant;
DSpark's semi-autoregressive draft model is not. MoE's objective of bounded
specialization is relevant; neural gates and expert-parallel training are not.

Use the following translation discipline:

| Model-system term | GraphGraph analogue | Important mismatch |
| --- | --- | --- |
| token/sample | query or independently required query facet | facets can have asymmetric safety cost |
| expert | typed operator, retrieval strategy, or evidence provider | GraphGraph experts are algorithms, not learned parameter blocks |
| gate/router | query compiler plus query-class/source planner | routing must be explainable, reproducible, and able to abstain |
| expert capacity | token, node, edge, latency, and provider budgets | critical relations cannot be dropped merely to balance load |
| sparse activation | run only the useful retrieval stages | the cheapest route still needs coverage and freshness checks |
| expert output fusion | typed evidence merge and packet selection | evidence needs provenance, deduplication, and contradiction handling |
| draft model | exact lookup, cache, or cheap one-hop candidate | there is no target-model oracle to certify semantic correctness |
| verification | freshness, ambiguity, facet, policy, relation, and packet gates | validation proves only declared properties, not answer truth |
| evolving context | versioned memory/episode/context delta | self-generated text must not overwrite structural facts |

## 3. What GraphGraph already has

The production architecture already contains most of the safe extension points:

- [`planning/query_compiler.py`](../../src/graphgraph/planning/query_compiler.py)
  chooses lossless specialized read-only operators and falls back to general
  context retrieval when specialization would drop a clause.
- [`planning/routing.py`](../../src/graphgraph/planning/routing.py) routes query
  classes with explicit reasons, confidence, margin, and broad-fallback
  abstention.
- [`retrieval/facets.py`](../../src/graphgraph/retrieval/facets.py) extracts query
  facets, reserves evidence, and reports facet coverage.
- [`platform/source_planner.py`](../../src/graphgraph/platform/source_planner.py)
  conditionally projects semantic, memory, temporal, federation, and runtime
  evidence into the native graph.
- [`platform/contracts.py`](../../src/graphgraph/platform/contracts.py) defines
  typed evidence-provider capabilities, merge behavior, and receipts.
- [`planning/packet.py`](../../src/graphgraph/planning/packet.py) selects measured
  packet strategies by query class and observed subgraph shape.
- [Retrieval confidence and routing](../architecture/information-retrieval/confidence-and-routing.md) already
  distinguishes exact lookup confidence from broad architectural retrieval and
  documents that current thresholds are provisional.

The first experiments should compose these pieces. A new abstraction is
justified only if the existing contracts prevent a controlled comparison.

## 4. Paper and concept scan

### 4.1 Directly relevant recent work

| Source | What the work contributes | Transferable candidate | What does not transfer |
| --- | --- | --- | --- |
| [Agent Retrieval Bench (2026)](https://arxiv.org/abs/2607.24882) | Coding-specific upstream retrieval tasks, no-gold controls, and evidence that different retrieval families win different task slices | Add task-stratified retrieval and abstention evaluation; compare route families by `code2test`, `comment2context`, `trace2code`, and `edit2ripple`-like tasks | Do not assume its file-level labels fully evaluate GraphGraph's symbol, edge, policy, or packet contracts |
| [ContextBench (2026)](https://arxiv.org/abs/2602.05892) | Process-level coding-agent context recall, precision, and efficiency over issue-resolution trajectories | Measure explored, emitted, and actually used context separately; add multilingual/cross-repository transfer slices | Do not equate final patch success with retrieval quality or copy an entire agent scaffold into GraphGraph |
| [A Language for Describing Agentic LLM Contexts (2026)](https://arxiv.org/abs/2605.01920) | A formal description of dynamic, conditional, and iterative agent contexts | Prototype a compact context-composition manifest and compare plans structurally across runs | Do not adopt another full DSL unless a minimal receipt extension cannot express the needed state |
| [DSpark (2026)](https://arxiv.org/abs/2607.05147) | Confidence-scheduled speculative decoding with adaptive verification length | Test risk- and confidence-scheduled verification for cheap candidate packets | Do not add a draft model, token verifier, semi-autoregressive decoder, batching policy, or inference-serving dependency |
| [EverydayGPT (2026)](https://arxiv.org/abs/2606.11212) | Confidence-gated routing between fast extraction and a costly generative path | Compare calibrated route/accept/fallback policies using risk-coverage and latency curves | Its in-domain QA results and thresholds do not establish coding-context calibration |
| [Agentic Context Engineering (2025/2026)](https://arxiv.org/abs/2510.04618) | Incremental generation, reflection, and curation of evolving playbooks; identifies context collapse from repeated rewriting | Test append/refine/curate memory updates with immutable history and replayable receipts | Do not allow self-generated playbooks to silently become source, policy, or architecture authority |
| [Adaptive Context Compression for RAG (2025)](https://arxiv.org/abs/2507.22931) | Query-complexity-dependent compression and multi-granular selection | Compare adaptive packet budgets and exact-near/compressed-far representations against fixed budgets | Wikipedia QA speedups do not imply safe code-impact compression |
| [SARA (2025)](https://arxiv.org/abs/2507.05633) | Combines fine-grained text with compressed global representations and iteratively reranks evidence | Test an exact-evidence plus compact-overview packet ladder and gap-driven reranking | Do not emit opaque semantic vectors to arbitrary downstream models or require model-specific adapters in core |
| [HippoRAG 2 (2025)](https://arxiv.org/abs/2502.14802) | Associative graph memory using Personalized PageRank plus passage integration | Compare memory-only associative retrieval and typed PPR against current lexical/structural baselines | Do not mix mutable episodic memory with source-derived structural edges or import human-memory claims as correctness evidence |
| [A-MEM (2025)](https://arxiv.org/abs/2502.12110) | Dynamically linked and evolving agent memories | Test typed memory links, evolution events, and temporal retrieval behind a separate provenance boundary | Do not rewrite old memories without history, permit recursive self-confirmation, or treat generated links as observed facts |
| [Adaptive-RAG (2024)](https://arxiv.org/abs/2403.14403) | Routes queries among no-retrieval, single-step, and iterative retrieval according to predicted complexity | Compare the current rule router with deterministic complexity features and, later, a shadow learned router | Do not put a small LM router on the default offline path before it wins held-out, cross-repository tests |

Recent coding-context results deserve more weight than generic QA results. In
particular, Agent Retrieval Bench reports no universal retrieval winner and a
calibration gap between synthetic controls and natural no-gold cases. That is a
direct warning against one global router threshold.

### 4.2 Foundational analogies needed to interpret the newer work

| Source | Useful idea | GraphGraph interpretation |
| --- | --- | --- |
| [Switch Transformers](https://arxiv.org/abs/2101.03961) | Simple sparse top-1 routing under bounded active compute | Prefer the smallest sufficient strategy set and measure routing overhead |
| [Expert Choice Routing](https://arxiv.org/abs/2202.09368) | Capacity-controlled expert allocation rather than fixed experts per token | Let providers declare capabilities/costs and test budget-aware assignment; never let capacity balance starve required facets |
| [Fast Inference via Speculative Decoding](https://arxiv.org/abs/2211.17192) | Cheap approximation followed by lossless target verification and fallback | A speculative packet is acceptable only when its verifier preserves GraphGraph's declared contract |

These papers motivate experiments. They do not justify calling GraphGraph an
MoE system or claiming speculative-decoding guarantees for retrieval.

## 5. Candidates worth testing

The IDs below are proposed research-intake IDs. Before implementation, copy the
selected candidate into `eval/context-system-research.json` with frozen data,
metrics, budgets, stop conditions, and artifact paths as required by the
[research tournament](context-system-tournament.md).

### AI-CTX-01 — Task-stratified external retrieval evaluation

**Priority:** P0; measure before changing algorithms.

**Mechanism:** Adapt or reproduce license-compatible slices of Agent Retrieval
Bench and ContextBench against frozen repositories. Preserve their task strata
instead of reporting only a pooled mean.

**Baseline:** Current automatic GraphGraph query/context path plus lexical and
embedding baselines at equal token budgets.

**Measure:** file and symbol Recall@k, edge/path recall, budgeted context yield,
facet completion, abstention risk-coverage, explored-versus-emitted context,
latency, tokens, and downstream patch success as a separate metric.

**Guardrails:** frozen base commits; no gold evidence available during
retrieval; natural no-gold and wrong-repository controls; report per-language,
per-task, worst-decile, and cross-repository transfer.

**Reject the evaluation design if:** it collapses all task families into one
score, cannot represent typed edge/path gold, or leaks future patches.

### AI-CTX-02 — Multi-route compound-query retrieval

**Priority:** P1.

**Mechanism:** Split a compound query into required facets, route each facet to
one or more existing query classes/operators, merge typed evidence, and reserve
budget for every required facet. This is the useful system-level analogue of
sparse expert activation.

**Candidates:** current single-route behavior; deterministic top-2 routes;
per-facet routes; cost-aware provider assignment. Keep all candidates behind
the same plan/result/receipt contract.

**Measure:** complete-facet rate, per-facet node/edge recall, direct-caller and
affected-test recall, token count, p50/p95 latency, duplicate evidence, and
fallback rate.

**Guardrails:** no regression for negative queries, policy/configuration nodes,
bridge nodes, or direct callers in blast-radius tasks. An average gain cannot
offset a catastrophic-facet miss.

**Reject if:** the incumbent's facet reservation matches it at lower
complexity, or route fusion increases tokens/latency without a held-out recall
gain.

### AI-CTX-03 — Verified speculative packet construction

**Priority:** P1.

**Mechanism:** Build a cheap internal candidate from exact lookup, cached
results, or a one-hop relation operator. Before returning it, run a verifier
covering freshness, scope, anchor ambiguity, required facets, critical relation
coverage, policy obligations, truncation, and packet validity. Fall back to the
normal context compiler on any failed or unknown gate.

**Measure:** accepted-candidate rate, false-accept rate, latency saved, tokens
saved, verification cost, fallback cost, and performance by query class.

**Guardrails:** never stream or expose the candidate before verification; never
use expected answers as verifier input; distinguish `unknown` from `pass`; log
the exact acceptance reasons.

**Reject if:** verification costs erase the fast-path gain, any critical
false-accept survives, or the verifier merely repeats full retrieval.

### AI-CTX-04 — Adaptive exact/compressed packet ladder

**Priority:** P1.

**Mechanism:** Allocate exact source and typed edges to high-risk/local facets,
with progressively coarser summaries for low-risk/distant context. Compare
fixed budgets with budgets derived from query class, facet count, graph shape,
ambiguity, and remaining uncertainty.

**Candidates:** current packet planner; query-complexity budget; exact-near plus
compressed-far; iterative expand-on-gap.

**Measure:** complete recall at equal tokens, answer accuracy, ordering
sensitivity, compression loss by relation type, latency, and prefix stability.

**Guardrails:** source identifiers, signatures, paths, policy text, numerical
values, and direct dependency edges stay exact when required. Generated
summaries must carry provenance and cannot be the only evidence for absence.

**Reject if:** a fixed budget or current `gg` packet is equivalent within
confidence intervals, or compression improves mean scores while worsening
critical omissions.

### AI-CTX-05 — Context-composition manifest

**Priority:** P1, small prototype.

**Mechanism:** Extend existing receipts with a compact, implementation-neutral
description of context state: ordered components, provenance, conditional
branches, refresh state, carried memory, omissions, truncation, and refinement
history. Evaluate whether this is sufficient before adopting an external DSL.

**Measure:** deterministic replay, structural diff quality between strategies,
debugging time on failed tasks, receipt size, and whether every emitted span is
traceable to a source or transformation.

**Reject if:** existing receipts already answer the same questions, or the
manifest becomes a second execution language rather than an observation of the
real plan.

### AI-CTX-06 — Provenance-safe evolving memory

**Priority:** P2; only after memory-specific datasets and authority rules exist.

**Mechanism:** Store immutable memory events, derive typed links and summaries
as versioned projections, and allow later evidence to supersede rather than
overwrite prior records. Project selected memory into normal GraphGraph nodes
and edges at query time.

**Candidates:** immutable append-only memory; linked memory; curated/evolving
projection; PPR/activation over memory-only edges.

**Measure:** temporal retrieval precision/recall, stale-memory rate,
contradiction detection, provenance completeness, update cost, context tokens,
and downstream task success.

**Guardrails:** source graph wins authority conflicts; generated memories cannot
create structural `calls`, `imports`, `tests`, or policy facts; every mutation
is replayable and reversible; prevent self-retrieval from recursively increasing
confidence.

**Reject if:** dynamic linking does not beat immutable lexical/semantic memory,
or it introduces provenance ambiguity and stale self-confirmation.

### AI-CTX-07 — Gap-driven iterative retrieval

**Priority:** P2.

**Mechanism:** After the first packet plan, inspect declared missing facets,
weak anchors, uncovered path obligations, contradictory evidence, and
truncation. Spend another bounded retrieval step only on a named gap, with an
analytic stop reason.

**Measure:** marginal recall or answer gain per added token/millisecond,
iterations, stop accuracy, repeated evidence, and worst-case boundedness.

**Guardrails:** hard iteration and token ceilings; no free-form model loop in
the core retriever; each iteration must name the unmet obligation it addresses.

**Reject if:** one-shot retrieval at the same total budget performs as well, or
the controller cannot distinguish productive refinement from repeated search.

### AI-CTX-08 — Router calibration and selective abstention

**Priority:** P2, after AI-CTX-01 supplies enough labels.

**Mechanism:** Compare the current interpretable log-linear router with
calibrated deterministic scores, multinomial/logistic models, and a learned
router in shadow mode. Calibrate by task/risk stratum rather than forcing one
global threshold.

**Measure:** Brier score, ECE/MCE, risk-coverage, route accuracy, complete-facet
rate, fallback cost, cross-repository transfer, and worst-stratum recall.

**Guardrails:** held-out repositories and time splits; no calibration on answer
evidence; explicit `unknown`/abstain outcome; offline deterministic fallback.

**Reject if:** learned routing does not beat the rule router by a preregistered
minimum effect after its latency, dependency, privacy, and failure costs.

### AI-CTX-09 — Provider capacity scheduling

**Priority:** P3/watch.

**Mechanism:** Let evidence providers expose capabilities, estimated marginal
cost, freshness, and bounded capacity. Compare central query allocation,
provider bids, and the current source planner under the same global budget.

**Measure:** facet coverage per provider cost, utilization, starvation,
duplicates, latency, and critical-relation recall.

**Guardrails:** mandatory facets and structural evidence override load
balancing; deterministic tie-breaking; no provider can promote its own
confidence without independent calibration.

**Reject if:** scheduling overhead exceeds saved provider work or simple
query-term rules are equivalent.

## 6. Recommended order

1. **Establish the external measurement layer:** AI-CTX-01.
2. **Test low-risk uses of current contracts:** AI-CTX-02, AI-CTX-03, and
   AI-CTX-05.
3. **Test packet quality/efficiency tradeoffs:** AI-CTX-04 and AI-CTX-07.
4. **Only after sufficient labels exist:** AI-CTX-08.
5. **Only with explicit memory authority semantics:** AI-CTX-06.
6. **Keep as a later optimization:** AI-CTX-09.

The order matters. A more sophisticated router cannot be evaluated honestly
without task-stratified retrieval labels, natural abstention cases, and a
process-level receipt.

## 7. Explicitly do not add

The following items are out of scope unless GraphGraph's product boundary
changes and a separate proposal supplies evidence:

- **Neural MoE layers, expert-parallel training, auxiliary balancing losses, or
  differentiable gates.** GraphGraph selects algorithms and evidence; it does
  not train parameter experts.
- **DSpark or another speculative-decoding runtime.** Draft heads, token
  verification, batching, KV-cache scheduling, and GPU kernels belong to the
  model-serving layer.
- **Unverified speculative context.** An incomplete packet must not reach an
  agent merely because it was cheap or high-confidence.
- **A learned/LLM router on the mandatory default path.** Keep the offline,
  deterministic router and fallback until held-out results justify an optional
  replacement.
- **Self-modifying source truth.** Agent memory, summaries, and reflections may
  supplement source evidence but may not rewrite source-derived structure,
  policy, or history.
- **Opaque vector payloads as a universal packet format.** Arbitrary downstream
  models cannot interpret model-specific latent vectors, and such payloads are
  difficult to audit.
- **Attention-guided compression that requires private model internals.** Test
  black-box or local variants separately; do not make provider telemetry a core
  contract.
- **A second graph or memory store used as parallel structural truth.** External
  evidence must be normalized into GraphGraph nodes/edges with provenance and
  receipts before retrieval.
- **Unlimited multi-agent or multi-retriever fan-out.** Parallelism is not free;
  compare it under the same latency, token, and provider-cost ceilings.
- **A general context-engineering DSL before a receipt extension is tested.** A
  manifest should describe the actual pipeline, not become another pipeline to
  keep synchronized.
- **Apache Spark or another distributed data engine without a measured scale
  failure.** Distribution adds serialization, deployment, and consistency costs
  that current in-process graphs have not shown they need.
- **DSPy as a core runtime dependency, if `DSpark` was meant as `DSPy`.** DSPy
  may be useful in an optional prompt/router optimization experiment, but the
  GraphGraph core should remain model- and framework-independent.
- **Branding the architecture as “MoE.”** “Typed strategy routing,” “multi-route
  retrieval,” and “evidence providers” describe the system more accurately and
  avoid implying neural-training properties GraphGraph does not have.
- **Paper-result inheritance.** Reported gains on QA, finance, or model-serving
  workloads are priors for experiments, not expected GraphGraph improvements.

## 8. Promotion checklist

A candidate from this document can affect production only after it has:

1. a registry entry with a stable claim and experiment ID;
2. an implementation behind an existing or explicitly justified common
   interface;
3. equal graph, query, freshness, token, and latency budgets against a strong
   incumbent;
4. held-out repository and cross-language results where applicable;
5. per-stratum and worst-decile reporting, not only pooled means;
6. critical-relation and policy guardrails with no hidden average tradeoff;
7. deterministic receipts, provenance, truncation, and fallback behavior;
8. a recorded rejection condition and result artifact even when it loses; and
9. a reversible feature flag plus automatic fallback if promoted.

The default decision remains: retain the simpler incumbent when results are
equivalent within uncertainty.

## 9. Source-quality caveats

Several 2026 references above are recent arXiv preprints. Their mechanisms and
reported results may change after review or later versions. Even peer-reviewed
papers were evaluated in domains that differ from repository context retrieval.
The sources justify candidates and failure hypotheses only. GraphGraph's own
frozen-repository, equal-budget, code-specific experiments decide promotion.
