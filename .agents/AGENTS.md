

# GraphGraph Workspace Rules

You have direct access to the **`graphgraph`** codebase context serialization engine. It is available as a CLI tool (`graphgraph`) and, on platforms with MCP config, as an MCP server (`graphgraph` server).

## Instinctive Tool Guide

When the user asks codebase structure/dependency questions or says "using graphgraph now to build context":
0. **Check MCP availability first:** The `graphgraph/*` MCP tools exist only if a graphgraph MCP server is registered for *this* client; many sessions have none even when Claude Desktop does. If those tools are not present, use the `graphgraph` CLI instead and do NOT map MCP tool names onto CLI flags (the CLI subcommands `context`/`query`/`final` have different options). `graphgraph doctor` shows per-client MCP status.
1. **Graph-first orientation:** Check if `.graphgraph/graph.gg` exists in the workspace. If it does not exist, run `graphgraph scan --depth symbols --docs` to generate it before broad structural exploration.
2. **Context Compilation — preferred path (no node IDs needed):** Call `graphgraph/query_context` with a natural-language query. It auto-discovers anchors and returns a ready packet. Use this unless you already know exact node IDs.
3. **Context Compilation — when you know node IDs:** Call `graphgraph/search_nodes` first to confirm the ID, then `graphgraph/final_packet` with the confirmed IDs.
4. **Evidence discipline:** Use the compressed topological packet as orientation evidence for project structure, imports, and calls.
5. **Verification:** Do not read `.graphgraph/graph.gg` directly with text tools; it is binary graph data. Validate graph packets with `graphgraph/validate_packet` or `graphgraph validate`, and verify final claims against source files, tests, or explicitly requested command output.

### Available MCP Tools
* **`graphgraph/query_context`**: **Preferred.** Natural-language query → auto-discovered anchors → graph packet. No node IDs needed.
* **`graphgraph/search_nodes`**: Find node IDs by label, path, or kind substring. Use before `final_packet` when you don't know the exact ID.
* **`graphgraph/final_packet`**: Render a compressed context packet from known anchor node IDs. Raises a helpful error (with nearest matches) when node IDs aren't found.
* **`graphgraph/project_status`**: Validate the graph, summarize code/doc balance, package metadata, and optional runtime probes.
* **`graphgraph/plan_context`**: Pass `query_class` to plan the expansion depth.
* **`graphgraph/build_graph`**: Scan a directory and save to `.graphgraph/graph.gg`. Supports `exclude_dirs` to skip large external dirs and `include_dirs` to keep real project dirs that match default skip names.

### Available CLI Commands
* **Scan Directory**: `graphgraph scan --depth symbols --docs` (generates `.graphgraph/graph.gg`, default max-nodes=2000)
* **Scan with exclusions**: `graphgraph scan --depth symbols --docs --exclude repos references_temp`
* **Project status**: `graphgraph status --probe`
* **One-step context packet**: `graphgraph context "<text>" --query-class subsystem_summary --show-stats`
* **Natural-language query on an existing graph**: `graphgraph query "<text>" --query-class blast_radius --show-anchors`
* **Known-node packet only**: `graphgraph final --graph <graph_path> --query-class <query_class> --starts <node_id>...`
* **Stable prompt-cache skeleton**: `graphgraph final --stable-skeleton --max-nodes 120`
* **System diagnostics**: `graphgraph doctor`
