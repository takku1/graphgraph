# Source Layout

`src/graphgraph/` is organized by runtime responsibility. Root-level modules
such as `graphgraph.core`, `graphgraph.packets`, `graphgraph.validate`, and
`graphgraph.cache` remain as compatibility import surfaces, but most
implementation now lives in domain packages.

## Domain Packages

- `graph/`: graph model, operations, relation ontology, and traversal policy.
- `scanner/`: file collection, imports, document extraction, and source
  frontends.
- `concepts/`: concept normalization, doc/code alignment, and typed
  interpretation-layer registry.
- `retrieval/`: lexical search, context expansion, activation, budget shaping,
  and connected selection (`selection.py`). `tree_knapsack.py` remains a
  compatibility import for older integrations.
- `planning/`: query plans, packet choices, budgets, graph-shape budgets, and
  policy selection.
- `packets/`: packet renderers and packet/graph validation.
- `runtime/`: runtime caches and session-adjacent helpers.
- `storage/`: native `.gg` binary storage backends.
- `io/`: graph load/save/merge APIs plus graph/policy/lesson path discovery.
- `analysis/`: graph summaries and graph comparisons.
- `services/`: higher-level query/context/snippet/native orchestration.
- `cli/` and `mcp/`: command-line and MCP surfaces. CLI installation/plugin
  generation lives in `cli/install.py`; runtime command handlers live in
  `cli/commands.py`.

## Compatibility Rule

Public import paths are kept stable during refactors. For example:

```python
from graphgraph.core import Graph
from graphgraph.packets import render_packet
from graphgraph.validate import validate_packet
```

Those paths still work, but new internal code should import from the owning
domain package, such as:

```python
from graphgraph.graph.core import Graph
from graphgraph.packets.renderers import render_packet
from graphgraph.packets.validation import validate_packet
```

This keeps external integrations stable while making ownership clearer inside
the codebase.
