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
| `direct_lookup` | 1 | `sql` | 99.2 | 1.000 | 1.000 |
| `reverse_lookup` | 1 | `sql` | 108.2 | 1.000 | 1.000 |
| `multi_hop_path` | 2 | `lowlevel` | 443.0 | 1.000 | 1.000 |
| `blast_radius` | 2 | `lowlevel` | 228.2 | 1.000 | 1.000 |
| `subsystem_summary` | 1 | `lowlevel` | 271.2 | 1.000 | 1.000 |
| `negative_query` | 1 | `lowlevel` | 157.8 | 1.000 | 1.000 |

Finding: hop depth and packet format should be chosen per query class. SQL rows
can beat low-level for tiny direct/reverse lookups because the low-level packet
pays for relation maps.

## Constraint Context

Project standards and LLM answer values should be scoped policies, not a global
prompt dump.

| Strategy | Avg tokens | Policy recall | Irrelevant ratio |
| --- | ---: | ---: | ---: |
| `global_all` | 223.0 | 1.000 | 0.625 |
| `scoped_compact` | 45.2 | 1.000 | 0.000 |
| `scoped_verbose` | 81.2 | 1.000 | 0.000 |

Finding: storing frontend standards, security rules, API contracts, testing
expectations, and LLM values has value when each policy has `applies_to` and
`task_tags`.

## Final Packet Composition

Composed packet = selected graph packet + optional policies.

| Policy strategy | Avg graph tokens | Avg policy tokens | Avg total tokens |
| --- | ---: | ---: | ---: |
| `none` | 218.0 | 0.0 | 218.0 |
| `scoped_compact` | 218.0 | 43.8 | 267.8 |
| `global_all_compact` | 218.0 | 126.0 | 350.0 |

Finding: scoped policies add useful constraints at modest cost. Global policy
dumps add unnecessary repeated tokens.

## What Is Still Unproven

The remaining major proof is live model-answer scoring:

- parse pass rate,
- node recall,
- edge recall,
- hallucinated nodes/edges,
- TTFT and total latency.

The prompt set is already frozen at:

- `benchmarks/context_graph/out/protocol/model_reasoning_prompts.jsonl`
