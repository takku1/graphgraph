# GraphGraph vs Graphify

GraphGraph and Graphify now serve different roles in this repository.

GraphGraph owns the native runtime path:

- scan local source and docs into `.graphgraph/graph.gg`;
- maintain incremental symbol/doc graphs;
- retrieve query-specific anchors;
- render compact LLM-facing packets;
- validate packets and saved graphs mechanically;
- expose the workflow through CLI, MCP, and Codex skill/plugin surfaces.

Graphify remains useful as an external graph producer and comparison baseline.
GraphGraph can ingest Graphify output explicitly:

```powershell
graphgraph ingest --input graphify-out/graph.json --output .graphgraph/graph.gg
```

Normal `scan`, `context`, `query`, `final`, skill, and MCP workflows do not read
Graphify outputs unless a user passes a Graphify file to `ingest` or to a command
that accepts an explicit graph path.

## Current Difference

Graphify tends to produce rich, human-readable graph exports. That is useful for
inspection and interop, but verbose as an LLM packet format.

GraphGraph optimizes for the runtime packet path. It keeps rich graph data in
storage, then renders a narrow subgraph in the cheapest format that still passes
mechanical validation and benchmark evidence. The current default policy is:

- `gg_max` for non-empty structural packets;
- `semantic_arrow` mainly for zero-edge or negative-query packets;
- `doc_summary` for docs/install/usage queries where topology is not the main
  evidence.

## Practical Rule

Use GraphGraph for live agent context. Use Graphify output only when importing an
external graph or comparing another graph generator against GraphGraph's native
scanner.
