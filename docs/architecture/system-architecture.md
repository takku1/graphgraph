> **Academic title:** System Architecture (narrative)  
> **L0 map:** [SYSTEM.md](./SYSTEM.md)  
> **Legacy:** `architecture.md`

# Architecture

`graphgraph` separates native indexing, storage, retrieval, packet rendering,
constraint selection, validation, and scoring. External graph tools are import
routes; they are not the core architecture.

```text
native source scanner
  -> native graph store
  -> retrieval planner
  -> graph packet encoder
  -> scoped policy selector
  -> final LLM packet
  -> mechanical validation
  -> live model scoring
```

External graph files enter before the native store through explicit `ingest`.
They are compatibility inputs, not default runtime sources. Installing
GraphGraph and running normal scan/query/context commands does not invoke or
read Graphify, code-review-graph, or other graph-tool outputs.

## Execution Model and Latency

GraphGraph runs the same retrieval core behind two transports, and the choice of
transport dominates latency by three orders of magnitude. This is a property of
process lifetime, not of the graph or the algorithms.

```text
CLI          new interpreter -> import -> load graph -> answer -> exit
MCP server   long-lived process -> [ load graph once ] -> answer -> answer -> ...
```

Measured on Flask (460 nodes / 1,311 edges), one-hop `relations`:

| Stage | Cost |
|---|---:|
| Python interpreter start (before any GraphGraph code) | ~126 ms |
| GraphGraph import and dispatch | ~3 ms |
| `load_any`, first call in a process | ~6 ms |
| `load_any`, later calls (process graph cache) | ~0.2 ms |
| `query_relations` on a resident graph | ~0.02 ms |
| **End to end, CLI subprocess** | **~252 ms** |
| **End to end, resident process** | **~0.26 ms** |

Two consequences worth stating plainly, because both are easy to get wrong:

**The floor for a one-shot CLI call is the interpreter, not GraphGraph.** About
126 ms is spent before any GraphGraph code executes, and GraphGraph's own share
of a cold invocation is single-digit milliseconds. A resident *service* fronted
by a CLI client cannot recover this, because the client is itself a Python
process paying the same 126 ms. Only a caller that is already long-lived, or a
non-Python client, can.

**That caller already exists.** The MCP server is long-lived and `load_any`
memoizes per process against a store fingerprint (`remember_loaded_graph`,
`graph_store_fingerprint`), so a graph is parsed once and reused until its bytes
change. Residency is therefore a property the system already has on the MCP
path; it is not a missing component.

Practical rule: use the MCP tools for interactive and repeated retrieval, and
the CLI for one-shot or scripted use where a ~250 ms fixed cost is irrelevant.
Benchmarks that time repeated CLI invocations are measuring process spawn, and
will understate retrieval performance by roughly 1000x.

## Native Storage Contract

The only automatically discovered native store is
`.graphgraph/graph.gg`. New `.gg` files use the full-fidelity, sectioned GGB4
encoding with separate identity/detail/edge/relation sections and per-section
checksums. The in-memory `Graph`/`Node`/`Edge` model remains the canonical
logical IR for consumers that require complete materialization.

Legacy `.ggb`/GGB2, human-readable adjacency `.gg`, graph JSON, CSV, and TSV are
explicit migration or interchange inputs. They remain readable through
`load_any`/`ingest`, but GraphGraph does not create new `.ggb` stores or
auto-select legacy files as the active project graph.

The compact `#gg` text returned to an LLM is a packet encoding, not the binary
`.gg` persistence encoding:

```text
source -> Graph IR -> binary graph.gg -> selected subgraph -> #gg packet
                                                    \-> JSON receipt envelope
```

JSON remains necessary for MCP/CLI control receipts and optional interchange,
not for the native graph write path.

## Shared IR

Every source route compiles to the same logical shape:

- **nodes**: `id`, `label`, `kind`, `path`, `summary`, `facts`
- **edges**: `source`, `target`, `type`, `weight`
- **policies**: `id`, `kind`, `priority`, `applies_to`, `task_tags`, `compact`, `content`

To support compatibility with tools like Graphify, code-review graph stores, and
CSV edge lists, the internal loader permits loose schema binding with explicit
fallback mappings (e.g., fallback from `label` to `name` or `id`, `kind` to
`file_type` or `type`, `path` to `source_file`, and `summary` to
`properties.description`). This is an ingestion convenience. The native
GraphGraph artifact is `.graphgraph/graph.gg`.

## Source Routes

Supported native and benchmark routes:

- `native_scan_files`
- `native_scan_symbols`
- `native_gg`
- `code_graph_direct`
- `sqlite_rows`
- `wiki_with_edges`
- `wiki_prose_relations`
- `wiki_noisy_prose`
- `wiki_plain_no_edges`

The official implementation should prefer deterministic extraction first. LLM
extraction can be added later, but it must be scored separately from packet
serialization.

## Packet Formats

Current public packet targets:

<!-- BEGIN GENERATED: packet-formats -->
| Packet | Relative tokens | Use |
| --- | ---: | --- |
| `lowlevel` | 1.03x | XML-tagged adjacency; a readable structural fallback. |
| `sql` | ~0.7x | Table-row layout for models that prefer relational structure. |
| `hybrid` | ~2.3x | Readable Markdown node and edge lists with higher token overhead. |
| `semantic_arrow` | 1.49x | SVO arrows; preferred for zero-edge structural results. |
| `gg` | 1.00x | Measured token floor for non-empty structural graph packets. |
| `gg_hybrid` | ~1.6x | Integer-id gg plus inline grounded node facts. |
| `gg_lex` | ~1.0x | Compact gg topology with stable lexical node identifiers. |
| `gg_lex_hybrid` | ~1.6x | Lexical-id gg plus inline grounded node facts. |
| `svo` | ~1.1x | Self-describing subject-verb-object triples. |
| `doc_summary` | ~0.6x | Grounded document sections and notes without topology. |
<!-- END GENERATED: packet-formats -->

Older research docs call the compact `gg` representation `gg_max`; the
accepted CLI/API name is `gg`.

## Query Classes

<!-- BEGIN GENERATED: query-classes -->
| Query class | Routing | Purpose |
| --- | --- | --- |
| `direct_lookup` | automatic or explicit | Locate a definition or focused symbol. |
| `reverse_lookup` | automatic or explicit | Find callers, references, implementors, or dependents. |
| `affected_tests` | automatic or explicit | Find direct, transitive, and behavioral tests affected by a change. |
| `multi_hop_path` | automatic or explicit | Trace a dependency, call, control, or data-flow path. |
| `blast_radius` | automatic or explicit | Estimate downstream change impact and supporting evidence. |
| `subsystem_summary` | automatic or explicit | Summarize a subsystem or architecture slice. |
| `doc_summary` | automatic or explicit | Ground an answer in document sections and paragraphs. |
| `negative_query` | automatic or explicit | Prove absence, isolation, or lack of references. |
| `recent_changes` | automatic or explicit | Retrieve qualifying recent history and fixes evidence. |
| `spreading_activation` | explicit | Use explicit multi-step activation retrieval. |
<!-- END GENERATED: query-classes -->

Low-level and SQL packets should pass mechanical validation before they are
returned to an LLM client. Validation checks block structure, node references,
relation references, and numeric weights.

The adaptive planner chooses per query class. Use `query_context` or
`graphgraph context` as the default agent entry point so anchors are discovered
from the natural-language query before packet rendering:

- direct/reverse: usually `1hop gg`
- path/blast: usually `2hop gg`
- summary: `gg` for structural summaries or `doc_summary` when grounded
  docs/facts dominate
- zero-edge packets: usually `semantic_arrow`

## Constraint Policies

Policies are task-scoped constraints. Examples:

- frontend visual standards,
- accessibility rules,
- API compatibility,
- security requirements,
- testing expectations,
- LLM answer values.

Do not inject all policies globally. Select by path and task tags, then render
compact policy text.

## Storage

Recommended first implementation:

- canonical `.gg` plus JSON records for inspectability,
- derived CSR/CSC/bitmap indexes for hot traversal,
- text packets only at the LLM boundary.

Binary/CSR storage is a machine optimization. It is not directly useful as a
prompt unless decoded into an LLM-readable packet.

