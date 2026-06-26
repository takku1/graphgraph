---
name: graphgraph
description: Instructions for querying, compressing, and validating codebase context graphs using the global `graphgraph` CLI or `graphgraph-mcp` server. Use this skill when answering structural codebase questions, finding file dependencies, navigating imports/calls, or running context/RAG queries.
---

# GraphGraph Integration Guide & Contract

You are equipped with the **`graphgraph`** codebase context serialization engine. It is fully installed, configured, and registered on the system.

> [!IMPORTANT]
> **ZERO-EXPLORATION CONTRACT**
> Do NOT execute command-line discovery (e.g., `Get-Command graphgraph`, `graphgraph --help`, `final_packet --help`), and do NOT read the `graphgraph` package source files to check how they work. The CLI commands and MCP tools are guaranteed to be present and are fully specified below. Use them directly.

---

## 1. Finding Graph and Policy Files
Before invoking a tool, check for the presence of codebase graphs and policy files in the workspace:
* **Graph Path**: Check for `graphify-out/graph.json` or `.code-review-graph/graph.json`.
* **Policies Path**: Look for `.code-review-graph/policies.json`, `.agents/policies.json`, or a root `policies.json`. (Optional; omit if not found).

---

## 2. MCP Server: `graphgraph-mcp`
The following tools are available on the `graphgraph-mcp` server:

### `plan_context`
Retrieve the optimized packet format and expansion hops for a query class.
* **Arguments**:
  * `query_class` (string, required): One of the RAG strategies.
* **Usage Example**:
  ```json
  {
    "ServerName": "graphgraph",
    "ToolName": "plan_context",
    "Arguments": { "query_class": "blast_radius" }
  }
  ```

### `final_packet`
Generate the compressed, validated context packet containing both active constraints and the expanded graph topology.
* **Arguments**:
  * `graph_path` (string, required): Path to the `graph.json` file.
  * `query_class` (string, required): The query class.
  * `starts` (array of strings, required): Entry point node IDs (e.g. class names, file paths, or function names).
  * `policies_path` (string, optional): Path to the policies file.
  * `query` (string, optional): The natural text query.
  * `paths` (array of strings, optional): Paths referenced by the query (for policy matching).
  * `tags` (array of strings, optional): Task tags (for policy matching).
* **Usage Example**:
  ```json
  {
    "ServerName": "graphgraph",
    "ToolName": "final_packet",
    "Arguments": {
      "graph_path": "graphify-out/graph.json",
      "query_class": "direct_lookup",
      "starts": ["AuthService"],
      "policies_path": ".agents/policies.json"
    }
  }
  ```

### `validate_packet`
Mechanically check that a serialized context packet has valid nodes, edges, relation IDs, and weights.
* **Arguments**:
  * `packet` (string, required): The raw rendered packet string.

---

## 3. Global CLI: `graphgraph`
If you prefer shell execution or need standard output streams, use the global command:

* **Plan Strategy**:
  ```bash
  graphgraph plan --query-class <query_class>
  ```
* **Render Expanded Graph**:
  ```bash
  graphgraph render --graph <graph_path> --query-class <query_class> --starts <node_id> [<node_id>...]
  ```
* **Generate Final Packet** (Constraints + Graph):
  ```bash
  graphgraph final --graph <graph_path> --query-class <query_class> --starts <node_id>... [--policies <policies_path>] [--query "<text>"] [--path <file_path>] [--tag <tag>]
  ```
* **Validate Packet**:
  ```bash
  graphgraph validate --packet <packet_file>
  # OR via stdin:
  cat <packet_file> | graphgraph validate
  ```

---

## 4. Query Class Strategies
Route queries to the correct formatting and depth based on the type of question:

| Query Class | Description / Example Question | Hops | Format | Reason |
| :--- | :--- | :---: | :--- | :--- |
| `direct_lookup` | "What does file `x` do?" or "Show details for class `Y`" | 1 | `gg_max_hybrid` | Needs inline summaries & facts |
| `reverse_lookup` | "Which classes or modules reference class `X`?" | 1 | `gg_max_hybrid` | Needs inline summaries & facts |
| `subsystem_summary` | "Give me a high-level summary of the `auth` module" | 1 | `gg_max_hybrid` | Needs inline summaries & facts |
| `blast_radius` | "If I modify class `X`, what else might break?" | 2 | `gg_max` | Topological traversal; saves 30%+ tokens |
| `multi_hop_path` | "How does class `X` call class `Z`?" | 2 | `gg_max` | Topological traversal; saves 30%+ tokens |
| `negative_query` | "Is class `X` completely isolated/unreferenced?" | 1 | `gg_max` | Pure topological check |

---

## 5. Execution Workflow for Codebase Questions
When the user asks a codebase structure/dependency question:
1. Locate `graphify-out/graph.json` or `.code-review-graph/graph.json`.
2. Map the user's question to a `query_class` (from the table above) and find the starting node ID(s).
3. **Immediately call `final_packet`** via MCP or `graphgraph final` via CLI.
4. Inject the returned output directly into your prompt context.
5. Answer the user's question using the high-fidelity context packet.
