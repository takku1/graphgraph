# Integration Surfaces

`graphgraph` should not be only one kind of integration. Different parts of the
system belong on different surfaces.

## Recommended Split

| Surface | Best for | Status |
| --- | --- | --- |
| Python library | Shared core logic, tests, embedding elsewhere | started |
| CLI/offline tool | Build, parse, benchmark, inspect packets | started |
| MCP server | Serve narrow context packets to an LLM agent | started |
| Plugin/skill | Product/editor/Codex distribution wrapper | started |

## Why Not MCP For Everything?

MCP is good for live agent calls:

- plan context for this task,
- retrieve anchors from a natural-language query and render a context packet,
- render a final packet from already-known node IDs,
- select scoped policies,
- validate a packet before the model sees it.

MCP is not the best surface for heavy offline work:

- crawling a repo,
- parsing all documents,
- rebuilding indexes,
- benchmarking all packet formats,
- cloning external repositories.

Those are better as CLI/offline tools, similar to how Graphify behaves as an
indexing/build tool.

## Practical Architecture

```text
src/graphgraph core library
  -> CLI / offline tool
       build graphs, parse docs, run benchmarks
  -> MCP server
       serve natural-language query packets and known-node final packets to LLM agents
  -> plugin / skill
       install and call CLI/MCP from a host product
```

The rule: only one implementation of planning/rendering logic, in the Python
library. CLI, MCP, and plugins should be wrappers.

## Current Recommendation

1. Keep benchmark/index/build workflows as CLI tools.
2. Use MCP `query_context` for live LLM context retrieval; use `final_packet`
   only after resolving exact node IDs.
3. Use `graphgraph install --project --platform codex` to generate or refresh
   the repo-local Codex plugin at `plugins/graphgraph`.

## Codex Packaging

Current Codex packaging lives in:

- `plugins/graphgraph/.codex-plugin/plugin.json`
- `plugins/graphgraph/.mcp.json`
- `plugins/graphgraph/skills/graphgraph/SKILL.md`
- `.agents/plugins/marketplace.json`

The plugin is intentionally a wrapper. Planning, scanning, traversal, packet
rendering, and validation stay in `src/graphgraph`; the plugin only teaches
Codex when to use those tools and how to launch the MCP server.

For the local Windows checkout, `.mcp.json` uses an absolute `cwd` and
`uv run --no-sync --project` path so Codex starts the server from the
repository root without trying to replace a currently running console script.
`graphgraph install --project --platform codex` writes those paths for the
current checkout. `python scripts\configure_codex_plugin.py --repo-root
<checkout>` remains available as a repair command after moving or copying the
repo; the Codex integration benchmark includes a temporary-copy probe for this
path rewrite.
