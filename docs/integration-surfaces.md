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
- render a final packet,
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
       serve final packets to LLM agents
  -> plugin / skill
       install and call CLI/MCP from a host product
```

The rule: only one implementation of planning/rendering logic, in the Python
library. CLI, MCP, and plugins should be wrappers.

## Current Recommendation

1. Keep benchmark/index/build workflows as CLI tools.
2. Use MCP for live LLM context retrieval.
3. Use the repo-local Codex plugin at `plugins/graphgraph` for installable
   Codex distribution once the local checkout path is configured.

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
`uv --project` path so Codex starts the server from the repository root. Run
`python scripts\configure_codex_plugin.py --repo-root <checkout>` after moving
or copying the repo; the Codex integration benchmark includes a temporary-copy
probe for this path rewrite.
