# Source Layout

`src/graphgraph/` is organized by runtime responsibility. The package root
holds only `__init__.py` (the curated public API), `__main__.py`, and
`version.py` — every implementation module lives in a domain package below.

## Domain Packages

- `graph/`: graph model, operations, relation ontology, and traversal policy.
- `scanner/`: file collection, imports, document extraction, and source
  frontends.
- `concepts/`: concept normalization, doc/code alignment, and typed
  interpretation-layer registry.
- `retrieval/`: lexical search and context compilation. `context.py` is the
  `retrieve_context` orchestrator; the stages it drives live beside it in
  `scoping.py`, `pruning.py`, `facets.py`, `expansion.py`, `reservations.py`,
  `document_status.py`, `test_recommendations.py`, `anchors.py`, and
  `quality.py`. Also holds activation, budget shaping, connected selection
  (`selection.py`), and node-suggestion diagnostics (`findnodes.py`).
  `tree_knapsack.py` remains a compatibility import for older integrations.
- `planning/`: query plans, packet choices, budgets, graph-shape budgets, and
  policy selection.
- `packets/`: packet renderers and packet/graph validation.
- `runtime/`: runtime persistence primitives — packet cache (`cache.py`), scan
  manifest (`manifest.py`), and atomic on-disk state (`state.py`).
- `storage/`: native `.gg` binary storage backends.
- `io/`: graph load/save/merge APIs plus graph/policy/lesson path discovery.
- `analysis/`: graph summaries, graph comparisons, and retrieval evaluation
  (`eval.py`).
- `services/`: higher-level query/context/snippet/native orchestration, plus
  the gate-control receipt (`control.py`).
- `acceptance/`: black-box acceptance harness and the live-validation harness
  (`live_validation.py`). These are release/eval tooling, not engine code.
- `cli/` and `mcp/`: command-line and MCP surfaces. CLI installation/plugin
  generation lives in `cli/install.py`; runtime command handlers live in
  `cli/commands.py`.

## Import Rule

Import from the module that owns the code:

```python
from graphgraph.graph.core import Graph
from graphgraph.packets.renderers import render_packet
from graphgraph.packets.validation import validate_packet
```

The `graphgraph` package root re-exports the common API for external callers,
so `from graphgraph import Graph, retrieve_context, search_nodes` also works.
Prefer the owning-package path for internal code so ownership stays clear.

## Entry Points

| Command | Target |
| --- | --- |
| `graphgraph` | `graphgraph.cli:main` |
| `graphgraph-mcp` | `graphgraph.mcp:main` |
| `python -m graphgraph.mcp` | MCP stdio server |
| `python -m graphgraph.acceptance run --repo <path>` | acceptance harness |
| `python -m graphgraph.acceptance.live_validation` | live validation harness |
