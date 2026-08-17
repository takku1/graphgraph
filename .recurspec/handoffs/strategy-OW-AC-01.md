# Strategy Handoff — OW-AC-01

## Target

- Contract: `docs/architecture/agent-interfaces/mcp-transport/SYSTEM.md`
- Ticket: `OW-AC-01`

## Goal

Gate resident exact-query p95 from a reusable measurement module, and
prove a warm session handshake exposes the retrieval tool catalog.

## Non-goals

- Replacing the custom MCP transport with an SDK
- Changing retrieval semantics
- Claiming MCP is faster than CLI without a paired cold/warm study

## Required invariants

- [State-driven] WHILE the process is warm, a second load of the same
  graph path SHALL reuse the memoized object.
- [Ubiquitous] `initialize` then `tools/list` SHALL expose
  `query_relations`, `query_context`, `search_nodes`, and `project_status`.
- [Ubiquitous] Resident exact-query p95 SHALL be computed with a
  documented nearest-rank quantile and recorded against a numeric SLO.

## Test seams

- `tests/test_resident_query.py`
- `components/agent-interfaces/measure.sh`

## KEEP gate

Human review required.
