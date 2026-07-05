

# GraphGraph Workspace Rules

You have direct access to the **`graphgraph`** codebase context serialization engine. It is available as a CLI tool (`graphgraph`) and, on platforms with MCP config, as an MCP server (`graphgraph` server).

## Instinctive Tool Guide

When the user asks codebase structure/dependency questions or says "using graphgraph now to build context":
1. **Zero-Exploration Contract:** Immediately check if `.graphgraph/graph.gg` or another native graph exists in the workspace. If it does not exist, immediately run `graphgraph scan --depth symbols --docs` to generate it. Do NOT run custom shell listings or file-discovery loops.
2. **Context Compilation -- preferred (no node IDs needed):** Call `graphgraph/query_context` with a natural-language query. It auto-discovers anchors and returns a ready packet.
3. **Context Compilation -- when you know node IDs:** Call `graphgraph/search_nodes` to confirm the ID, then `graphgraph/final_packet` with the confirmed IDs.
4. **Zero-Hallucination Reasoning:** Rely *only* on the compressed topological packet returned by GraphGraph to understand the project structure, imports, and calls.
5. **No Direct Graph File Inspection:** NEVER read `.graphgraph/graph.gg` directly; treat `.graphgraph/graph.json` as a compatibility/import file only. If you need to verify the graph, call `graphgraph/validate_packet` or trust the scanner output.

### Available MCP Tools
* **`graphgraph/query_context`**: **Preferred.** Natural-language query -> auto-discovered anchors -> graph packet. No node IDs needed.
* **`graphgraph/search_nodes`**: Find node IDs by label, path, or kind substring. Use before `final_packet`.
* **`graphgraph/final_packet`**: Render compressed context packet from known anchor node IDs.
* **`graphgraph/project_status`**: Validate the graph, summarize code/doc balance, package metadata, and optional runtime probes.
* **`graphgraph/plan_context`**: Pass `query_class` to plan the expansion depth.
* **`graphgraph/build_graph`**: Scan a directory. Accepts `exclude_dirs` to skip large external dirs.

### Available CLI Commands
* **Scan**: `graphgraph scan --depth symbols --docs` (default max-nodes=2000)
* **Scan with exclusions**: `graphgraph scan --depth symbols --docs --exclude repos references_temp`
* **Project status**: `graphgraph status --probe`
* **One-step context packet**: `graphgraph context "<text>" --query-class subsystem_summary --show-stats`
* **Natural-language query on an existing graph**: `graphgraph query "<text>" --query-class blast_radius --show-anchors`
* **Known-node packet only**: `graphgraph final --graph <graph_path> --query-class <query_class> --starts <node_id>...`
* **Stable prompt-cache skeleton**: `graphgraph final --stable-skeleton --max-nodes 120`
* **System diagnostics**: `graphgraph doctor`
