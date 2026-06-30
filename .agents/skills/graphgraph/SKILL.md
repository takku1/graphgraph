---
name: graphgraph
description: Use GraphGraph for codebase context retrieval: one-step graph build/query, dependency lookup, blast radius analysis, status packets, packet validation, or graph-backed source orientation.
---

# GraphGraph Operational Contract

GraphGraph is installed for native codebase context retrieval in Codex, Antigravity, and CLI workflows. Use it to orient on code structure before broad source searches.

> [!IMPORTANT]
> **DEFAULT PATH**
> Prefer the MCP `graphgraph/query_context` tool when available. If MCP is unavailable, run `graphgraph context "<query>" --query-class <class>`; it builds `.graphgraph/graph.json` if missing, then returns a packet.

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

## CLI Fallback

- One-step default: `graphgraph context "<query>" --query-class subsystem_summary --show-stats`
- Project status: `graphgraph status --probe`
- Force rebuild: `graphgraph context "<query>" --rebuild --scan-max-nodes 5000 --show-stats`
- Focus scope: `graphgraph context "<query>" --scope src/graphgraph/retrieval --query-class blast_radius`
- Validate graph: `graphgraph validate-graph`
- Validate packet from stdin: `graphgraph query "<query>" --packet doc_summary | graphgraph validate`

## Query Classes

| Query Class | Description / Example Question | Hops | Format | Reason |
| :--- | :--- | :---: | :--- | :--- |
| `direct_lookup` | Specific file/symbol details | 1 | `gg_max_hybrid` | inline source facts |
| `reverse_lookup` | References/callers/users of a symbol | 1 | `gg_max_hybrid` | reverse evidence |
| `subsystem_summary` | High-level status or architecture area | 1 | `gg_max_hybrid` | balanced summary |
| `blast_radius` | What changes if this is modified? | 2 | `gg_max` | topology-first |
| `multi_hop_path` | How does A reach/call B? | 2 | `gg_max` | path evidence |
| `doc_summary` | README/docs/install/usage summaries | 1 | `doc_summary` | grounded docs, no topology |
| `negative_query` | Is this isolated/missing? | 1 | `semantic_arrow` | minimal evidence |

## Noise Controls

Default scanning skips generated artifact directories such as `.graphgraph`, `graphify-out`, `.code-review-graph`, `evidence`, `artifacts`, `scratch`, `tmp`, build outputs, vendors, and cloned external repos. Normal install, scan, context, query, and MCP workflows do not invoke Graphify, code-review-graph, or other graph tools; external graph outputs are read only when explicitly passed to `ingest` or a graph-path argument. For project-specific noise, pass `exclude_dirs` in MCP or `--exclude <dir>` in CLI.
