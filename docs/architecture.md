# Architecture

`graphgraph` separates storage, retrieval, packet rendering, and constraint
selection.

```text
source route
  -> shared context IR
  -> retrieval planner
  -> graph packet encoder
  -> scoped policy selector
  -> final LLM packet
  -> mechanical validation
  -> live model scoring
```

## Shared IR

Every source route compiles to the same logical shape:

- **nodes**: `id`, `label`, `kind`, `path`, `summary`, `facts`
- **edges**: `source`, `target`, `type`, `weight`
- **policies**: `id`, `kind`, `priority`, `applies_to`, `task_tags`, `compact`, `content`

To support zero-configuration indexing tools like `graphify`, the internal loader permits loose schema binding with explicit fallback mappings (e.g., fallback from `label` to `name` or `id`, `kind` to `file_type` or `type`, `path` to `source_file`, and `summary` to `properties.description`). This allows code graphs and external databases to be compared and validated out-of-the-box.

## Source Routes

Supported benchmark routes:

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

Low-level and SQL packets should pass mechanical validation before they are
returned to an LLM client. Validation checks block structure, node references,
relation references, and numeric weights.

The adaptive planner chooses per query class:

- direct/reverse: often `1hop sql`
- path/blast: usually `2hop lowlevel`
- summary/negative: usually `1hop lowlevel`

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

- canonical SQLite or JSON records for inspectability,
- derived CSR/CSC/bitmap indexes for hot traversal,
- text packets only at the LLM boundary.

Binary/CSR storage is a machine optimization. It is not directly useful as a
prompt unless decoded into an LLM-readable packet.
