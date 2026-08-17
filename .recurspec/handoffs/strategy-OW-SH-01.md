# Strategy Handoff — OW-SH-01

## Target

- Contract: `docs/architecture/agent-interfaces/cli-transport/SYSTEM.md`
- Ticket: `OW-SH-01`

## Goal

Make exact one-hop lookup as tight as `rg` / `Select-String` from PowerShell:
`graphgraph callers Type::method` with no required flags, compact JSON, and
rg-like exit codes. Do not emit a context packet.

## Non-goals

- OW-AC-03 conceptual recall
- Changing MCP tool names
- Treating CLI spawn time as retrieval latency
- Ranking or packet format work

## Required invariants

- [Event-driven] WHEN the operator asks for exact callers or callees THE SYSTEM SHALL NOT require a `--direction` flag.
- [Event-driven] WHEN the target is missing or ambiguous THE SYSTEM SHALL exit 1 after emitting the compact receipt.
- [Event-driven] WHEN `select --mode exists` is false THE SYSTEM SHALL exit 1.
- [Ubiquitous] Parser construction SHALL stay import-light.

## Test and observation seams

- `tests/test_cli_mcp.py`
- `tests/test_surface_constants.py`

## KEEP gate

Human review required. No independent checker is configured.
