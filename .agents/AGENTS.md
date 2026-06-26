# GraphGraph Workspace Rules

You have direct access to the **`graphgraph`** codebase context serialization engine. It is fully installed and registered on this system as both a CLI tool (`graphgraph`) and an MCP server (`graphgraph` server).

## Instinctive Tool Guide

Use `graphgraph` to retrieve highly optimized, token-efficient codebase context packets for LLM queries instead of traditional vector search or raw file dumps.

### 1. Available MCP Tools
* **`graphgraph/plan_context`**: Pass `query_class` (e.g. `blast_radius`, `direct_lookup`, `multi_hop_path`) to plan the expansion depth.
* **`graphgraph/final_packet`**: Generates the final compressed context packet containing graph topology and active constraints.
  - Arguments: `graph_path` (usually `.graphgraph/graph.json`), `query_class`, `starts` (list of node/file IDs).

### 2. Available CLI Commands
* **Scan Directory**: `graphgraph scan --directory . --depth symbols --output .graphgraph/graph.json`
* **Query anchors**: `graphgraph query "what is the blast radius of stats" --show-anchors`
* **Render/Print Graph**: `graphgraph render --query-class <query_class> --starts <node_id>...`
* **Render Final LLM packet**: `graphgraph final --graph <graph_path> --query-class <query_class> --starts <node_id>...`
* **Doctor Diagnostics**: `graphgraph doctor`

### 3. Strategy Routing
- **File summaries / details**: Use `direct_lookup` (1 hop, `gg_max_hybrid` format).
- **Caller references**: Use `reverse_lookup` (1 hop, `gg_max_hybrid` format).
- **Impact/Blast radius**: Use `blast_radius` (2 hops, `gg_max` format).
- **Call pathways**: Use `multi_hop_path` (2 hops, `gg_max` format).

When answering architectural or dependency questions, immediately retrieve the context packet using `graphgraph/final_packet` or `graphgraph final` instead of exploring files manually.
