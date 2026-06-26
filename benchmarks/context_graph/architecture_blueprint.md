# Context Graph / RAG Architecture Blueprint

This is the current architecture hypothesis from the benchmark suite.

## Objective

Minimize:

- input tokens
- prefill/TTFT pressure
- storage footprint
- retrieval latency
- irrelevant context

While preserving:

- node recall
- edge recall
- path recall
- model interpretability
- inspectable source grounding

## Layered Design

## Two Source Routes To Test

The benchmark should not assume the graph-first route is the winner. There are
two serious routes:

### Route A: Document/Wiki/Database Compiler

```text
Markdown / wiki / docs / SQLite rows
  -> deterministic parser
  -> typed context IR
  -> packet encoder
  -> LLM
```

This route treats project knowledge documents almost like source code. Headings,
links, tables, frontmatter, IDs, and repeated section patterns become parseable
structure. It may be the more LLM-native route because the source material is
already written in language the model understands.

Test it with:

- plain Markdown wiki pages
- compact Markdown sections
- prose relation sentences parsed deterministically
- noisy prose relation sentences for parser robustness tests
- SQLite row dumps
- parsed heading/link/table graphs
- hybrid packets that preserve short source snippets

### Route B: Code/AST/Graph Compiler

```text
Code / AST / Tree-sitter / imports / calls
  -> symbol graph
  -> CSR/CSC traversal index
  -> packet encoder
  -> LLM
```

This route treats code as the canonical truth and compiles deterministic edges
from imports, calls, definitions, references, tests, and ownership metadata. It
may win on blast radius, path questions, and change impact because the graph
edges are explicit and cheap to traverse.

Test it with:

- AST-derived symbol graphs
- file/module dependency graphs
- call/import/reference edges
- generated source snippets only when needed
- the same packet encoders as Route A

### Common Rule

Both routes must converge into the same intermediate representation:

```text
nodes(id, label, kind, path, summary, facts)
edges(source, target, type, weight, source_span, confidence)
documents(path, checksum, body)
```

That keeps the comparison fair. The source route changes, but retrieval,
serialization, token counting, round-trip validation, and live model scoring
stay identical.

## Constraint Context Layer

Project standards and LLM behavior rules should be stored as scoped policies,
not pasted into every prompt.

Examples:

- frontend colors, spacing, accessibility, and component standards
- API compatibility contracts
- security rules for auth/token/session paths
- testing expectations
- LLM answer values such as evidence citation and uncertainty handling

Policy records should include:

- `id`
- `kind`
- `priority`
- `applies_to`
- `task_tags`
- compact LLM-facing text
- longer human-readable text

The retrieval rule is path plus intent. A frontend design task touching
`src/components/**` should receive frontend visual/accessibility policies. A
backend auth change should receive API/security/testing policies. General graph
questions should receive only the evidence/uncertainty answer policy, ideally as
a cached prefix.

### 1. Canonical Store

Use SQLite as the first canonical store.

Tables:

- `nodes(id, label, kind, path, summary, facts, updated_at)`
- `edges(source, target, type, weight, source_span, confidence, updated_at)`
- `documents(path, checksum, body)`

Why:

- easy to inspect
- easy to diff
- fast enough at medium scale
- supports indexes
- avoids premature binary-only storage

### 2. Hot Graph Indexes

Build derived indexes from the canonical store:

- CSR for outgoing edges
- CSC for incoming edges
- optional bitmap indexes for set filters

Use CSR/CSC for:

- 1-hop expansion
- 2-hop expansion
- path prefiltering
- blast-radius queries

Use bitmaps for:

- changed-file masks
- team/subsystem filters
- kind filters
- intersection/union of candidate sets

Benchmark result: CSR-style binary is the likely machine floor for sparse
weighted graphs. Dense bitmaps lose badly on large sparse graphs unless the
query is topology-only and dense.

### 3. Retrieval Policy

Default policy:

```text
graph_1hop_lowlevel
```

Escalate to:

```text
graph_2hop_lowlevel
```

When:

- task asks for blast radius
- task asks for path/multi-hop reasoning
- edited node is high-risk
- first-hop evidence does not satisfy enough expected relation classes

Fallback retrieval:

```text
graph_2hop_sql
```

When live model tests show low-level packets cause interpretation errors.

### 4. LLM Packet

Preferred packet:

```text
GG-LL low-level adjacency
```

Format:

```text
<g>
<r>
1:calls
2:reads
</r>
<n>
N00001:AuthService
N00002:TokenStore
</n>
<a>
N00001,N00002,1,0.94
</a>
</g>
```

Use a stable cached schema prefix:

```text
Decode GG-LL. <r> maps relation_id:relation. <n> maps node_id:label.
<a> rows are source,target,relation_id,weight.
```

First fallback:

```text
SQL rows
```

Use when semantic anchors are worth the extra tokens.

Final fallback:

```text
hybrid graph + snippets
```

Use when source-grounded factual explanation matters more than raw compression.

## Current Inflection Point

From current deterministic benchmarks:

```text
smallest passing retrieval+packet: graph_1hop_lowlevel
perfect-recall safety point:       graph_2hop_lowlevel
machine storage floor:             CSR binary
semantic prompt fallback:          SQL rows
```

## Decision Matrix

| Need | Choice |
| --- | --- |
| Cheapest good default | `graph_1hop_lowlevel` |
| Highest recall without full dump | `graph_2hop_lowlevel` |
| Model struggles with compact syntax | `graph_1hop_sql` or `graph_2hop_sql` |
| Needs citations/source facts | hybrid graph + snippets |
| Local storage/query floor | SQLite + CSR/CSC derived indexes |
| Fast set filters | bitmap side indexes |
| Human debugging | Markdown reports and saved packets |

## What Is Not Proven Yet

The deterministic harness now proves:

- retrieval evidence coverage
- token pressure
- storage footprint
- packet schema overhead
- mechanical packet round-trip parseability

It does not prove final model reasoning accuracy. The remaining required
validation is live answer testing:

1. `lowlevel_schema`
2. `sql_schema`
3. `hybrid_schema`

Against:

- multi-hop path tasks
- blast-radius tasks
- negative/no-edge tasks
- subsystem summary tasks

Success means low-level packets preserve answer accuracy and reduce TTFT/cost.
If they fail, SQL rows become the production prompt default.

Use:

```powershell
python benchmarks\context_graph\model_reasoning_benchmark.py
```

without API env vars to generate the prompt set, then set
`RUN_OPENAI_REASONING_EVAL=1` for live scoring.
