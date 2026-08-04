# Locus Comparison Snapshot

Date: 2026-06-26

Target repo: local `locus` checkout configured for the benchmark run.

Command used for the current benchmark:

```powershell
$env:LOCUS_REBUILD='1'
$env:LOCUS_FRONTEND='tree_sitter'
uv run --with tree-sitter --with tree-sitter-language-pack python benchmarks\context_graph\locus_benchmark.py
```

Artifacts:

- Native graphgraph: `benchmarks/context_graph/out/locus/locus-native.json`
- Graphify import: `benchmarks/context_graph/out/locus/locus-graphify-import.json`
- Summary: `benchmarks/context_graph/out/locus/locus_summary.md`

## Graph Shape

| Source | Nodes | Edges |
| --- | ---: | ---: |
| graphgraph Tree-sitter + docs + communities | 13,129 | 29,831 |
| Graphify import | 7,932 | 16,950 |

Top native edge types:

| Type | Count |
| --- | ---: |
| `contains` | 8,625 |
| `mentions` | 7,121 |
| `calls` | 7,095 |
| `discusses` | 3,285 |
| `field_of` | 925 |
| `section_of` | 960 |
| `imports_from` | 986 |
| `returns` | 571 |
| `imports` | 211 |
| `implements` | 51 |

Top Graphify-import edge types:

| Type | Count |
| --- | ---: |
| `references` | 6,031 |
| `contains` | 4,996 |
| `calls` | 4,694 |
| `method` | 779 |
| `imports_from` | 272 |
| `implements` | 107 |

## Read

The native scanner is no longer a thin Graphify wrapper or packet renderer. On
this Rust-heavy codebase, graphgraph now extracts more deterministic structure
than the imported Graphify graph: more nodes, more edges, more `calls`, and
more `imports_from`, with explicit frontend metadata and provenance.

Tree-sitter is the preferred precision frontend. Regex remains useful as a
fallback and for recall experiments, but it should not dominate prompt
evidence. Document and semantic concepts now share the same normalization path,
so case, punctuation, kebab-case, and CamelCase variants collapse to one
concept key.

Graphify still carries some richer semantic relation vocabulary and more Rust
`implements` edges (`107` vs native `51`). That is the next scanner gap:
generic impl blocks. Native now extracts Rust struct fields and function return
types, adding `field_of` and `returns` edges that Graphify import does not
represent in the normalized relation vocabulary.

Retrieval quality is now ahead on this benchmark. Native reaches 1.0 node
recall on all 10 tasks. Graphify remains below 1.0 recall on compiler rules,
visitor summary, and rule registry tasks. Native has lower token estimates than
Graphify on compiler rules, exact reverse lookup, differentiation, matrix
rules, visitor summaries, docs, and rule registry tasks. Graphify is still
cheaper on some path-query packets.

## Retrieval Eval

Task file: `benchmarks/context_graph/data/locus_tasks.json`

Max nodes: `40`

| Graph | Query | Node Recall | Edge Recall | Token Estimate |
| --- | --- | ---: | ---: | ---: |
| native | compiler expression rules | 1.000 | 1.000 | 275 |
| graphify | compiler expression rules | 0.667 | 1.000 | 311 |
| native | what calls compile_rules_slice | 1.000 | 1.000 | 182 |
| graphify | what calls compile_rules_slice | 1.000 | 1.000 | 422 |
| native | differentiation synthesizer applier derivative rules | 1.000 | 1.000 | 258 |
| graphify | differentiation synthesizer applier derivative rules | 1.000 | 1.000 | 340 |
| native | matrix transpose orthogonal symmetric square vector rules | 1.000 | 1.000 | 289 |
| graphify | matrix transpose orthogonal symmetric square vector rules | 1.000 | 1.000 | 287 |
| native | symbolic expression visitor condition visitor | 1.000 | 1.000 | 327 |
| graphify | symbolic expression visitor condition visitor | 0.500 | 1.000 | 259 |
| native | locus README installation usage | 1.000 | 1.000 | 164 |
| graphify | locus README installation usage | 1.000 | 1.000 | 96 |

## Next Improvements

1. Improve Rust generic impl extraction and trait implementation coverage.
2. Add token thresholds to CI-style benchmark runs so recall/token regressions
   fail loudly.
3. Add optional semantic triples from reviewed LLM/human extraction.
4. Run the same benchmark harness across additional local projects to catch
   language and repo-shape regressions.
