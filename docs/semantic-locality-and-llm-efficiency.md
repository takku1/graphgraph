# Semantic Locality and LLM Efficiency

Semantic locality is a useful GraphGraph design principle, but it needs a
precise boundary:

> A packet whose evidence stays close to the query's entities, facets, and
> subsystems can reduce prompt length and distractors. Whether it improves an
> LLM's answer is an empirical question. It does not reduce the FLOP count of a
> standard dense Transformer at a fixed token length.

The metaphor that a cat-related prompt keeps "cat weights active" is useful for
intuition, not a literal execution model. Model weights remain fixed during
ordinary inference. Activations, attention values, and the KV cache depend on
the current tokens, but a domain shift does not make dense attention heads skip
matrix multiplications, layers, or parameters.

## What semantic locality can and cannot claim

Let \(Q\) be the query, \(C\) the selected context, and \(Y\) the desired
response. An ideal retriever would select context that reduces:

$$
H(Y \mid C,Q)
$$

GraphGraph cannot observe \(Y\) at retrieval time and does not measure this
conditional entropy directly. Exact entity resolution, typed paths, requested
facet coverage, source proximity, and token cost are inspectable proxies.
Irrelevant context can distract models, and long-context evaluations such as
*Lost in the Middle* show that models do not use every position robustly.
Neither fact proves that every local packet lowers entropy or improves an
answer.

The standard attention operation is:

$$
\operatorname{softmax}\left(\frac{QK^\mathsf{T}}{\sqrt{d_k}}\right)V
$$

Adding tokens adds candidates to the normalization, but it does not
mechanically guarantee that attention to relevant evidence is diluted. Learned
logits can remain concentrated. "Attention dilution" is therefore a risk model
to test, not a proof derived from the denominator alone.

Physical system savings come from fewer input tokens, fewer raw file reads, and
fewer agent/tool round-trips. The latency curve depends on model architecture,
serving stack, prefix and KV caching, batching, and whether prefill or decoding
dominates. It should not be summarized as a universal quadratic saving.

## GraphGraph's LLM-near instruction set

GraphGraph translates the activation metaphor into an inspectable, low-level
context pipeline:

```text
query terms + exact paths + requested facets
    -> anchor mass
    -> typed-edge propagation
    -> evidence-constrained packet selection
    -> bounded graph IR + optional source windows
    -> semantic validation receipt
```

This is "close to the model" in the useful engineering sense:

- identifiers and paths become explicit activation seeds;
- relation types constrain which associations may propagate;
- query-class budgets bound working context;
- compact adjacency preserves topology without repeating full source;
- bounded source windows supply exact syntax only where selected;
- receipts tell the caller whether the packet supports its own claims.

The graph is not a simulation of hidden neural weights. It is an external,
deterministic context compiler whose output is shaped for transformer input.

## Constants versus dynamic rules

Constants are appropriate for protocol invariants, safety ceilings, and
reproducible defaults. They are weak when they stand in for repository shape,
query ambiguity, graph density, or observed evidence.

A useful design objective for packet \(P\) is:

$$
\max_{P \subseteq G}
  \operatorname{coverage}(P,Q)
  + \operatorname{typedSupport}(P,Q)
  - \lambda_t\operatorname{tokens}(P)
  - \lambda_x\operatorname{unsupportedCrossings}(P)
$$

GraphGraph does not optimize this as one learned function or estimate mutual
information. The production implementation realizes pieces of the objective
through query routing, information-gain-regularized node budgets, exact and
changed-path anchors, typed traversal strengths, relation-shaped edge quotas,
connected selection, and receipt validation.

The practical rule is:

- keep stable constants for schema tags, hard safety limits, and fallback
  behavior;
- derive budgets and scores from query class, graph size and density, anchor
  confidence, facet coverage, and measured token cost;
- saturate heuristics rather than letting degree or centrality grow without
  bound;
- require benchmarks before replacing a simple constant with a more complex
  adaptive mechanism.

A formula is not automatically more optimal. It can add parameters, unstable
feedback, and benchmark overfitting. Dynamic behavior should earn its
complexity with a measurable gain.

## Ripgrep concepts translated for LLM context retrieval

The useful transfer is staged execution, not copying a text searcher's
implementation:

| Ripgrep mechanism | GraphGraph translation |
| --- | --- |
| Required-literal prefilter | Resolve exact symbols, paths, and facets first |
| Full regex verification around candidates | Verify candidates with typed edges and bounded source |
| Input-shaped buffer choice | Choose cached graph, changed-path splice, or live source window |
| Reused matchers and worker buffers | Reuse graph, lexical/topology indexes, and packet caches |
| Early match termination | Stop when requested facets have attributed evidence |
| Regex-size bounds | Bound nodes, edges, hops, source lines, and tokens |
| Ignore rules before search | Exclude generated, vendored, secret-bearing, and irrelevant artifacts |

The round-three implementation adds two concrete pieces of this staged path:

- `source_snippets` reuses the process-local graph cache;
- MCP `query_context` can fuse bounded, current source windows with its graph
  packet, avoiding a second tool call. Whole-response caching is bypassed for
  fused raw source so a file edit cannot return stale lines.

## What the evidence currently supports

On the 48-task Locus deterministic evidence-containment suite:

- the uniform 120-node route averaged **843.1 tokens**;
- adaptive planning averaged **690.0 tokens**, an **18.1% reduction**;
- selected packets contained the benchmark's required evidence on all 48
  tasks and were **5.01%** above the **657.1-token** oracle
  evidence-containment floor.

These results validate packet size and deterministic evidence containment.
They do not establish code-generation correctness, semantic answer quality, or
generalization to an independently sampled task population. Frozen live-model
scoring remains outstanding.

Likewise, a July 18 topology-free experimental branch measured about
**97.7 ms** warm on the 5,026-node self-graph versus about **93.6 ms** for the
existing path. This was not a controlled flat-file-search benchmark, and the
small difference does not establish a causal topology speedup. The branch
delivered no demonstrated advantage and was removed. The useful result is the
rejection decision, not the 4.2% ratio.

`gg_lex` is also still a hypothesis. Self-describing lexical handles may be
easier for a model to follow than numeric indirection, but they cost roughly
10–13% more tokens in current serialization measurements. Live answer scoring
is required before calling that a reasoning win or making it the default.

## Adoption bar for small repositories

For an agent to prefer GraphGraph even on a small project, the common path must:

1. start or connect with near-zero ceremony;
2. answer exact symbol/path lookups as cheaply as text search;
3. update only changed files;
4. return topology and just enough exact source in one bounded call;
5. expose a receipt that fails closed when evidence is missing;
6. avoid paying semantic or graph machinery when the exact fast path suffices.

The target is not "always use the graph." It is one tool that selects the
cheapest trustworthy path—exact lookup, graph neighborhood, or bounded
source—without forcing the agent to orchestrate several lower-level commands.

## Primary references

- Vaswani et al., *Attention Is All You Need* (2017).
- Tishby, Pereira, and Bialek, *The Information Bottleneck Method* (1999).
- Liu et al., *Lost in the Middle: How Language Models Use Long Contexts*,
  arXiv:2307.03172.
- Jiang et al., *LLMLingua: Compressing Prompts for Accelerated Inference of
  Large Language Models*, arXiv:2310.05736.
- Wu et al., *Repoformer: Selective Retrieval for Repository-Level Code
  Completion*, arXiv:2403.10059.
- Zhang et al., *RepoCoder: Repository-Level Code Completion Through Iterative
  Retrieval and Generation*, arXiv:2303.12570.
- Ye et al., *Differential Transformer*, arXiv:2410.05258.
