---
name: graphgraph
description: Use GraphGraph in Codex / Antigravity for structural codebase questions, dependency lookup, blast radius analysis, multi-hop paths, context packet rendering, packet validation, or graph-backed retrieval.
---

# GraphGraph Integration Guide & Contract

You are equipped with the **`graphgraph`** codebase context serialization engine. It is fully installed, configured, and registered on the system.

> [!IMPORTANT]
> **ZERO-EXPLORATION CONTRACT**
> Do NOT execute command-line discovery (e.g., `Get-Command graphgraph`, `graphgraph --help`), and do NOT read the `graphgraph` package source files. The CLI commands and MCP tools are guaranteed to be present and are fully specified below. Use them directly.

## 1. Finding or Generating Graph and Policy Files
Before invoking a tool, check for the presence of codebase graphs and policy files in the workspace:
* **Graph Path**: Check for `.graphgraph/graph.json` or `graphify-out/graph.json` or `.code-review-graph/graph.json`.
* **Policies Path**: Look for `.agents/policies.json` or `.graphgraph/policies.json`.
* **Generate Graph**: If no graph file exists in the workspace, immediately run the scan command to generate it:
  ```bash
  graphgraph scan --depth symbols --docs
  ```

## 2. MCP Server Tools
The following tools are available on the `graphgraph` MCP server:
- `graphgraph/plan_context`: Pass `query_class` to plan the expansion depth.
- `graphgraph/final_packet`: Generates the final compressed context packet. Arguments: `graph_path` (e.g. `.graphgraph/graph.json`), `query_class`, `starts` (node IDs/file paths/class names), `policies_path` (optional), `query` (optional).
- `graphgraph/validate_packet`: Mechanically check that a serialized context packet has valid nodes and edges.

## 3. Global CLI: `graphgraph`
Use the CLI for manual execution:
- `graphgraph plan --query-class <query_class>`
- `graphgraph scan --depth symbols --docs` (generates native graph)
- `graphgraph final --graph <graph_path> --query-class <query_class> --starts <node_id>...` (renders prompt context)

## 4. Query Class Strategies
Route queries to the correct formatting and depth based on the type of question:

| Query Class | Description / Example Question | Hops | Format | Reason |
| :--- | :--- | :---: | :--- | :--- |
| `direct_lookup` | "What does file `x` do?" or "Show details for class `Y`" | 1 | `gg_max_hybrid` | Needs inline summaries & facts |
| `reverse_lookup` | "Which classes or modules reference class `X`?" | 1 | `gg_max_hybrid` | Needs inline summaries & facts |
| `subsystem_summary` | "Give me a high-level summary of the `auth` module" | 1 | `gg_max_hybrid` | Needs inline summaries & facts |
| `blast_radius` | "If I modify class `X`, what else might break?" | 2 | `gg_max` | Topological traversal; saves tokens |
| `multi_hop_path` | "How does class `X` call class `Z`?" | 2 | `gg_max` | Topological traversal; saves tokens |
| `negative_query` | "Is class `X` completely isolated/unreferenced?" | 1 | `gg_max` | Pure topological check |

## 5. Execution Workflow for Codebase Questions
When the user asks a codebase structure/dependency question:
1. Check if `.graphgraph/graph.json` exists; if not, run `graphgraph scan --depth symbols --docs` first.
2. Map the user's question to a `query_class` and find the starting node ID(s).
3. Call `final_packet` MCP tool or run `graphgraph final` to render the context.
4. Inject the context payload directly into your response and answer the user's question.
