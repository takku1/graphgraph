# Schema Alignment And Import Compatibility

`graphgraph` has a native graph contract. It also accepts outside graph shapes
because interoperability, comparison, and migration matter.

Interop is a first-class boundary, not a thin wrapper. A Graphify export, Neo4j
edge dump, CSV file, or code-review graph should enter through `ingest`,
normalize into the shared IR, and then behave like any other `.graphgraph`
graph.

## Native Fields

Nodes:

- `id`
- `label`
- `kind`
- `path`
- `summary`
- `facts`
- `scope`
- `parent`
- `source`
- `confidence`
- `active`
- `created_at`
- `updated_at`

Edges:

- `source`
- `target`
- `type`
- `weight`
- `confidence`
- `provenance`
- `evidence`
- `source_location`
- `valid_from`
- `valid_to`
- `active`

## Fallback Bindings

The JSON loader accepts common aliases:

| Native field | Fallbacks |
| --- | --- |
| `label` | `name`, `id` |
| `kind` | `file_type`, `type`, `unknown` |
| `path` | `source_file`, empty string |
| `summary` | `properties.description`, empty string |
| `scope` | `community`, empty string |
| `parent` | `parent_id`, empty string |
| `source` | `source_uri`, empty string |
| `edges` | `links` |
| `type` | `relation`, `dependency` |
| `provenance` | `kind`, `source_type`, `extracted` |
| `source_location` | `loc`, empty string |
| `valid_from` | `created_at`, empty string |

These fallbacks exist so imports do not crash. They are not a reason to design
new native data around another tool's schema.

## Import Rule

Use:

```powershell
python -m graphgraph ingest --input graphify-out/graph.json --output .graphgraph/graph.gg
```

Do not rely on implicit discovery of external graph directories. The default
graph lookup should prefer `.graphgraph/graph.gg`; `.graphgraph/graph.json`
remains a compatibility/import path.
Normal install, scan, context, query, and MCP workflows do not touch external
graph tools or their generated output directories unless an explicit input path
is supplied.

## Evaluation Rule

Every imported source route should be compared on the same tasks:

- node recall,
- edge recall,
- path recall,
- answer accuracy,
- irrelevant context ratio,
- token count,
- retrieval latency,
- update cost.

If an imported graph performs better on context quality, learn from it. If
native graphgraph packets perform better on token cost, preserve that advantage.
