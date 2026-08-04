# Agent Interfaces (L1)

> **Packages:** `cli/`, `mcp/`  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Execution Model and Latency  
> **Integration guide:** [../../guides/integration-interfaces.md](../../guides/integration-interfaces.md)

## 1. Intent

Two transports, **same retrieval core**:

| Transport | Process model | Latency character |
|-----------|---------------|-------------------|
| **CLI** | Cold-start interpreter per invocation | Dominated by process spawn (~100ms+ floor) |
| **MCP (resident)** | Long-lived server; memoized `load_any` | Sub-ms core once warm |

Measured illustration (Flask-scale one-hop relations): CLI end-to-end ~250 ms vs resident ~0.26 ms—mostly interpreter and import, not graph algorithms.

## 2. Decomposition

| Surface | Role |
|---------|------|
| CLI parser / commands | One-shot scripting, scan, doctor, context |
| MCP server / tools | Interactive agent cycles |
| Machine contract | Capability identity for clients |
| Install / skill generation | Client registration (external state may lag repo) |

## 3. Invariants

- **[Ubiquitous]** Benchmarks that time repeated CLI calls SHALL label cold-start; they are not core retrieval latency.
- **[Ubiquitous]** Read-only query tools SHALL not imply mutation or silent full reindex.
- **[Conditional]** IF reporting agent-cycle performance THEN resident transport SHALL be the primary gate (OW-AC-01).

## 4. Open work

OW-AC-01, OW-AC-09, OW-D-03 — [open-work.md](../../open-work.md).
