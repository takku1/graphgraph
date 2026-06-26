# Storage And Prompt Format Research Notes

The benchmark should separate two layers:

1. **Machine storage/query format**: optimized for update cost, graph traversal,
   set operations, and disk/memory footprint.
2. **LLM packet format**: optimized for token count, interpretability, and
   answer accuracy after retrieval.

Those are not necessarily the same format.

There is also a source-route question:

1. **Document-native route**: Markdown, wiki pages, tables, and database rows
   are parsed as structured source material.
2. **Code-native route**: AST/import/call/reference graphs are parsed from code.

Both routes should compile into the same graph IR before retrieval. Otherwise
we would be benchmarking source extraction quality and packet serialization at
the same time, which makes the result hard to trust.

## Candidate Source Routes

### Markdown / Wiki As Context Source Code

Markdown has useful structure if we treat it as parseable input instead of raw
prose:

- headings define entities and scopes
- links define weak graph edges
- tables define typed rows
- frontmatter defines metadata
- code fences define source-grounded snippets
- repeated templates define predictable fields
- relation sentences can be parsed deterministically when they use a controlled
  verb vocabulary

This may outperform code graphs for human-facing explanation tasks because the
text is already semantic. It can underperform on blast-radius and dependency
tasks if links and headings do not encode true execution relationships.

The benchmark should include both clean and noisy document routes. Clean routes
test whether a document format can be losslessly compiled. Noisy routes test
whether deterministic parsers lose recall or accidentally extract false edges
from ordinary prose.

### Database Rows As Source

SQLite/CSV row dumps are a middle ground between prose and graph packets. They
carry explicit columns while staying compact. This is useful as a parser target
for both docs and code extraction.

### Code / AST As Source

AST-derived graphs can produce high-confidence structural edges. They are better
for impact analysis and path questions, but they can miss intent, ownership,
business rules, and undocumented runtime behavior.

### Shared Intermediate Representation

Route comparisons should normalize into the same node/edge/document IR before
packet rendering. If a Markdown parser and a Tree-sitter parser both produce
`nodes` and `edges`, then `lowlevel`, `sql`, and `hybrid` packets can be scored
fairly across both.

## Candidate Storage Formats

### Adjacency List / Edge Table

Best default for sparse project graphs. Most codebase graphs are sparse: each
symbol/file usually touches a small fraction of the corpus. Adjacency lists are
space efficient for sparse graphs and make neighbor traversal natural.

Use when:

- retrieving 1-hop and 2-hop neighborhoods
- storing edge metadata like relation type, confidence, file span, timestamp
- supporting incremental updates

### CSR / CSC Sparse Arrays

Compressed Sparse Row stores graph edges in arrays such as:

- `ptr`: row offsets
- `col`: target ids
- `rel`: relation ids
- `w`: weights

CSR is a strong machine format for fast row-neighborhood reads and sparse
matrix operations. CSC is the reverse-direction companion for incoming edges.

Use when:

- graph is large and mostly static
- query pattern is neighbor expansion
- you want predictable memory layout and low overhead

### Roaring Bitmaps

Roaring bitmaps are useful when queries become set algebra:

- union of neighbors
- intersection of dependencies and changed files
- permission filters
- team/subsystem masks

They are especially attractive for high-cardinality sets and fast boolean
operations. They are less useful as a direct LLM prompt format.

### HDT / Dictionary + Triples

HDT-style dictionary/triples formats are relevant if the graph becomes RDF-like
or semantic-web-like: many subject-predicate-object triples with repeated
strings. The dictionary/triples split maps closely to our low-level adjacency
idea: deduplicate labels, then encode relations as IDs.

### SQLite / DuckDB Tables

Relational tables are a pragmatic baseline:

- easy to inspect
- good enough for medium graphs
- supports indexes and SQL joins
- stable storage

SQLite is likely the best first implementation. CSR/bitmap indexes can be added
beside it later for hot paths.

## Candidate LLM Packet Formats

### Low-Level Adjacency

Smallest text packet. Best token floor.

```text
<r>
1:calls
2:reads
</r>
<n>
N1:AuthService
N2:TokenStore
</n>
<a>
N1,N2,1,0.94
</a>
```

Risk: the model may reason worse if semantic signposts are too compressed.

### SQL Rows

Slightly larger but clearer:

```text
TABLE edges: source,target,type,weight | N1,N2,calls,0.94
```

This is the likely fallback if low-level adjacency harms answer accuracy.

### Hybrid Packet

Graph rows plus short grounding snippets. Best when final answer needs facts,
not just topology.

## Current Hypothesis

- Storage: `SQLite edge table + optional CSR/CSC derived indexes`
- Retrieval: `graph_1hop` by default, escalate to `graph_2hop` for path and
  blast-radius tasks
- LLM packet: try `low_level_adj`; fallback to `sql_rows`; use hybrid snippets
  when factual source grounding is required

## Sources

- GraphBLAS represents graph algorithms through sparse matrices and linear
  algebra primitives: https://graphblas.org/
- Sparse matrix CSR/CSC formats are standard structures for efficient sparse
  graph operations: https://en.wikipedia.org/wiki/Sparse_matrix
- Sparse graph representation tradeoffs between adjacency lists and matrices:
  https://en.wikipedia.org/wiki/Graph_%28abstract_data_type%29
- Roaring bitmap papers show fast compressed set operations:
  https://arxiv.org/abs/1402.6407 and https://arxiv.org/abs/1709.07821
- HDT uses Header, Dictionary, Triples to compress RDF-style repeated triples:
  https://en.wikipedia.org/wiki/HDT_%28data_format%29
