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
| production default | 48/48 | 580.5 |
| uniform `n=120` | 48/48 | 710.3 |
| unbounded | 48/48 | 6401.1 |

Finding: the current per-query-class production default is structurally
defensible. It is `2.918%` above the cheapest answerable frontier while saving
about `18%` versus uniform `n=120`.

## Local Project Recall

The local project smoke/eval fixtures currently pass after anchor-limit tuning
and extension-normalized eval matching:

| Project | Query | Class | Node recall | Tokens |
| --- | --- | --- | ---: | ---: |
| `slotmachine` | video slot free games session | `subsystem_summary` | 1.000 | 279 |
| `slotmachine` | symbols combinations analyzer random number generator | `blast_radius` | 1.000 | 212 |
| `chess` | alpha beta search mcts trajectory | `blast_radius` | 1.000 | 417 |
| `chess` | static exchange evaluation see | `direct_lookup` | 1.000 | 38 |
| `chess` | ace neural model features nnue | `subsystem_summary` | 0.667 | 337 |
| `contextminer` | mcp server corpus status | `blast_radius` | 1.000 | 306 |
| `contextminer` | README mining tasks agents | `doc_summary` | 1.000 | 179 |
| `contextminer` | artifact mcp server | `direct_lookup` | 1.000 | 34 |

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
| Pass | 87/92 |
| Avg node recall | 0.960 |
| Avg tokens | 258.6 |
| Avg irrelevant ratio | 0.822 |

| Task kind | Pass | Avg recall | Avg tokens | Irrelevant ratio |
| --- | ---: | ---: | ---: | ---: |
| `symbol_direct` | 30/30 | 1.000 | 84.4 | 0.819 |
| `file_summary` | 24/24 | 1.000 | 132.5 | 0.767 |
| `negative_sparse` | 8/8 | 1.000 | 14.9 | 0.479 |
| `concept_summary` | 13/14 | 0.929 | 185.6 | 0.940 |
| `hub_blast` | 12/16 | 0.833 | 959.7 | 0.980 |

Finding: camel-case tokenization and capped PageRank fixed the main symbol
anchor failures. The remaining hard cases are hub/blast queries and noisy
concept anchors. Their problem is not packet choice; it is over-retrieval and
ambiguous anchor selection.

## What Is Still Unproven

The remaining major proof is live model-answer scoring:

- parse pass rate,
- node recall,
- edge recall,
- hallucinated nodes/edges,
- TTFT and total latency.

The prompt set is already frozen at:

- `benchmarks/context_graph/out/protocol/model_reasoning_prompts.jsonl`
