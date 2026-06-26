# LLM Connection Strategy

The best live LLM interface for `graphgraph` is likely an MCP server.

Reason:

- MCP lets an LLM client call tools without pasting the whole graph into every
  conversation.
- Tools can return narrow packets, not raw databases.
- The server can enforce mechanical validation before returning context.
- The same core can also power a CLI, editor plugin, or Codex skill.

For offline indexing/build/benchmark behavior, a CLI tool is a better fit.

## Recommended Surfaces

### 1. Python Library

Core package:

```python
from graphgraph import Graph, Query, plan_packet
```

Use this for tests, benchmark scripts, and embedding in other tools.

### 2. CLI

Useful commands:

```powershell
python -m graphgraph plan --query-class blast_radius
python -m graphgraph render --format lowlevel
```

The CLI is the easiest way to debug packets and inspect decisions.

### 3. MCP Server

Target tools:

- `graphgraph.plan_context`
- `graphgraph.final_packet`
- later: `graphgraph.validate_packet`

The MCP server should call the same `src/graphgraph` core. It should not have
its own planning logic.

Current command:

```powershell
$env:PYTHONPATH="src"
python -m graphgraph.mcp_server
```

Current tools:

- `plan_context`: returns hop depth and packet type for a query class.
- `final_packet`: returns scoped policy constraints plus the selected graph
  packet.
- `validate_packet`: mechanically validates low-level and SQL packets.

### 4. Plugin / Skill

A Codex or editor plugin can wrap the MCP server or CLI. That is a distribution
surface, not the core architecture.

## Current Decision

Build the core as a normal Python package first. Keep MCP as the official LLM
connection target once the API stabilizes.
