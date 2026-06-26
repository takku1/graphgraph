# Integration Surfaces

`graphgraph` should not be only one kind of integration. Different parts of the
system belong on different surfaces.

## Recommended Split

| Surface | Best for | Status |
| --- | --- | --- |
| Python library | Shared core logic, tests, embedding elsewhere | started |
| CLI/offline tool | Build, parse, benchmark, inspect packets | started |
| MCP server | Serve narrow context packets to an LLM agent | started |
| Plugin/skill | Product/editor/Codex distribution wrapper | later |

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
3. Add plugin/skill packaging only after the core API and MCP tool shape settle.
