---
name: graphgraph
description: Use GraphGraph for codebase context retrieval: one-step graph build/query, dependency lookup, blast radius analysis, status packets, packet validation, or graph-backed source orientation.
---

# GraphGraph Operational Contract

GraphGraph is installed for native codebase context retrieval in Codex, Antigravity, and CLI workflows. Use it to orient on code structure before broad source searches.

> [!IMPORTANT]
> **STEP 0 -- CHECK TOOL AVAILABILITY FIRST**
> The `graphgraph/*` MCP tools only exist if a graphgraph MCP server is registered for *this* client. Many sessions (e.g. Claude Code without project `.mcp.json`) have **no** graphgraph MCP server even when Claude Desktop does. Before following any MCP step, confirm a tool named `graphgraph/query_context` (or similar) is actually available. **If it is not, silently switch to the CLI path below -- do NOT try to translate MCP tool names into CLI flags.** Run `graphgraph doctor` to see per-client MCP status.

> **DEFAULT PATH**
> If MCP tools are available, prefer `graphgraph/query_context`. Otherwise run `graphgraph context "<query>" --query-class <class>`; it builds `.graphgraph/graph.json` if missing, then returns a packet. Leave `max_nodes` unset for normal use so GraphGraph can choose the dynamic query-class and graph-shape budget; pass an explicit cap only for repeatable tests or intentionally small packets.

> **BENCHMARK DISCIPLINE**
> Do not use expected answer keys or benchmark fixture answers as evidence when answering codebase questions. Use only the retrieved graph packet, source files, docs, and explicitly requested command output.

## Decision Rules

1. For natural-language codebase questions, call `graphgraph/query_context` first. Do not preselect node IDs unless the user supplied exact files/symbols.
2. If no graph exists or MCP is unavailable, run `graphgraph context "<query>" --query-class subsystem_summary --show-stats`.
3. For focused implementation work, add `--scope src/path` or use `search_nodes` before `final_packet`.
4. Validate saved graph files with `graphgraph validate-graph`; validate rendered packets with `graphgraph validate`.
5. Treat GraphGraph as orientation evidence. Verify final claims against source files or test output before changing code.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `query_context` | Natural-language query -> anchors -> compressed packet. Best default. |
| `search_nodes` | Resolve file/symbol labels to node IDs for exact follow-up packets. |
| `final_packet` | Render a packet from known node IDs. |
| `project_status` | Validate graph, summarize code/doc balance, package metadata, and optional probes. |
| `build_graph` | Build `.graphgraph/graph.json`; accepts `exclude_dirs`. |
| `validate_packet` | Validate a rendered packet, not a saved graph JSON file. |

## CLI Commands (the real subcommands)

The MCP tool names above are NOT CLI flags. The CLI has distinct subcommands with **disjoint** options -- do not, e.g., pass `--starts` to `query` (it has no such flag). Use this map:

| Need | Subcommand | Anchors | Example |
|------|-----------|---------|---------|
| Ask a natural-language question (auto-finds anchors) | `context` | auto | `graphgraph context "how does retrieval work" --query-class subsystem_summary --show-stats` |
| Same, on an existing graph only (no auto-build) | `query` | auto | `graphgraph query "callers of retrieve_context" --query-class reverse_lookup --show-anchors` |
| Render from node IDs you already know | `final` | `--starts <id>...` | `graphgraph final --query-class blast_radius --starts src_graphgraph_retrieval_context_py` |
| Low-level render from known IDs (no policies) | `render` | `--starts <id>...` | `graphgraph render --query-class direct_lookup --starts <id>` |

Notes: `--starts` exists only on `final` and `render`. `context`/`query` take free text and discover anchors themselves; use `--show-anchors` to see what they picked. Other helpers:

- Project status: `graphgraph status --probe`
- Force rebuild: `graphgraph context "<query>" --rebuild --scan-max-nodes 5000 --show-stats`
- Focus scope: `graphgraph context "<query>" --scope src/graphgraph/retrieval --query-class blast_radius`
- Dynamic sizing: omit `--max-nodes` for production context packets; use `--scan-max-nodes` only to control how much of the repo is indexed.
- Validate a saved graph file: `graphgraph validate-graph` (or bare `graphgraph validate`, which auto-detects `.graphgraph/graph.json`)
- Validate a rendered packet from stdin: `graphgraph query "<query>" --packet gg_max | graphgraph validate`

## Query Classes

| Query Class | Description / Example Question | Hops | Format | Reason |
| :--- | :--- | :---: | :--- | :--- |
| `direct_lookup` | Specific file/symbol details | 1 | `gg_max` | measured token floor |
| `reverse_lookup` | References/callers/users of a symbol | 1 | `gg_max` | measured token floor |
| `subsystem_summary` | High-level status or architecture area | 1 | `gg_max` | measured token floor |
| `blast_radius` | What changes if this is modified? | 2 | `gg_max` | topology-first |
| `multi_hop_path` | How does A reach/call B? | 2 | `gg_max` | path evidence |
| `doc_summary` | README/docs/install/usage summaries | 1 | `doc_summary` | grounded docs, no topology |
| `negative_query` | Is this isolated/missing? | 1 | `semantic_arrow` | minimal evidence |

Format note: `gg_max`/`gg_max_hybrid` use short integer node handles and are the most token-efficient. `sql` also uses integer handles but carries extra `kind`/`path`/`weight` columns, so it is larger than topology-only `gg_max` (typically ~2x on real repos, more when names are long) -- pick it only when you need those columns. Token ratios between formats are repo-dependent; measure on your own codebase with `--show-stats` or `graphgraph compare` rather than assuming fixed multipliers.

## Noise Controls

Default scanning skips generated artifact directories such as `.graphgraph`, `graphify-out`, `.code-review-graph`, `evidence`, `artifacts`, `scratch`, `tmp`, build outputs, vendors, and cloned external repos. Normal install, scan, context, query, and MCP workflows do not invoke Graphify, code-review-graph, or other graph tools; external graph outputs are read only when explicitly passed to `ingest` or a graph-path argument. For project-specific noise, pass `exclude_dirs` in MCP or `--exclude <dir>` in CLI.
