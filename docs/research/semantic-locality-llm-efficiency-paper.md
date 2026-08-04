# Semantic Locality in Codebase Context Retrieval

## A position paper on information density, attention risk, and GraphGraph's LLM-native context IR

**Author:** Dillon Carney (Independent Researcher)

**Date:** July 2026

**Status:** Technical position paper; not peer reviewed

## Abstract

Repository-scale AI agents need enough code evidence to answer a query without
filling the model context with unrelated source. This paper examines
**semantic locality** as a context-selection principle: favor evidence close to
the query's entities, requested facets, and typed dependency paths.

The central claim is deliberately limited. Semantic locality does not reduce
the floating-point work of a standard dense Transformer at a fixed sequence
length. It can reduce end-to-end work when the retrieval system emits fewer
tokens or avoids additional tool calls, and it may improve answer quality by
removing distractors. The quality claim remains model- and task-dependent and
must be measured.

GraphGraph translates this principle into an external context compiler:
exact anchors, typed propagation, evidence-constrained selection, compact graph
serialization, bounded source windows, and fail-closed receipts. On a
48-task deterministic Locus evidence-containment suite, its adaptive route
reduced mean packet size from 843.1 to 690.0 tokens (18.1%) while retaining all
benchmark-required evidence. This is not yet evidence of improved live
code-generation accuracy. A separate topology-free experiment showed no
demonstrated latency benefit and was removed.

## 1. Claim boundary

Three meanings of "efficiency" must not be conflated.

### 1.1 Dense-model compute at fixed length

For a conventional dense Transformer, semantically coherent tokens do not
cause attention heads to skip layers or matrix multiplications. Model weights
are fixed during ordinary inference. Activations and KV-cache contents change
with the prompt, but a domain shift does not by itself change the model's
execution graph.

Parameter-count rules of thumb such as roughly two floating-point operations
per active parameter per generated token omit attention, memory movement,
prefill, batching, and serving overhead. They are not a complete latency model.

### 1.2 End-to-end system work

Retrieval can reduce real work by shortening the prompt, reading fewer source
windows, reusing a loaded graph, incrementally processing changed files, and
combining topology and source in one tool response. The magnitude depends on
the model, serving stack, cache state, repository, and query.

### 1.3 Answer quality

Irrelevant or badly positioned evidence can reduce long-context task
performance. *Lost in the Middle* demonstrates position-sensitive degradation
on multi-document question answering and key-value retrieval, but it does not
prove that every form of semantic locality improves every coding task.

The paper therefore treats reduced distraction and lower conditional
uncertainty as hypotheses and design goals, not guaranteed neural mechanisms.

## 2. Information-theoretic framing

Let \(Q\) be the query, \(C\) the selected context, and \(Y\) the desired
response:

$$
P(Y \mid C,Q)=\prod_t P(y_t \mid y_{<t},C,Q)
$$

An ideal selector would find context that reduces:

$$
H(Y \mid C,Q)
$$

or, using an information-bottleneck-style objective:

$$
\max_C I(Y;C\mid Q)-\beta\,\operatorname{cost}(C)
$$

This is a conceptual formulation. At retrieval time, \(Y\) and its true
distribution are unknown, so GraphGraph cannot calculate either term.
Observable proxies include resolved entities, requested-facet coverage, typed
path support, source proximity, unsupported boundary crossings, and serialized
token cost.

The attention operation:

$$
\operatorname{softmax}\left(\frac{QK^\mathsf{T}}{\sqrt{d_k}}\right)V
$$

does not prove a simple "more tokens always dilute evidence" rule. Additional
tokens add attention candidates, but learned logits may remain sharply
concentrated. Attention competition is a plausible failure mode to evaluate,
not a theorem derived from the denominator.

## 3. GraphGraph as an LLM-near context compiler

GraphGraph does not claim to reproduce a model's latent space or weights. It
compiles repository evidence into a small, explicit intermediate
representation:

```text
query terms + paths + facets
    -> exact/lexical anchor mass
    -> query-shaped typed traversal
    -> evidence- and budget-constrained selection
    -> compact graph packet + optional bounded source
    -> structural and semantic receipt
```

This representation is close to an LLM in the same sense that an instruction
set is close to hardware: it exposes the relations needed by the next
computation while removing repository detail that the current task did not
request.

A useful design objective for packet \(P\) is:

$$
\max_{P\subseteq G}
\operatorname{coverage}(P,Q)
+\operatorname{typedSupport}(P,Q)
-\lambda_t\operatorname{tokens}(P)
-\lambda_x\operatorname{unsupportedCrossings}(P)
$$

GraphGraph does not optimize this as one learned objective. Production behavior
is decomposed across routing, information-gain-regularized budgets, changed-path
anchors, typed traversal strengths, relation-shaped edge quotas, connected
selection, and receipt validation.

## 4. Serialization and the indirection hypothesis

GraphGraph supports numeric and lexical graph handles:

```text
# numeric
[n] 1 AuthService
[n] 2 TokenStore
[e] 1 2 calls

# lexical
[n] authserv AuthService
[n] tokensto TokenStore
[e] authserv tokensto calls
```

Lexical handles may reduce the model's need to resolve numeric references and
may retain useful subword cues. That proposed **attention-indirection penalty**
has not yet been isolated by live-model scoring. Current measurements show the
trade-off clearly: lexical handles cost roughly 10–13% more tokens than the
numeric format. `gg_lex` should remain opt-in until frozen answer-quality tests
show that the extra tokens buy a repeatable gain.

## 5. Ripgrep's staged-execution lesson

The transferable idea from ripgrep is staged work:

| Search-engine mechanism | LLM-context translation |
| --- | --- |
| Required literal before regex verification | Exact symbol, path, and facet anchors before propagation |
| Verify only around candidates | Typed-edge checks and bounded source around selected anchors |
| Input-shaped buffer strategy | Cached graph, changed-path splice, or live source by query shape |
| Reused workers and buffers | Persistent graph and index caches |
| Early match termination | Candidate: stop when requested facets have attributed evidence |
| Explicit regex bounds | Node, edge, hop, source-line, and token budgets |
| Ignore rules before matching | Exclude generated, vendored, secret-bearing, and irrelevant files |

This is not an argument that a graph should replace text search. Exact lexical
lookup is often the correct first stage, especially in small repositories. The
product goal is a single interface that selects the cheapest trustworthy path.

## 6. Current evidence

### 6.1 Deterministic evidence containment

The 48-task Locus suite measures whether a packet contains a predeclared set of
required graph evidence:

| Route | Mean packet tokens | Required-evidence containment |
| --- | ---: | ---: |
| Uniform 120-node route | 843.1 | 100% |
| Adaptive planning | 690.0 | 100% |
| Oracle evidence floor | 657.1 | 100% by construction |

Adaptive planning reduced mean packet size by 18.1% and was 5.01% above the
oracle evidence-containment floor.

These results do not measure live answer correctness, compilation success,
test-pass rate, hallucination rate, or independently sampled generalization.
Calling them "downstream code-generation results" would be incorrect.

### 6.2 Rejected topology-free branch

An experimental topology-free branch measured approximately 97.7 ms warm on a
5,026-node self-graph, versus approximately 93.6 ms for the existing path.
This was not a controlled comparison with ripgrep or a flat scan of all source
contents. The small difference does not identify a causal topology speedup.
Because the branch demonstrated no advantage, it was removed.

### 6.3 Round-three system changes

The retained changes target correctness and agent-loop cost:

- affected-test commands now fail semantic validation when no direct or
  transitive test evidence is attributed;
- refresh receipts distinguish requested paths, refreshed/removed paths, graph
  writes, and remaining stale paths;
- source-snippet retrieval reuses the loaded graph;
- `query_context` can return graph topology and bounded, current source in one
  response without caching stale raw lines.

### 6.4 Native exact-anchor fast path

A source audit found that exact direct lookups still paid for PageRank, full
lexical indexing, document/code profiling, and graph-shape budgeting. The
production path now checks a small revision-aware literal index first.
Unambiguous explicit IDs, identifiers, filenames, and paths bypass those
ranked/topological preparation stages and auxiliary semantic sources.
Ambiguous names and natural-language queries retain the full ranked path.

Five repetitions on freshly parsed Graph objects from the 5,170-node saved
self-graph used `recommend_node_budget` as the exact identifier. Median native
exact search was 17.277 ms, compared with 532.094 ms for normal ranked/PPR
search; both returned the same first node. Full context compilation on the
exact route measured 65.087 ms median and reported the exact-path receipt.
These figures exclude graph parsing, are not a comparison with ripgrep, and say
nothing about LLM answer quality.

This implementation is entirely native GraphGraph. Graphify was used only as a
comparison baseline during the design audit; it is not a runtime dependency,
wrapper, adapter, or fallback.

## 7. Constants versus adaptive formulas

Constants remain appropriate for protocol tags, hard safety ceilings,
compatibility behavior, and reproducible benchmark defaults. Adaptive formulas
are better candidates when repository size, density, query class, anchor
confidence, or facet coverage materially changes the optimal amount of work.

Complexity is not evidence of optimality. A dynamic rule should be retained
only when it improves a frozen metric without unacceptable regressions. The
topology-free experiment is an example of rejecting a plausible mechanism that
did not earn its complexity.

## 8. Falsifiable next tests

The semantic-locality thesis should be evaluated with:

1. frozen queries and target evidence across repositories and languages;
2. packet-token, source-line, tool-call, cold-latency, and warm-latency metrics;
3. live answer scoring for parse rate, node/edge recall, hallucinations,
   compilation, and target tests;
4. randomized packet-format comparisons for numeric, lexical, and verbalized
   relations;
5. distractor ablations that hold relevant evidence and approximate token
   length constant;
6. confidence intervals and repeated runs rather than single timing ratios.

Facet-aware early termination remains an explicit test candidate rather than a
claimed production feature. Current retrieval performs bounded facet searches
and computes completeness after expansion. Promoting an earlier cutoff requires
a frozen coverage/latency benchmark showing that it does not remove typed
support needed by the final receipt.

Until those tests pass, semantic locality is a disciplined retrieval hypothesis
with encouraging structural results—not a claim that latent proximity changes
dense-model compute or guarantees better answers.

## References

- Vaswani, A., et al. (2017).
  [*Attention Is All You Need*](https://arxiv.org/abs/1706.03762). NeurIPS.
- Tishby, N., Pereira, F. C., and Bialek, W. (1999).
  [*The Information Bottleneck Method*](https://arxiv.org/abs/physics/0004057).
  Allerton Conference.
- Liu, N. F., et al. (2023).
  [*Lost in the Middle: How Language Models Use Long Contexts*](https://arxiv.org/abs/2307.03172).
- Jiang, H., et al. (2023).
  [*LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models*](https://arxiv.org/abs/2310.05736).
- Wu, D., et al. (2024).
  [*Repoformer: Selective Retrieval for Repository-Level Code Completion*](https://arxiv.org/abs/2403.10059).
- Zhang, F., et al. (2023).
  [*RepoCoder: Repository-Level Code Completion Through Iterative Retrieval and Generation*](https://arxiv.org/abs/2303.12570).
- Ye, T., et al. (2024).
  [*Differential Transformer*](https://arxiv.org/abs/2410.05258).
- Gallant, A. (BurntSushi).
  [*ripgrep source repository*](https://github.com/BurntSushi/ripgrep).
