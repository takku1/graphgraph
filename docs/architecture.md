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
They are compatibility inputs, not default runtime sources.

## Shared IR

Every source route compiles to the same logical shape:

- **nodes**: `id`, `label`, `kind`, `path`, `summary`, `facts`
- **edges**: `source`, `target`, `type`, `weight`
- **policies**: `id`, `kind`, `priority`, `applies_to`, `task_tags`, `compact`, `content`

To support compatibility with tools like Graphify, code-review graph stores, and
CSV edge lists, the internal loader permits loose schema binding with explicit
fallback mappings (e.g., fallback from `label` to `name` or `id`, `kind` to
`file_type` or `type`, `path` to `source_file`, and `summary` to
`properties.description`). This is an ingestion convenience. Native graphgraph
graphs live under `.graphgraph/`.

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

Current official packet targets:

- `lowlevel`: compact GG-LL adjacency
- `sql`: SQL-style rows
- `hybrid`: graph rows plus grounding snippets
- `svo`: compact subject-verb-object triples
- `semantic_arrow`: relation words inline with directed arrows
- `gg_max`: integer node/relation coding for larger topology packets
- `gg_max_hybrid`: `gg_max` plus compact summaries/facts

Low-level and SQL packets should pass mechanical validation before they are
returned to an LLM client. Validation checks block structure, node references,
relation references, and numeric weights.

The adaptive planner chooses per query class:

- direct/reverse: usually `1hop gg_max`
- path/blast: usually `2hop gg_max`
- summary: `gg_max` for structural summaries, `gg_max_hybrid` or
  `doc_summary` when grounded prose/facts dominate
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
