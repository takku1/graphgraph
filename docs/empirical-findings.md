# Empirical Findings

These are measured local benchmark results as of the current generated reports.
They are deterministic retrieval/token/round-trip findings, not final live-model
reasoning claims.

## Format Token Overhead

At 200 nodes and 265 edges:

| Format | Tokens | Prompt tokens |
| --- | ---: | ---: |
| `csr_arrays` | 3007 | 3025 |
| `low_level_adj` | 3133 | 3151 |
| `relation_coded_adj` | 3673 | 3691 |
| `sql_rows` | 3802 | 3820 |
| `markdown_compact` | 5255 | 5273 |
| `json_minified` | 6320 | 6338 |
| `json_pretty` | 12374 | 12392 |
| `graphml` | 13338 | 13356 |

Finding: compact adjacency and CSR-style packets are the token floor. GraphML
and pretty JSON are bad LLM wire formats for dense graph evidence.

## Source Route Gate

Pass gate: edge recall >= `0.95`, edge precision >= `0.99`.

| Source route | Edge recall | Edge precision | Status |
| --- | ---: | ---: | --- |
| `code_graph_direct` | 1.000 | 1.000 | PASS |
| `sqlite_rows` | 1.000 | 1.000 | PASS |
| `wiki_prose_relations` | 1.000 | 1.000 | PASS |
| `wiki_with_edges` | 1.000 | 1.000 | PASS |
| `wiki_noisy_prose` | 0.940 | 1.000 | FAIL |
| `wiki_plain_no_edges` | 0.000 | 0.000 | FAIL |

Finding: document-native routes can work if the docs compile into explicit
relations. Noisy prose stays high-precision but loses recall when relation
phrasing is unsupported.

## Adaptive Packet Choices

Measured choices for the default trusted route, `code_graph_direct`:

| Query class | Hops | Packet | Avg tokens | Node recall | Edge recall |
| --- | ---: | --- | ---: | ---: | ---: |
| `direct_lookup` | 1 | `gg_max` | 37.2 | 1.000 | 1.000 |
| `reverse_lookup` | 1 | `gg_max` | 39.2 | 1.000 | 1.000 |
| `multi_hop_path` | 2 | `gg_max` | 148.0 | 1.000 | 1.000 |
| `blast_radius` | 2 | `gg_max` | 75.5 | 1.000 | 1.000 |
| `subsystem_summary` | 1 | `gg_max` | 98.5 | 1.000 | 1.000 |
| `negative_query` | 1 | `gg_max` | 56.8 | 1.000 | 1.000 |

Finding: hop depth should be chosen per query class. `gg_max` is now the
measured structural packet default for the trusted route. Real-project packet
balance further refines this: use `semantic_arrow` for zero-edge packets and
`gg_max` for non-empty structural packets.

## Constraint Context

Project standards and LLM answer values should be scoped policies, not a global
prompt dump.

| Strategy | Avg tokens | Policy recall | Irrelevant ratio |
| --- | ---: | ---: | ---: |
| `global_all` | 281.0 | 1.000 | 0.625 |
| `scoped_compact` | 50.2 | 1.000 | 0.000 |
| `scoped_verbose` | 105.0 | 1.000 | 0.000 |

Finding: storing frontend standards, security rules, API contracts, testing
expectations, and LLM values has value when each policy has `applies_to` and
`task_tags`.

## Final Packet Composition

Composed packet = selected graph packet + optional policies.

| Policy strategy | Avg graph tokens | Avg policy tokens | Avg total tokens |
| --- | ---: | ---: | ---: |
| `none` | 75.9 | 0.0 | 75.9 |
| `scoped_compact` | 75.9 | 48.5 | 130.4 |
| `global_all_compact` | 75.9 | 134.0 | 215.9 |

Finding: scoped policies add useful constraints at modest cost. Global policy
dumps add unnecessary repeated tokens.

## Real-Project Answerability

The deterministic evidence-containment oracle over saved real-project graphs
currently reports:

| Policy | Answerable | Avg tokens |
| --- | ---: | ---: |
| production default | 48/48 | 635.4 |
| uniform `n=120` | 48/48 | 766.3 |
| unbounded | 48/48 | 7351.2 |
| cheapest answerable oracle | 48/48 | 607.7 |

Finding: the current per-query-class production default is structurally
defensible. It is `4.563%` above the cheapest answerable frontier while saving
about `17%` versus uniform `n=120`.

## Planner Fit

`benchmarks/context_graph/planner_fit_benchmark.py` fits simple planner families
against the saved real-project rows:

| Fit | Answerable | Avg tokens | Premium vs oracle |
| --- | ---: | ---: | ---: |
| cheapest answerable oracle | 48/48 | 607.7 | 0.000% |
| current default | 48/48 | 635.4 | 4.563% |
| per-class candidate fit | 48/48 | 635.4 | 4.563% |
| per-class current-budget fit | 48/48 | 635.4 | 4.563% |

Finding: the only lower planner fit picks `gg_max_1hop` for `multi_hop_path`,
which is not safe to promote because it changes the query-class semantics even
though this synthetic oracle still finds enough evidence. The production
planner should keep `multi_hop_path` at 2 hops until live answer scoring and
path-specific tasks prove otherwise.

The packet selector fit confirms the existing piecewise rule:

| Packet selector | Cases | Avg tokens | Read |
| --- | ---: | ---: | --- |
| `semantic_arrow` when `edges == 0`, else `gg_max` | 48/48 | 614.0 | best measured packet floor |
| sigmoid activation over edge count | 48/48 | 614.0 | collapses to the same hard threshold |

The fitted token surface for planning is now:

```text
tokens ~= intercept + node_coef * nodes + edge_coef * edges
```

with measured coefficients:

| Packet | Intercept | Node coef | Edge coef | R2 |
| --- | ---: | ---: | ---: | ---: |
| `gg_max` | 45.37 | -0.710 | 7.193 | 0.8901 |
| `semantic_arrow` | 30.20 | 1.081 | 12.035 | 0.9734 |
| `lowlevel` | 56.10 | 1.102 | 10.066 | 0.9625 |
| `sql` | 29.93 | 12.278 | 11.696 | 0.9541 |
| `gg_max_hybrid` | 50.55 | 4.812 | 7.956 | 0.7064 |

## Frontier Expansion

`benchmarks/context_graph/frontier_policy_benchmark.py` isolates expansion after
anchors are known. It adds harder tasks than the answerability benchmark:

- `hard_path_2hop`: exact two-hop edge containment with both endpoints seeded.
- `hub_precision`: strongest local hub edges under a smaller node budget.

Current saved result:

| Policy | Answerable | Node recall | Edge recall | Avg tokens | Irrelevant ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| current fixed expansion | 60/60 | 1.000 | 1.000 | 499.5 | 0.895 |
| current outward only | 47/60 | 0.972 | 0.850 | 331.0 | 0.866 |
| relation-strength scoring | 32/60 | 0.871 | 0.725 | 444.4 | 0.913 |
| query-overlap scoring | 34/60 | 0.831 | 0.696 | 446.0 | 0.917 |
| marginal-gain scoring | 27/60 | 0.794 | 0.621 | 441.1 | 0.921 |

Finding: the current fixed expansion remains the safest production default.
The continuous scoring variants reduce tokens but drop required path and hub
evidence. Outward-only traversal is promising for hub-local tasks, but it still
fails too many hard path tasks to become a broad default.

Engineering rule: use discrete gates where data shows a cliff
(`edges == 0`, query class, traversal direction), and use continuous functions
inside candidate scoring only after they beat the fixed policy on recall, not
only token count.

## Local Project Recall

The local project smoke/eval fixtures currently pass after anchor-limit tuning
and extension-normalized eval matching:

| Project | Query | Class | Node recall | Tokens |
| --- | --- | --- | ---: | ---: |
| `slotmachine` | video slot free games session | `subsystem_summary` | 1.000 | 185 |
| `slotmachine` | symbols combinations analyzer random number generator | `blast_radius` | 1.000 | 206 |
| `chess` | alpha beta search mcts trajectory | `blast_radius` | 0.667 | 338 |
| `chess` | static exchange evaluation see | `direct_lookup` | 1.000 | 43 |
| `chess` | ace neural model features nnue | `subsystem_summary` | 1.000 | 181 |
| `contextminer` | mcp server corpus status | `blast_radius` | 1.000 | 274 |
| `contextminer` | README mining tasks agents | `doc_summary` | 1.000 | 154 |
| `contextminer` | artifact mcp server | `direct_lookup` | 1.000 | 233 |

Finding: the previous failures were anchor/search and eval-normalization issues,
not graph construction or packet-format failures. The expected nodes already
existed in the saved graphs.

## Cross-Repo Anchor Stress

A stricter fixed-policy stress benchmark now generates exact-node tasks from
mixed local projects and cloned resources. It holds the production policy fixed
and reports recall plus waste metrics.

| Metric | Value |
| --- | ---: |
| Tasks | 92 |
| Pass | 92/92 |
| Avg node recall | 1.000 |
| Avg tokens | 204.7 |
| Avg irrelevant ratio | 0.820 |

| Task kind | Pass | Avg recall | Avg tokens | Irrelevant ratio |
| --- | ---: | ---: | ---: | ---: |
| `symbol_direct` | 30/30 | 1.000 | 85.4 | 0.814 |
| `file_summary` | 24/24 | 1.000 | 120.0 | 0.768 |
| `negative_sparse` | 8/8 | 1.000 | 14.9 | 0.479 |
| `concept_summary` | 14/14 | 1.000 | 182.0 | 0.942 |
| `hub_blast` | 16/16 | 1.000 | 671.5 | 0.971 |

Finding: structural query classes need more than the top lexical hits. The
current fixed policy searches a wider candidate pool for blast/path/reverse
queries, then prefers structural anchors over docs/concepts. The remaining
problem is efficiency, not recall: dense hub tasks still return very high
irrelevant ratios, so future work should reduce noise without losing the exact
hub-neighbor evidence.

## Live Graph Shape

`benchmarks/context_graph/live_graph_shape.py` scans the current repository and
checks whether live scanner output still has usable structure before saved
benchmark gates are trusted.

Current live `graphgraph` scan:

| Metric | Value |
| --- | ---: |
| Nodes | 3,463 |
| Edges | 10,330 |
| Source/symbol nodes | 980 |
| Symbol nodes | 883 |
| Doc-like nodes | 2,442 |
| Other nodes | 41 |
| Import/imports_from edges | 495 |
| Weak edges (`confidence < 0.7`) | 2,727 |
| Weak edge ratio | 0.264 |
| Doc node ratio | 0.705 |
| Generated export paths (`graphify-out`, `.code-review-graph`, `evidence`) | 0 |

Finding: Python relative import resolution was load-bearing. Before the scanner
fix, the live validation saw only 8 import edges; after resolving package
relative imports and directory hierarchy for language-kind file nodes, the live
shape is structurally plausible. The current clean rebuild also proves generated
graph/export directories are excluded by default. The remaining shape risk is
not generated-artifact pollution; it is doc/concept volume, especially
free-floating concept nodes with no path. Broad status queries now penalize
concept-only anchors unless the query is documentation-heavy, but packet
efficiency still needs doc/concept pruning work.

## Search Hot Path

`benchmarks/context_graph/search_hot_path_benchmark.py` measures repeated
lexical search against the current live graph. PageRank is now cached and
persisted in JSON graph saves, and node lexical tokenization is cached per
loaded graph. It now also isolates bare process-startup cost (fresh
subprocess, 5 rounds each) from in-process graph load and search, so a single
CLI invocation's latency budget can be attributed correctly.

Current live `graphgraph` result:

| Metric | Value |
| --- | ---: |
| Queries per round | 4 |
| `import graphgraph` median (fresh subprocess) | 0.131s |
| `graphgraph --help` median (full CLI cold start) | 0.152s |
| Graph load (in-process, one read) | 0.123s |
| Cold round seconds | 0.348 |
| Cached rounds | 5 |
| Cached total seconds | 0.766 |
| Cached seconds/query | 0.0383 |

Finding: repeated search against a loaded graph is now fast enough for agent
loops on this project shape. `python -X importtime -c "import graphgraph"`
shows the package's own imports cost only ~62ms of cumulative time (dominated
by ordinary stdlib costs: dataclasses, inspect, json, hashlib, pathlib) --
tree-sitter-language-pack is not eagerly imported at package top level. The
remaining ~90ms of bare-subprocess `import graphgraph` time is Python
interpreter/site startup, identical for any Python process. `graphgraph
--help` costs a further ~20ms on top for argparse subcommand setup, as
expected. So for a single CLI invocation, the latency budget is roughly:
~130ms fixed interpreter+import startup, ~120ms graph load, then query time
(tens of ms). Startup and load dominate a single-shot CLI call; repeated
in-process queries (the MCP server path) pay startup/load once and then run
at the ~38ms/query cached rate above.

## Live Query Noise

`benchmarks/context_graph/live_query_noise.py` measures packet composition for
runtime queries against the current live graph. Current result after generated
artifact skips, clean rebuild semantics, concept-anchor penalties, and
subsystem-summary doc/concept pruning:

| Query | Class | Packet | Nodes | Edges | Doc nodes | Concepts | Doc ratio | Impl edges | Weak edges | Generated paths | Tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| native_context_status | `subsystem_summary` | `gg_max_hybrid` | 118 | 381 | 5 | 0 | 0.042 | 331 | 0 | 0 | 2240 |
| retrieval_noise | `subsystem_summary` | `gg_max_hybrid` | 81 | 180 | 0 | 0 | 0.000 | 162 | 0 | 0 | 1199 |
| install_interop | `subsystem_summary` | `gg_max_hybrid` | 120 | 335 | 3 | 0 | 0.025 | 294 | 1 | 0 | 2028 |
| doc_usage | `doc_summary` | `doc_summary` | 12 | 10 | 5 | 2 | 0.417 | 0 | 2 | 0 | 168 |

Finding: normal broad runtime packets now keep generated export leakage at zero,
remove pathless concept nodes, and keep doc spillover at `0-4.2%` while
retaining hundreds of implementation edges. Documentation queries still use
`doc_summary` and are allowed to carry more doc/concept evidence.

## Dynamic Budget

`benchmarks/context_graph/dynamic_budget_benchmark.py` tests graph-shape
recommended node budgets against the current saved real-project
evidence-containment tasks. A smaller budget is promotable only if it preserves
full answerability. The same report now also audits an experimental
`context_window` candidate for token-window saturation and paging hints.

Current result:

| Candidate | Answerable | Avg tokens | Avg nodes | Irrelevant ratio |
| --- | ---: | ---: | ---: | ---: |
| current default | 48/48 | 635.2 | 75.2 | 0.473 |
| shape recommended | 48/48 | 616.9 | 72.9 | 0.471 |
| context window | 48/48 | 545.4 | 60.2 | 0.460 |
| observed window | 48/48 | 800.0 | 96.5 | 0.551 |

Finding: the first aggressive formula saved more tokens but failed broad
`blast_radius` and `subsystem_summary` tasks. The promoted rule keeps broad
evidence-gathering classes recall-first and only trims classes that preserved
100% answerability. Current measured savings for the promoted shape rule are
`2.87%`.

Critical read: `context_window` is promising but not promotable as “full context
saturation” yet. It preserved answerability and reduced tokens, but actual
target saturation averaged only `0.505` while the estimator predicted `1.068`.
That means the token-window math is currently too pessimistic about the expanded
subgraph density.

The second-pass `observed_window` candidate uses the actual rendered first page
after anchors are known. It improved actual target saturation to `0.781` and
kept `48/48` answerability, but raised average tokens to `800.0` and irrelevant
ratio to `0.551`. That is useful for a "maximize first-page information" mode,
but it is not a replacement for the cheaper production default until noise and
live model answer quality are measured.

## Promotion Gate

`benchmarks/context_graph/promote_check.py` is now the structural promotion
gate. Current run:

- unit tests: PASS (`119` tests, `2` skipped)
- live graph shape: PASS
- search hot path: PASS (`0.06065` cached seconds/query)
- dynamic budget: PASS (`48/48` shape-recommended answerable)
- real-project answerability: PASS (`48/48`)
- frontier current expansion: PASS (`60/60`)
- token proxy semantic-vs-gg decision agreement: PASS (`144/144`)
- prompt preflight: PASS
- Codex integration check: PASS (`21/21` checks, MCP launch probe about `499 ms`)
- live model scoring: skipped and explicitly not counted as model-quality proof

Finding: passing promotion means scanner/retrieval/packet changes are
structurally defensible. It does not prove live answer quality.

## Codex Integration

`benchmarks/context_graph/codex_integration_check.py` validates the repo-local
Codex plugin wrapper:

| Metric | Value |
| --- | ---: |
| Checks passing | 21/21 |
| MCP launch probe | 499.1 ms |
| Configurator temp-copy probe | 112.9 ms |
| Marketplace entries | 1 |
| Skill size | 3,138 chars |

Finding: the Codex plugin, marketplace entry, bundled skill, and MCP launch
configuration are locally coherent. `graphgraph install --project --platform
codex` generates the repo-local plugin and writes `.mcp.json` with an absolute
Windows checkout path so Codex starts the server from the repository root and
finds `.graphgraph/graph.json`; `scripts/configure_codex_plugin.py` remains a
repair command for copied checkouts, and the integration check verifies that
rewrite against a temporary repo copy.

## Doc-Code Pairing

`benchmarks/context_graph/doc_code_pairing_benchmark.py` inventories semantic
keys across the saved real-project graphs and splits them into doc-only,
code-only, paired, and unlabeled buckets. It also computes connected-component
coverage so the report can distinguish shared labels from actual graph links.
The scanner now creates `explains` bridges from doc sections to code symbols
when semantic aliases match, which is the load-bearing path for closing those
gaps in future scans.

Use it as the current gap map for deciding whether the next update should add
implementation, documentation, or both.

Report:

- `benchmarks/context_graph/out/real_projects/doc_code_pairing_report.md`

## What Is Still Unproven

The remaining major proof is live model-answer scoring:

- parse pass rate,
- node recall,
- edge recall,
- hallucinated nodes/edges,
- TTFT and total latency.

The prompt set is already frozen at:

- `benchmarks/context_graph/out/protocol/model_reasoning_prompts.jsonl`

Live execution is now explicit opt-in:

```powershell
RUN_OPENAI_REASONING_EVAL=1 python benchmarks/context_graph/model_reasoning_benchmark.py
RUN_GEMINI_REASONING_EVAL=1 python benchmarks/context_graph/model_reasoning_benchmark.py
SCORE_EXISTING_REASONING_ANSWERS=1 python benchmarks/context_graph/model_reasoning_benchmark.py
```

The scorer separates true hallucination from irrelevant-but-available context:

- hallucinated node/edge: returned by the model but absent from the packet.
- irrelevant node/edge: present in the packet but outside the expected answer
  key.
