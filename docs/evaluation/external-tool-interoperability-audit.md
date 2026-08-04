# Graph-tool usage audit

Empirical comparison of GraphGraph with the graph-oriented tools available in
`C:\Users\dcarn\aiprojects\resources`. The test was the recurring coding-agent
loop, not “can the tool build a graph?”:

1. enter an unfamiliar project;
2. locate the implementation behind a natural-language task;
3. inspect callers/path/impact;
4. edit or delete files;
5. refresh the knowledge state;
6. immediately reason about what to do next.

Measurements below are local single-machine observations from 2026-07-14. They
are directional, not a cross-platform performance ranking; process startup,
graph size, extraction depth, and warm caches differ.

## What the usage test found

| Tool | Strongest observed behavior | Recurring-loop friction | GraphGraph decision |
| --- | --- | --- | --- |
| GraphGraph | Exact symbol/caller/path packets, compact topology, no service or API key, targeted file splices | Previously required update/remove/query calls and explicit changed paths | Closed: one `query_context` can Git-sync, splice, persist, and query the resulting in-memory graph |
| Graphify | Useful single-node `explain`; persistent concepts/communities; global multi-repo registry | `update .` rescanned 221 files in about 20s and emitted thousands of warnings; the tested caller/path queries missed known direct relations | Absorb explainability and eventual multi-repo identity, not its large semantic graph or human-facing visualization |
| code-review-graph | Broad tool surface: flows, communities, impact, change review, refactor preview, multi-repo registry | Initial build about 6.9s; an ambiguous caller lookup needed a qualified-name follow-up; change-risk/test-gap output included false positives | Absorb topology-derived flows/change evidence and continuation hints, not opaque risk scores or mutation/refactor authority |
| Graphiti | Temporal episodes and `as_of` knowledge are first-class | Requires a graph database plus LLM/embedding services; not a source-topology loop out of the box | Keep temporal validity as optional graph facts; do not put a database or model call on the hot path |
| ContextSniper | Semantic output filtering and exact replacement edits can reduce downstream context | Bootstrap/runtime/embedding dependencies; operates around tool output more than source topology | Add packet continuation/filtering contracts where measured; keep editing in the agent/tool layer |
| KGCompass | Fixed-budget, issue-to-function repair context and path mining | Research artifact rather than a general installed project service | Use as benchmark inspiration for repair-context recall under a hard budget |
| GraphRAG | Corpus-wide semantic/global questions | Index/query require configuration and model calls; weak fit for a per-edit source loop | Optional fallback for document corpora, never a required source-code path |

On the same source question, GraphGraph anchored the actual
`render_query_context`, `build_query_context`, `retrieve_context`, and updater
symbols in one call. Graphify's query was fast (about 1.4s versus GraphGraph's
roughly 1.8s cold CLI call) but mostly returned benchmark/document nodes;
Graphify `affected render_query_context` returned no affected nodes and its
path query missed a known direct call. code-review-graph found callers after a
qualified-name follow-up, but returned fewer locations and no line numbers.
This is why latency alone is not the objective: unusable evidence has zero
value.

The current fused benchmark is less ambiguous. On the same 500-file synthetic
graph, separate update + remove + query had a 286.2 ms median; one fused
refresh/query took 167.3 ms, a 1.71x local orchestration improvement before
counting the two eliminated MCP round trips.

## The low-level contract

MCP, CLI, and a skill are transports over one instruction set. The hot path
should remain:

```text
SYNC(delta?) -> ANCHOR(intent) -> EXPAND(policy,budget) -> PACK(format)
```

- `SYNC`: trust an explicit changed/deleted set, or ask Git for candidates;
  compare candidate hashes with the manifest; splice only stale paths.
- `ANCHOR`: map task language and exact identifiers to stable graph nodes.
- `EXPAND`: traverse typed, confidence-weighted relations locally.
- `PACK`: encode the smallest connected evidence set that preserves the answer.

`query_context` now composes all four. Explicit `changed_paths` and
`deleted_paths` are the cheapest authoritative form. `sync: "git"` is the
zero-bookkeeping form. A repeated Git sync with no new edits performs no graph
write and no re-extraction.

The sync cost is now approximately

```text
O(manifest path strings checked against ignore rules
  + bytes of Git-changed candidates hashed
  + changed-file extraction
  + graph splice/serialization)
```

It does not walk or hash every repository file. The manifest ignore check is a
single batched Git subprocess and also removes content indexed before a new
ignore rule, which closed the `docs/bugs/` stale-content leak found in this
audit.

## Context-selection math

“Full context” means sufficient evidence across the active change boundary,
not every dirty symbol. Before this audit, broad session queries could add all
nodes owned by dirty files as PageRank/traversal seeds. That creates redundant
personalization mass and lets one large file consume the start budget.

The implemented session selector chooses at most one node per dirty path. For
candidate node `v` in path `p`:

```text
u(v,p) = 4 lexical_cosine(query,v)
       + 0.65 log(1 + degree(v)) / log(1 + max_degree)
       + kind_prior(v)
       + 0.35 log(1 + change_count(p)) / log(1 + max_change)

K = min(4, ceil(log2(number_of_candidate_paths + 1)))
```

The lexical term dominates when the task names a changed symbol. Degree and
change mass provide a smooth generic “what next?” prior. The path constraint
is a cheap coverage objective; the logarithmic `K` prevents a large worktree
from linearly increasing packet cost. Existing query anchors suppress a dirty
representative from the same path.

The next packet-level improvement should generalize this as budgeted marginal
coverage. For packet set `S` and candidate `v`, select by

```text
argmax_v  [query_evidence(v)
           + uncovered_relation_families(v,S)
           + change_boundary_coverage(v,S)
           + connectivity_gain(v,S)
           - redundancy(v,S)] / token_cost(v)
```

subject to the packet token budget. This is preferable to a single “risk”
number: the agent receives callers, impacted tests, uncovered boundaries, and
their relations as inspectable evidence.

## Research basis

- Acar's self-adjusting computation work uses a dynamic dependence graph and
  change propagation with the key correctness target that the adjusted result
  matches recomputation from scratch. GraphGraph should adopt that equivalence
  as the incremental-sync oracle, while using source-file ownership as its
  cheaper invalidation unit. [Acar, *Self-Adjusting Computation*](https://www.cs.cmu.edu/~rwh/students/acar.pdf)
- Andersen, Chung, and Lang show that local personalized PageRank can have work
  governed by the nearby partition rather than the full graph. That matches
  GraphGraph's seeded local retrieval and argues against global community work
  on every query. [*Local Graph Partitioning using PageRank Vectors*](https://snap.stanford.edu/class/cs224w-readings/andersen06localgraph.pdf)
- Budgeted maximum coverage formalizes selecting weighted evidence under a
  cost cap and is NP-hard, motivating a marginal-utility-per-token heuristic
  instead of pretending an exact packet optimizer is cheap. [Khuller, Moss,
  and Naor, *The Budgeted Maximum Coverage Problem*](https://doi.org/10.1016/S0020-0190(99)00031-9)
- Change-impact research documents the tradeoff GraphGraph must expose rather
  than hide: call-graph closure is cheap but imprecise; static slicing is safer
  but can be too large; execution-profile impact is more precise for observed
  behavior but not conservative. [Law and Rothermel, *Whole Program
  Path-Based Dynamic Impact Analysis*](https://doi.org/10.1109/ICSE.2003.1201210)

## Capability roadmap

Ordered by useful evidence divided by token cost, latency, and stale-state risk:

1. **Done: atomic fresh query.** Explicit or Git-derived delta, one validated
   splice, direct in-memory query, compact refresh receipt.
2. **Done: bounded worktree coverage.** Query-aware, one-per-path dirty seeds
   with logarithmic fanout.
3. **Next: structural change packet.** Changed definitions, strongest reverse
   impact frontier, relevant tests, and uncovered test boundary. Report facts,
   not an uncalibrated risk scalar.
4. **Then: continuation receipt.** State whether the packet saturated its
   evidence/token budget and provide the cheapest next query only when useful.
5. **Then: multi-repo identity.** Registry plus cross-repo symbol/package edges;
   keep each repository's local graph independently refreshable.
6. **Optional: temporal facts.** `valid_from`/`valid_to` and `as_of` traversal
   for decisions and incidents, without requiring an external graph database.
7. **Benchmark-only until proven:** embeddings, automatic wiki generation,
   visualization, refactor application, global community detection, and model
   calls in indexing. None belongs in the default agent hot path without a
   measured answerability gain that exceeds its latency/token cost.
