# Adaptive Packet Planning: From Rough Piecewise Idea to Architecture Plan

This note supersedes the earlier rough formula. The old version was useful
because it named the right shape: graphgraph should not have one universal
context packet. It should route each query through a measured decision function.

The exact branches and thresholds should not be treated as canon. The threshold
might be 3 edges, 30 edges, a density ratio, a fact-coverage score, or a learned
Pareto policy. The important architecture is that packet choice becomes an
explicit optimization problem over real retrieval features and answer quality.

## Research Grounding

The academic direction supports a graph-first adaptive planner:

- Retrieval-augmented generation is valuable because external evidence reduces
  reliance on parametric memory, but retrieval quality controls answer quality
  (Lewis et al., 2020, https://arxiv.org/abs/2005.11401).
- GraphRAG-style systems show that graph structure helps when answers need
  relationships, summaries across communities, or global/local context blending
  rather than isolated chunks (Edge et al., 2024, https://arxiv.org/abs/2404.16130).
- Long-context models still do not reliably use all supplied evidence; "Lost in
  the Middle" makes compression and evidence placement part of the accuracy
  problem, not just the cost problem (Liu et al., 2023, https://arxiv.org/abs/2307.03172).
- Therefore graphgraph should optimize for enough topology plus enough grounded
  text, not simply "shortest packet" or "most readable packet."

## Current State In This Repo

Current implementation already has most of the raw materials:

- `src/graphgraph/planner.py` chooses `hops` and packet format by query class.
- `src/graphgraph/packets.py` supports `sql`, `semantic_arrow`, `gg_max`,
  `gg_max_hybrid`, `doc_summary`, `svo`, and tensor/CSR-like arrays.
- `src/graphgraph/retrieval.py` chooses anchors, node budgets, weak-edge caps,
  runtime policy context, and decision trace enrichment.
- `src/graphgraph/cache.py` keys cached packets by starts, query class, hops,
  and packet choice.
- Benchmarks already cover format overhead, packet round-trip validity,
  source-route precision/recall, density, prompt preflight, and min-max analysis.

The missing piece is that `choose_packet()` only sees `query_class` and query
text. It does not see the retrieved subgraph's size, density, relation mix,
fact coverage, confidence/provenance profile, or available token budget. That is
where the rough piecewise idea should become real architecture.

## What Current Artifacts Say

Saved benchmark artifacts give us several concrete constraints:

- `benchmarks/context_graph/out/protocol/packet_roundtrip_results.md` reports
  `312/312` generated packets mechanically round-trip.
- `benchmarks/context_graph/out/protocol/prompt_preflight.md` reports 144 frozen
  live-model prompts, with average prompt tokens:
  - `lowlevel_schema` 1-hop: `209.7`
  - `lowlevel_schema` 2-hop: `311.6`
  - `sql_schema` 1-hop: `249.8`
  - `sql_schema` 2-hop: `442.5`
  - `hybrid_schema` 1-hop: `507.2`
  - `hybrid_schema` 2-hop: `1082.4`
- `benchmarks/context_graph/out/density/density_summary.md` shows `gg_max`
  beating verbose graph packets on real project graphs:
  - `graphgraph/self`: `860` mean tokens vs `1819` baseline, `-53%`
  - `contextminer/self`: `613` mean tokens vs `1636` baseline, `-61%`
  - `locus/native`: `597` mean tokens vs `1569` baseline, `-62%`
- `benchmarks/context_graph/out/protocol/model_reasoning_summary.md` says live
  model execution is still skipped. The prompt set exists, but answer scoring
  has not been proven yet.
- `benchmarks/context_graph/out/protocol/adaptive_threshold_sweep.md` tests the
  rough "maybe 3 edges" idea as a real min-max proxy. On existing protocol rows,
  `semantic_arrow` for `retrieved_edges <= 3`, else `gg_max`, preserves proxy
  quality at `1.0` with only a `0.604%` token premium over all-`gg_max`, while
  using readable packets in 7 of 24 task/corpus cases. The best token result was
  threshold `2`, but threshold `3` is a reasonable readability starting point.
- `benchmarks/context_graph/out/real_projects/real_project_packet_balance.md`
  is the stricter result: on bounded real projects, `gg_max` wins every
  non-empty subgraph; `semantic_arrow` only wins when `edge_count == 0`.
- `benchmarks/context_graph/out/real_projects/adaptive_hop_policy.md` rejects
  uncapped nth-hop traversal as a production default. It adds about `324`
  tokens on average without answer labels. The safer `capped_to_fixed` variant
  saves nothing at thresholds `0.5` through `5`; at threshold `10` it saves
  about `100` tokens but drops about `10` edges and `10` nodes on average.
- `benchmarks/context_graph/out/real_projects/token_proxy_calibration.md`
  checks the runtime token proxy against rendered packets on real-project
  subgraphs, including bundled anchors. The proxy underestimates absolute token
  counts, but packet-winner agreement is `144/144`, and the specific
  `semantic_arrow` vs `gg_max` refinement decision also agrees `144/144`.
- `benchmarks/context_graph/out/real_projects/real_project_answerability_limit.md`
  generates deterministic answer keys from real graph edges. After adding
  directional traversal and measured per-class node budgets, the production
  default is answerable on `48/48` tasks at `586.0` average tokens. Uniform
  `n=120` also answers `48/48`, but costs `706.6` average tokens; unbounded
  expansion costs `6459.0` average tokens.

Current verification has run outside the broken sandbox process launcher:

- `python -m unittest discover -s tests`: `89` tests passed, `2` skipped.
- Planner smoke: `direct_lookup -> 1hop gg_max`.
- Planner smoke: `negative_query -> 0hop semantic_arrow`.
- Negative-query CLI smoke renders anchors with empty `@edges`.

## New Objective Function

Instead of:

```text
if edge_count <= 30 then semantic_arrow else gg_max_hybrid
```

use a measurable selector:

```text
F(Gq, Q, B, M) -> (hops, direction, packet, node_budget, edge_budget, fact_policy)
```

Where:

- `Gq` is the retrieved candidate subgraph.
- `Q` is the query class and query text.
- `B` is the token budget and latency/cost target.
- `M` is model/profile information: whether the target model reliably answers
  from numeric graph packets, SQL rows, or hybrid text.

The selected packet must satisfy:

```text
minimize tokens + latency + irrelevant_context
subject to:
  node_recall >= query_class_gate
  edge_recall >= query_class_gate
  answer_correctness >= live_model_gate
  hallucinated_edges == 0 for structural queries
  packet_validate == pass
```

## Activation-Function View

The production planner can remain piecewise, but the research model should look
more like an activation function. Instead of asking only "which side of the
threshold is this on?", compute a packet preference score:

```text
score(packet | Gq, Q, M) =
  w_tokens * normalized_token_cost(packet)
+ w_recall * recall_risk(packet, Q)
+ w_noise  * irrelevant_context(packet)
+ w_interp * model_interpretability_risk(packet, M)
+ w_absent * absence_query_penalty(packet, Q)
```

Then choose:

```text
packet* = argmin score(packet | Gq, Q, M)
```

The "activation" can be a sigmoid over edge count or density:

```text
p(readable) = sigmoid(k * (t - edge_count))
```

Where:

- `t` is the learned transition point.
- `k` is sharpness: high `k` behaves like a hard piecewise cutoff.
- low `k` gives a soft gray zone where live model-comprehension evidence can
  override token cost.

Current evidence suggests two different curves:

- Synthetic protocol proxy: `semantic_arrow <= 3 edges, else gg_max` is cheap
  enough to test live, costing only about `0.604%` over all-`gg_max`.
- Real-project packet floor: the curve is much sharper; `semantic_arrow` only
  wins at `edge_count == 0`, and `gg_max` dominates every non-empty subgraph in
  the bounded real-project run.
- Runtime now has a lightweight `SubgraphStats` layer in `planner.py` that
  computes post-retrieval node/edge counts, density, weak-edge ratio, fact
  coverage, relation variety, and fast token proxies before packet refinement.

That means the likely production activation is close to a step function:

```text
if edge_count == 0: semantic_arrow
else: gg_max
```

But the softer activation form is still useful for future model-specific
profiles. If a model fails to reason from numeric `gg_max` on low-edge graphs,
`w_interp` can bend the curve toward `semantic_arrow` without rewriting the
planner.

The token proxy is calibrated for routing, not reporting. On the current
real-project calibration, it underestimates absolute token counts by roughly:

| Packet | Avg actual tokens | Avg proxy tokens | Avg relative error |
| --- | ---: | ---: | ---: |
| gg_max | 438.3 | 385.6 | -17.2% |
| semantic_arrow | 791.2 | 592.6 | -29.0% |
| sql | 1388.8 | 795.6 | -53.3% |
| lowlevel | 695.0 | 530.0 | -36.4% |
| gg_max_hybrid | 690.7 | 485.2 | -36.3% |

That is acceptable only because current runtime refinement depends on rank, not
exact token budgeting. Exact token reports should keep using rendered packet
counts in benchmarks.

## Current Continuous Objective

The current mathematical model is:

```text
plan = (h, d, n, p)

minimize:
  alpha * token_cost(h, d, n, p)
+ beta  * missing_evidence_risk(h, d, n)
+ gamma * irrelevant_context_noise(h, d, n)
+ delta * model_interpretability_risk(p, M)
+ eps   * absence_leak(Q, h, d, p)
+ zeta  * latency_cost(h, d, n)

subject to:
  packet_validate(p, Gq) == pass
  negative_query => edge_count(Gq) == 0
```

Where:

- `h` is hop depth.
- `d` is traversal direction: `out`, `in`, or `both`.
- `n` is node budget.
- `p` is packet format.
- `M` is the model/profile.

This is a continuous objective with discrete regimes. The current measured
switching policy is:

```text
negative_query:     h=0, d=both, p=semantic_arrow
direct_lookup:      h=1, d=out,  p=gg_max
reverse_lookup:     h=1, d=in,   p=gg_max
subsystem_summary:  h=1, d=both, p=gg_max
blast_radius:       h=2, d=both, p=gg_max
multi_hop_path:     h=2, d=both, p=gg_max
docs/install usage: h=1, d=both, p=doc_summary
```

The measured default node budgets are:

```text
direct_lookup:      n=80
reverse_lookup:     n=80
multi_hop_path:     n=80
negative_query:     n=1
subsystem_summary:  n=120
blast_radius:       n=120
docs/install usage: n=12
```

`answerability(n)` is currently measured by a deterministic
evidence-containment oracle, not by an LLM judge. The oracle builds expected
nodes/edges from real graph topology and checks whether a candidate plan
contains that evidence. It is cheap enough for benchmark sweeps, but not a
runtime scoring loop.

## N-Hop / Spreading Activation View

`multi_hop_path` is currently planned as 2-hop by default, but that is a policy
choice, not a graphgraph limitation. The underlying graph expansion already
accepts arbitrary `hops=n`, and the CLI can override defaults with `--hops`.

The more general math is closer to spreading activation than a fixed BFS depth:

```text
a_0(v) = 1 if v is an anchor else 0
a_{t+1}(v) = decay * sum_u a_t(u) * edge_weight(u,v) * relation_strength(u,v)
```

Then retrieve:

```text
Gq = top nodes/edges where activation(v) >= epsilon
```

This is the "electron jumping through relational nodes" version: context energy
propagates through the graph, but every jump loses charge unless the edge is
strong, trusted, and relevant. Instead of asking "is this a 2-hop task or a
3-hop task?", the planner asks whether the next hop adds enough useful evidence
to justify its token cost.

The stopping rule should be min-max:

```text
continue while marginal_recall_gain / marginal_token_cost >= threshold
stop when activation mass, confidence, or token budget falls below the gate
```

Candidate production rule:

- `direct_lookup`: start at 1 outgoing hop.
- `reverse_lookup`: start at 1 incoming hop.
- `blast_radius`, `multi_hop_path`: start at 2 hops.
- Escalate to nth-hop only when the frontier still has high activation and the
  query asks for chains, transitive impact, reachability, or global coupling.
- Use relation-specific decay so weak `references` edges die quickly while
  `calls`, `imports`, `contains`, `implements`, and policy edges carry farther.
- Cap by token budget and choose `gg_max` for any non-empty structural packet.

This would turn the planner from a fixed hop table into:

```text
TraversalPlan = argmax evidence_gain(hop_frontier) - token_cost(hop_frontier)
PacketPlan    = argmin packet_score(rendered_subgraph)
```

That is probably the right long-term architecture: hop depth becomes a learned
activation cutoff, packet format becomes the final compression layer.

The first real-project hop-frontier run gives a concrete starting point:

| Hops | Avg nodes | Avg edges | Avg tokens | New edges | New tokens | Marginal edges / 100 tokens |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1.0 | 0.0 | 12.8 | 0.0 | 12.8 | 0.000 |
| 1 | 70.7 | 69.7 | 521.6 | 69.7 | 508.9 | 7.000 |
| 2 | 79.8 | 99.8 | 707.5 | 30.1 | 185.9 | 2.089 |
| 3 | 80.5 | 103.7 | 728.4 | 3.9 | 20.9 | 1.175 |
| 4 | 80.5 | 103.7 | 728.4 | 0.0 | 0.0 | 0.000 |
| 5 | 80.5 | 103.7 | 728.4 | 0.0 | 0.0 | 0.000 |

Read: hop 1 is the major activation jump, hop 2 still pays, hop 3 is marginal,
and hop 4+ is dead under the current bounded real-project settings. A production
n-hop planner should therefore start from the current query-class defaults. It
should not allow uncapped escalation in production without answer-recall labels.

The follow-up adaptive-hop benchmark sharpened this:

| Policy | Threshold | Avg fixed tokens | Avg adaptive tokens | Token delta | Edge delta | Node delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| uncapped | 1 | 963.4 | 1287.1 | 323.6 | 58.2 | 12.7 |
| capped_to_fixed | 1 | 963.4 | 963.4 | 0.0 | 0.0 | 0.0 |
| capped_to_fixed | 10 | 963.4 | 863.9 | -99.6 | -9.9 | -9.9 |

Read: the "electron jump" idea is mathematically useful as a research model,
but the current operational optimum is still the fixed hop budget: 1-hop for
direct/reverse/subsystem, 2-hop for blast/path, 0-hop for negative queries.
Activation should remain a benchmarked experiment until live answer scoring can
prove that the lost edges at stricter thresholds are irrelevant.

The real-project answerability benchmark gives the current `answerability(n)`
shape:

| Budget | Answerable | Avg tokens |
| ---: | ---: | ---: |
| production default | 48/48 | 586.0 |
| 80 | 33/48 | 484.6 |
| 120 | 48/48 | 706.6 |
| 160 | 48/48 | 940.9 |
| 240 | 48/48 | 1382.3 |
| unbounded | 48/48 | 6459.0 |

By query class:

- `direct_lookup`: `n=80` is answerable on `8/8`, average `468.6` tokens.
- `reverse_lookup`: `n=80` is answerable on `8/8`, average `632.6` tokens
  after incoming-only traversal.
- `multi_hop_path`: `n=80` is answerable on `8/8`, average `618.9` tokens
  when both path endpoints are anchored.
- `subsystem_summary`: `n=120` is the first tested budget with `8/8`
  answerability.
- `blast_radius`: `n=120` is the first tested budget with `8/8`
  answerability.
- `negative_query`: `n` is irrelevant under the current `0`-hop rule.

This is the current best production balance: `48/48` answerable and only
`2.867%` above the cheapest answerable frontier in the deterministic oracle,
while avoiding the large unbounded-expansion penalty.

## Candidate Features

The planner should receive a `SubgraphStats` object computed after retrieval and
before rendering:

```python
@dataclass(frozen=True)
class SubgraphStats:
    nodes: int
    edges: int
    density: float              # edges / max(nodes, 1)
    relation_entropy: float
    weak_edge_ratio: float
    factful_node_ratio: float
    avg_fact_tokens: float
    max_degree: int
    provenance_min_confidence: float
    estimated_tokens_by_packet: dict[str, int]
```

This lets the system learn whether the real boundary is edge count, density,
fact coverage, relation variety, or model-dependent interpretability.

## Proposed Piecewise Planner

Treat this as a starting policy, not a fixed truth:

```python
def choose_packet_v2(query, stats, budget, profile):
    if query.needs_document_answer:
        return doc_summary_or_hybrid(stats, budget)

    if query.query_class in {"multi_hop_path", "blast_radius"}:
        if stats.edges == 0:
            return "doc_summary" if stats.factful_node_ratio else "gg_max"
        if profile.numeric_graph_reasoning_passes:
            return "gg_max"
        return "sql" if stats.edges <= profile.sql_edge_limit else "gg_max_hybrid"

    if query.query_class in {"direct_lookup", "reverse_lookup", "negative_query"}:
        if stats.edges <= profile.readable_edge_limit and budget.has_room:
            return "sql"
        return "gg_max"

    if stats.factful_node_ratio >= profile.factful_threshold:
        return "gg_max_hybrid"

    return "gg_max"
```

The decisive change is architectural: render choice happens after retrieval,
when graph shape is known. Today it happens before expansion.

## Rearchitecture Plan

1. Split planning into two phases:
   - `TraversalPlan`: query class -> anchor limit, hops, direction, max nodes,
     weak-edge cap.
   - `PacketPlan`: retrieved subgraph stats -> renderer, fact policy, cache key.

2. Add `SubgraphStats`:
   - Compute it in `retrieve_context()` or immediately after expansion.
   - Include token estimates for each candidate packet using the same tokenizer
     as benchmarks when available.

3. Replace static `choose_packet()` with a compatibility wrapper:
   - Keep the current API for CLI/MCP stability.
   - Add `choose_packet_for_subgraph(query, stats, profile)`.
   - Make `cmd_query`, `cmd_render`, and `cmd_final` use the new path after
     retrieval/expansion.

4. Make thresholds data-backed:
   - Emit CSV rows with `query_class`, graph stats, packet, tokens, recall,
     parse pass, and live answer score.
   - Fit simple threshold tables first. Do not jump to ML until static tables
     fail.

5. Add live answer gates:
   - Run the frozen `model_reasoning_prompts.jsonl`.
   - Score node recall, edge recall, hallucinated nodes/edges, and answer
     correctness.
   - Promote `gg_max` only for query classes where live reasoning passes.

6. Update cache keys:
   - Include planner version, stats bucket, renderer, fact policy, and model
     profile.
   - Keep stable-skeleton cache separate from query packet cache.

7. Preserve escape hatches:
   - CLI `--packet` should force a renderer.
   - CLI `--hops` should force traversal radius.
   - Benchmarks should test forced and adaptive modes separately.

## Immediate Implementation Tasks

1. Add `GraphPacketProfile` if/when model-specific reasoning profiles are
   introduced. `SubgraphStats` already exists in `src/graphgraph/planner.py`.
2. Keep the current fast token proxy for runtime planning; use full rendering
   token counts in benchmarks, not hot-path packet selection.
3. Keep `choose_packet_for_subgraph()` as the post-retrieval packet gate.
4. Expand unit tests only where live answer scoring or new profiles change the
   default routing.
5. Keep the threshold sweep benchmark as the packet Pareto frontier source.
   - Initial script: `benchmarks/context_graph/adaptive_threshold_sweep.py`.
   - Initial result: `semantic_arrow <= 3 edges, else gg_max` costs about
     `0.604%` more than all-`gg_max` on saved protocol rows and keeps proxy
     recall/quality at `1.0`.
6. Add a stricter mathematical-limit search.
   - Script: `benchmarks/context_graph/mathematical_limit_search.py`.
   - Result: static `gg_max` is effectively the proxy floor for positive
     structural queries. `negative_query` needs no-edge evidence rather than
     graph expansion.
7. Add real-project packet-balance testing.
   - Script: `benchmarks/context_graph/real_project_packet_balance.py`.
   - Result: `gg_max` dominates every non-empty real-project subgraph in the
     bounded run; `semantic_arrow` wins only for `edge_count == 0`.
8. Add hop-frontier testing.
   - Script: `benchmarks/context_graph/hop_frontier_benchmark.py`.
   - Result: real-project expansions show a strong hop-1 gain, a useful hop-2
     gain, marginal hop-3 gain, and no useful hop-4+ gain in the bounded run.
9. Add adaptive-hop testing.
   - Script: `benchmarks/context_graph/adaptive_hop_policy_benchmark.py`.
   - Result: uncapped activation is not production-safe; capped early stopping
     only saves tokens at a threshold that drops non-trivial topology.
10. Add token-proxy calibration.
   - Script: `benchmarks/context_graph/token_proxy_calibration.py`.
   - Result: current proxy preserves real-project packet winner rank and the
     zero-edge `semantic_arrow` vs `gg_max` decision, despite underestimating
     absolute token counts.
11. Add real-project answerability-limit testing.
   - Script: `benchmarks/context_graph/real_project_answerability_limit.py`.
   - Result: deterministic evidence-containment passes `48/48` tasks with
     measured production defaults. The default budget table is within `2.867%`
     of the cheapest answerable frontier and saves about `17%` versus uniform
     `n=120`.
12. Re-run:
   - `python -m unittest discover -s tests`
   - `python benchmarks/context_graph/run_all.py`
   - live model scoring when API keys are available

## Bottom Line

The old piecewise function was right in spirit and wrong in specificity. The
current measured production route is deliberately boring: fixed query-class hop
budgets plus post-retrieval packet refinement. The next architecture should move
graphgraph from "query-class table" to "two-stage adaptive planner": retrieve
first, measure the subgraph, then render the cheapest packet that still passes
structural and live-model correctness gates. N-hop activation belongs behind
that same gate, not in the default runtime path yet.
