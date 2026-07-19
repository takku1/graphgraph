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

## Automatic Query Routing

`benchmarks/context_graph/query_router_benchmark.py` measures the deterministic,
no-I/O router used when CLI/MCP callers omit `query_class`.

| Metric | Result |
| --- | ---: |
| Labeled agent intents | 16 |
| Correct routes | 16/16 |
| Timed routes | 100,000 |
| Average route latency | 22.8 microseconds |

The router scores explicit intent cues for direct, reverse, path, impact,
summary, documentation, negative, and recent-change queries. Strong compound
cues resolve by deterministic precedence; weak or ambiguous input remains a
`subsystem_summary`. Explicit query classes bypass the router. At roughly
`0.023ms`, routing is negligible beside loaded-graph search (~38ms) and removes
the previous inconsistent CLI defaults (`query=blast_radius`,
`context=subsystem_summary`).

## Storage Backend Bake-Off

The storage bake-off was stopped after 13 completed projects rather than
running the whole corpus in one monolithic job. The completed set still covers
small projects, medium projects, and heavier graph shapes:

`chess`, `contextminer`, `express`, `flask`, `gamemechanic`, `graphgraph`,
`graphify`, `langgraph`, `locus`, `redis`, `regex`, `requests`, `slotmachine`.

Among full-fidelity persisted graph stores, the binary GraphGraph store is the
measured winner. It was measured as `.ggb` during the bake-off and then promoted
to the normalized `.gg` extension:

| Format | Projects | Avg bytes | Avg save ms | Avg load ms |
| --- | ---: | ---: | ---: | ---: |
| binary `.gg` | 13 | 2,488,521 | 167.86 | 163.45 |
| `.duckdb` | 13 | 5,295,498 | 550.47 | 249.14 |
| `.msgpack` | 13 | 7,924,231 | 191.83 | 211.77 |
| `.sqlite` | 13 | 8,496,994 | 300.31 | 210.17 |
| `.json` | 13 | 12,350,763 | 500.86 | 248.75 |

Finding: binary `.gg` is the smallest full-fidelity graph store, averaging about
`20%` of JSON size across the completed corpus while saving and loading faster
than JSON, SQLite, DuckDB, and usually msgpack. Query latency is not the
promotion criterion because every backend deserializes into the same in-memory
`Graph` dataclass before retrieval runs.

The old human-readable text `.gg` adjacency format remains readable for
backward compatibility, but new `.gg` writes use the full-fidelity binary store.

Operational rule: default native scans should write `.graphgraph/graph.gg`;
JSON and legacy text `.gg` should remain readable for compatibility.

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
finds `.graphgraph/graph.gg`; `scripts/configure_codex_plugin.py` remains a
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

## Fused Incremental Query

`benchmarks/context_graph/fused_query_benchmark.py` compares the previous
three-step library path (update changed files, remove deleted files, then
load/query) with one MCP `query_context` call carrying both path sets. On a
500-file synthetic symbol graph, three fresh equivalent runs measured:

| Path | Median |
| --- | ---: |
| Separate update + remove + query | 286.2 ms |
| Fused splice + in-memory query | 167.3 ms |

The fused path was **1.71x faster**. It performs one validated graph write,
bypasses pre-refresh packet-cache reads, and passes the new graph directly to
retrieval rather than parsing the persisted graph again. This measurement is
local orchestration latency, not networked MCP transport latency; removing two
external tool round trips should increase the end-to-end agent-loop advantage.

The Git-derived variant was also dogfooded on this repository. The first calls
spliced current edits and removed paths that had become ignored (including the
local `docs/bugs/` corpus). A fourth identical `context --sync git` call made
zero graph changes and the measured in-command context operation took about
1.07s. This proves idempotence for the observed worktree; it is not a general
cross-repository latency claim.

Broad session retrieval now compresses dirty-file personalization/traversal
seeds to one representative per path with
`K=min(4, ceil(log2(changed_paths+1)))`. A focused synthetic regression with
nine dirty files and five symbols per file selects four distinct paths and
retains the query-matching changed symbol. Model answerability and packet-token
impact still need promotion-benchmark coverage before tuning those coefficients.

## Locus Development-Loop Acceptance (2026-07-14)

A fresh installed Tree-sitter scan of the live Locus workspace, using its
audited exclusions and a temporary output, measured 9.4s for 515 files: 6,596
nodes, 23,551 edges, zero parse fallbacks/failures, and a valid packet graph.
Receiver resolution reported 825 unique, 4,620 ambiguous, and 10,487 unresolved
member calls; these counts intentionally expose the remaining type-analysis
frontier rather than hiding it.

The field-log regression query now contains a direct
`run_formula_yield_benchmark -> validate_candidates_detailed` `calls` edge.
Automatic scope inferred `crates/locus-pipeline`, bounded structural boundary
crossings to five nodes, and returned no isolated/lexical-only nodes. The
composed refresh/query/validation envelope measured about 1.03s on the saved
graph.

The affected-test route selected both direct Locus tests, including
`detailed_validation_preserves_proved_refuted_and_unknown_outcomes`, separated
direct from transitive tests, and produced runnable commands for the
`yield_benchmark`, `performance_regression_test`, and `pipeline` integration
targets. `.ignore`-excluded packet dumps no longer make freshness appear stale.

These are black-box observations on one real workspace, not universal language
resolution guarantees. Ambiguous/unresolved counts remain the evidence-led
backlog for richer type inference.

## Locus Real-Source Follow-Up Acceptance (2026-07-15)

The follow-up field report measured a 169.2s fresh Locus rebuild and attributed
141.3s to an opaque concept stage. After replacing the document-to-file
all-pairs mention loop with a token index and separating document extraction
from source-concept linking, the final paragraph-aware rebuild completed in
15.4s wall time (12.8s scanner time): 10,520 nodes, 40,070 edges, 515 selected
files, and zero Tree-sitter fallbacks/failures. This is an observed 11.0x wall-
time improvement on the same workspace, not a cross-project throughput claim.

The receipt now attributes 3.20s to 97 document files, names the slowest eight
documents, reports one honestly truncated document, and attributes 0.76s to
source-concept linking. Qualified Rust unit-struct receivers such as
`locus_advisors::IdentityDiscoveryAdvisor.examine(...)` are now type-resolved;
the same scan increased resolved member calls from 825 to 920 while retaining
explicit ambiguous/unresolved counts.

The previously failing compound implementation/test question now decomposes
into six facets and returns evidence for all six: the exact benchmark runner,
identity advisor, simpler-form advisor, finite-field detector, conjugate filter
plus numerical-stability path, and successful verified applications. Its final
packet contained 17 nodes and 22 edges with 100% edge coverage, no isolated or
lexical-only nodes, an empty unfulfilled-facet list, and the direct Cargo test
command. The measured query was about 4.16s, within the report's prior 5-7s
range despite bounded per-facet searches.

The roadmap acceptance query now selects paragraph nodes rather than only the
Phase 3 heading. In 1.91s it returned `run_initial_strategy_yield_benchmark`,
`preview_fixes`, and the complete remaining-exit sentence (representative
real-project corpus, pinned per-strategy yield/noise thresholds, and separate
generation-versus-extraction timing). The packet had 10 nodes, 6 edges, no
isolated/lexical-only nodes, and seven grounded document nodes. Paragraph facts
remain bounded at 1,200 characters and document/paragraph budget truncation is
reported.

## Locus Source-Baseline Graph-Quality Acceptance (2026-07-15)

The source-baseline report exposed semantic failures that structural validation
could not detect: two same-named Rust methods had collapsed into one valid node,
generic parse facets escaped the requested subsystem, Cargo commands confused
aggregated modules with integration targets, and facet telemetry contradicted
packet evidence.

Rust method identity is now owner-qualified. A fresh audited Tree-sitter scan
of Locus completed in 14.5s wall time (12.2s scanner time) with 10,646 nodes,
40,530 edges, 5,378 source nodes, 3,962 document nodes, no parse fallbacks or
failures, and a valid native graph. It preserves distinct
`YieldBaseline::evaluate` (line 127) and `SourceYieldBaseline::evaluate` (line
512) nodes, parents, signatures, and receiver-resolved test callers. The same
identity rule applies to every inherent/trait method in the corpus and survives
incremental file replacement.

Exact `Type::method` queries now bypass bounded lexical-candidate crowding and
do not redundantly reserve the owner type. Affected-test expansion unions
direction-consistent incoming and outgoing traversals under one 60/40 node
budget; this prevents the in-then-out `method -> file -> every sibling` zigzag.
On the focused Locus query this reduced the packet from 36 nodes to 14 while
retaining the exact method, its direct test, 1/1 facet coverage, zero isolated
nodes, and the runnable pipeline test command.

The full source-baseline question returned all six requested facets: exact
qualified method, strategy yield, noise, parse failures, verified source
applications, and rejection diagnostics. It selected 23 nodes / 31 edges with
no isolated or lexical-only nodes, recommended the direct
`real_source_corpus_measures_all_four_initial_strategies` test, and attached a
`covers` receipt naming the exact method. Meta-language such as “every part” is
discarded, single meaningful facets such as “noise” are retained, and semantic
aliases such as `preview_fixes` can satisfy verified-application evidence.

Cargo commands now derive package and integration-target identity from the
nearest `Cargo.toml`, explicit `[[test]]` entries, and `tests/<target>/main.rs`
aggregation. GraphGraph produced
`cargo test -p locus-frontends --test suite fpcore_test`; Cargo accepted the
same selector with `--no-run` and reported the `suite` executable. JSON anchor
receipts now describe selected traversal starts rather than earlier lexical
candidates.

These results close GG-SB-1 through GG-SB-4 for the observed Locus workload.
They do not close global Rust receiver inference: the fresh scan still reports
954 uniquely resolved, 4,544 ambiguous, and 10,526 unresolved member calls.
That remaining uncertainty is explicitly retained rather than converted into
false edges.

## Member-Call Topology Invariant and Python Evidence (2026-07-18)

A GraphGraph self-scan exposed two different problems behind the global
member-call warning:

- external and builtin method calls were counted as failed internal topology;
- `calls_candidate` was declared non-traversable but a zero-strength edge could
  still enter `Graph.expand` as a zero-score frontier node.

The graph runtime now treats nonpositive traversal strength as a hard boundary
at both hop zero and later expansion. The extractor only materializes ambiguous
candidate edges when receiver-type evidence exists. An untyped name collision
such as `values.append(...)` is recorded as `unknown_receiver`; it does not
become a graph edge.

Python receiver evidence now includes:

- parameter and local annotations;
- stable constructor and literal assignments;
- direct class receivers;
- stable annotated or constructor-bound `self.field` assignments;
- `self` and `cls` owner evidence.

A production-file extraction probe over the repository's 232 parseable inputs
reported 210 resolved member sites, zero typed-ambiguous sites, 725
unknown-receiver sites, 5,664 external-or-unmatched sites, and zero
`calls_candidate` edges. The prior saved graph contained 2,403 candidate edges.
The status surface now reports trusted-resolution precision separately from
receiver-evidence coverage and identifies pre-v2 snapshots as legacy telemetry
until a full symbol scan refreshes them.

## Locus Round-Three Closure and Ripgrep Transfer Audit (2026-07-18)

The round-three black-box report was re-audited against the current production
paths. Four reported failures were already closed before this audit:

- the live harness returns nonzero when required gates or query semantics fail
  and reports expected/actual failure details;
- repeatable custom queries replace the derived default query plan;
- the harness calls the same production query service and automatic router as
  CLI/MCP;
- exact changed paths use local, conjunctive facet anchors, while affected-test
  recommendations prioritize attributed symbols before file-level commands.

Two live gaps remained and are now closed:

- affected-test commands with no attributed direct/transitive recommendations
  receive `evidence_status=candidate_only` and force `semantic_fail`;
- refresh receipts now distinguish caller-requested paths, paths actually
  refreshed or removed, graph-write facts, and post-refresh
  `remaining_stale_paths`.

The prior `changed_count=0` after a successful explicit refresh was a
post-refresh fact, but the old receipt made it look like no work happened. The
new state-transition fields retain the compatibility counters while removing
that ambiguity.

A bounded source study of ripgrep identified transferable staging principles:
required-literal prefilters, full verification only around candidates,
input-shape-specific read strategies, worker-state reuse, early termination,
and explicit work bounds. These are translated into GraphGraph as exact
symbol/path/facet activation, typed-edge verification, changed-path splices,
process-local graph/index reuse, bounded facet search with post-retrieval
completeness receipts, and node/edge/source/token budgets. General
facet-complete expansion stopping remains unimplemented and benchmark-gated.

Two concrete changes survived measurement and correctness review:

- standalone `source_snippets` now shares the process-local graph load cache;
- MCP `query_context` can fuse bounded source windows with the topology packet,
  eliminating a second tool call when raw code is required. Fused raw source
  bypasses whole-response packet caching so file edits cannot return stale
  lines.

One plausible optimization was rejected. An experimental topology-free branch
measured about 97.7 ms warm on the 5,026-node self-graph, versus about 93.6 ms
for the existing path. This was not a controlled flat-file-search benchmark,
and the small difference does not establish a causal topology speedup. The
branch was removed because it demonstrated no advantage. The corrected
semantic-locality model and its limits are documented in
`semantic-locality-and-llm-efficiency.md`.

## Native Exact-Lookup Staging (2026-07-19)

The semantic-locality implementation audit found one concrete runtime gap:
unambiguous direct identifiers still initialized the full lexical index,
executed topology ranking, and paid for graph-wide document/code and shape
profiles.

The retained native GraphGraph path now:

- resolves explicit IDs, identifiers, filenames, and paths through a small
  node-revision-aware literal index;
- falls back to ranked/PPR retrieval when an exact name is ambiguous or the
  query is prose;
- bypasses full token/search index construction, PageRank/PPR, document/code
  profiling, shape profiling, and auxiliary semantic sources for an
  unambiguous direct lookup;
- records `anchor_strategy=exact_fast_path` and
  `sources.mode=exact_fast_path` in the production receipt.

The measurement used five repetitions, a newly parsed Graph object for each
measured retrieval, the 5,170-node saved GraphGraph self-graph, and the exact
identifier `recommend_node_budget`:

| Stage | Median |
| --- | ---: |
| Native exact search | 17.277 ms |
| Normal ranked/PPR search | 532.094 ms |
| Full production exact context | 65.087 ms |

Exact and ranked search returned the same first node. The 30.8x search-stage
ratio measures avoided GraphGraph work only. Graph parsing was outside the
timed region, and the experiment is neither a ripgrep comparison nor evidence
of lower LLM compute or better model answers.

Graphify was comparison-only during this audit. No Graphify dependency,
wrapper, adapter, fallback, or runtime call was added.

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
