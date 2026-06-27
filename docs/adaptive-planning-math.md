# Adaptive Planning Math

This page consolidates the rough `mathpush.md` and `peacewise.md` notes into
the current production-oriented model.

The core idea is that graphgraph is not trying to output a graph. It is trying
to choose the cheapest graph-derived context packet that still contains the
evidence an AI agent needs.

## Decision Variables

For a query `Q`, the planner chooses:

```text
plan = (h, d, n, p)
```

Where:

- `h` is hop depth.
- `d` is traversal direction: `out`, `in`, or `both`.
- `n` is node budget.
- `p` is packet format.

The runtime implementation currently separates this into:

- traversal planning in `src/graphgraph/planning/`
- retrieval execution in `src/graphgraph/retrieval/`
- final packet composition in `src/graphgraph/services/context.py`
- packet rendering in `src/graphgraph/packets.py`

## Objective

The conceptual objective is:

```text
minimize:
  alpha * token_cost(h, d, n, p)
+ beta  * missing_evidence_risk(h, d, n)
+ gamma * irrelevant_context_noise(h, d, n)
+ delta * model_interpretability_risk(p, M)
+ eps   * absence_leak(Q, h, d, p)
+ zeta  * latency_cost(h, d, n)
```

Subject to:

```text
packet_validate(p, Gq) == pass
negative_query => edge_count(Gq) == 0
token_cost <= budget
```

`M` is the model/profile. Today this is not a learned profile; the default is
driven by deterministic benchmarks and packet validation.

## Current Measured Policy

The current production policy is intentionally simple:

```text
negative_query:     h=0, d=both, p=semantic_arrow, n=1
direct_lookup:      h=1, d=out,  p=gg_max,         n=80
reverse_lookup:     h=1, d=in,   p=gg_max,         n=80
subsystem_summary:  h=1, d=both, p=gg_max,         n=120
blast_radius:       h=2, d=both, p=gg_max,         n=120
multi_hop_path:     h=2, d=both, p=gg_max,         n=80
docs/install usage: h=1, d=both, p=doc_summary,    n=12
```

This is based on the current real-project evidence-containment benchmark:

| Budget policy | Answerable | Avg tokens |
| --- | ---: | ---: |
| production default | 48/48 | 580.5 |
| uniform 120 | 48/48 | 710.3 |
| unbounded | 48/48 | 6401.1 |

The production default is about `2.918%` above the cheapest answerable frontier
in the deterministic oracle.

## Packet Gate

The packet choice collapsed empirically to:

```text
if edge_count == 0:
    semantic_arrow
else:
    gg_max
```

Synthetic protocol sweeps suggested that a softer threshold such as
`semantic_arrow <= 3 edges` might be worth live testing. Real-project packet
balance was stricter: `gg_max` won every non-empty retrieved subgraph, and
`semantic_arrow` only won for zero-edge packets.

That means the current runtime gate is close to a step function, while the
research form can still be written as a smooth activation:

```text
p(readable) = sigmoid(k * (t - edge_count))
```

Where current real-project data implies `t = 0`.

## Subgraph Statistic Gates

The planner also computes descriptive statistics on the retrieved subgraph:

```text
density = edge_count / node_count
factful_node_ratio = nodes_with_summary_or_facts / node_count
relation_entropy = distinct_relation_types / edge_count
weak_edge_ratio = weak_edges / edge_count
```

These are now weight-bearing in two conservative places:

```text
if weak_edge_ratio >= 0.75
and edge_count >= 2 * weak_edge_limit:
    tighten weak_edge_limit

if query_class == subsystem_summary
and factful_node_ratio >= 0.5
and weak_edge_ratio < 0.75
and gg_max_hybrid premium <= max(48 tokens, 15%):
    p = gg_max_hybrid
```

The first rule is a noise gate for repeated weak relations such as
`references`, `links`, `mentions`, and `discusses`. Low relation diversity
(`relation_entropy <= 0.2`) tightens more aggressively because repeated weak
edges are usually redundant.

The second rule is a bounded evidence-inline escape hatch. It does not replace
the measured `gg_max` default for ordinary structural packets; it only promotes
fact-rich subsystem summaries when the estimated token premium is small.

## Hop Activation

The long-term traversal model is spreading activation:

```text
a_0(v) = 1 if v is an anchor else 0
a_{t+1}(v) = decay * sum_u a_t(u) * edge_weight(u,v) * relation_strength(u,v)
```

Continue expansion while:

```text
marginal_evidence_gain / marginal_token_cost >= threshold
```

Current real-project hop-frontier results say this should not be the default
yet. Hop 1 is the major gain, hop 2 is still useful for path/blast-radius
queries, hop 3 is marginal, and hop 4+ is dead under the bounded real-project
run.

## Lagrangian Node-Budget View

For the node-budget subproblem, use a differentiable evidence proxy:

```text
A_hat(n) = 1 - exp(-lambda * n)
```

With hard token and latency constraints:

```text
minimize: 1 - A_hat(n)

subject to:
  tau_node * n <= T_max
  lambda_node * n <= C_max
  n >= 1
```

The Lagrangian is:

```text
L(n, mu) =
  exp(-lambda * n)
+ mu_1 * (tau_node * n - T_max)
+ mu_2 * (lambda_node * n - C_max)
+ mu_3 * (1 - n)
```

The stationarity condition is:

```text
-lambda * exp(-lambda * n*)
+ mu_1 * tau_node
+ mu_2 * lambda_node
- mu_3
= 0
```

The useful engineering interpretation is the shadow price of context. When the
token constraint binds, `mu_1` estimates how much evidence recall would improve
if the token budget increased.

This is a research framing, not the current runtime. The current runtime uses
measured per-query-class budgets because they are simple, deterministic, and
already pass the evidence-containment oracle.

## Production Gates

Before promoting more adaptive behavior, each candidate policy should pass:

- packet validation
- deterministic evidence containment
- prompt preflight coverage
- live model parsing
- live node/edge recall
- hallucinated node/edge checks
- latency and token budget checks

The largest unproven gate remains live model-answer scoring. The frozen prompt
set exists at:

```text
benchmarks/context_graph/out/protocol/model_reasoning_prompts.jsonl
```
