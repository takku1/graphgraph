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

## 3. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Benchmarks that time repeated CLI calls SHALL label cold-start; they are not core retrieval latency.
  - `EvidenceStage: Measured` — Flask-scale one-hop relations: CLI ~250 ms end-to-end versus ~0.26 ms resident.
- **[Ubiquitous]** Read-only query tools SHALL NOT imply mutation or silent full reindex.
  - `EvidenceStage: Observed`.
- **[Conditional]** IF reporting agent-cycle performance THEN resident transport SHALL be the primary gate (OW-AC-01).
  - `EvidenceStage: Measured` (2026-08-05) — `components/agent-interfaces/measure.sh` now gates `resident_exact_query_p95_ms` (previously the script gated only the secondary `cli_cold_start_ms`, and nothing measured the declared primary metric at all). Warm-process `query_relations(direction=callers)` on 300 uniformly-sampled real exact node ids from this project's own ~14k-node graph: **p95 0.06-0.07ms** across three repeated runs (median ~0.015-0.017ms, max 0.18-0.35ms), consistent with the Flask-scale "~0.26ms resident" illustration above. No formal gate threshold recorded yet — this receipt establishes the first baseline for `hypothesis_runner.py` to compare future changes against.
- **[Ubiquitous]** Capability identity SHALL be machine-readable so a client can tell which contract it is talking to (OW-AC-09).
  - `EvidenceStage: Sampled` — `tests/test_mcp_machine_contract.py`.
- **[Conditional]** IF an external client's installed skill lags this repository THEN THE SYSTEM SHALL be described by `graphgraph status`, not by the stale copy.
  - `EvidenceStage: Observed` — OW-D-03; enforced for the shipped skill text by `tests/test_docs_contract.py`.

## 4. ADRs

- **ADR-AI-001:** The resident MCP process is the interactive transport; the CLI is for cold-start and scripting. This mirrors ADR-002 at L0 and is why the two latency figures are never averaged together.
- **ADR-AI-002:** Both transports sit over **one** instruction set. A capability exposed to one and not the other is a defect, not a transport feature.

## 5. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `cli/` (15 modules), `mcp/` (9 modules) |
| **Entry points** | `graphgraph = graphgraph.cli:main`, `graphgraph-mcp = graphgraph.mcp:main` |
| **Test surface** | `tests/test_cli_mcp.py`, `tests/test_mcp_machine_contract.py`, `tests/test_mcp_project_status.py` |
| **Environment probe** | `graphgraph doctor` (`cli/diagnostics.py`) — reports grammar and keyring availability |

## 6. Measurement seams

| | |
|--|--|
| **Primary metric** | Resident exact-query p95 latency (`direction: lower`, OW-AC-01). Measured 2026-08-05: **p95 0.06-0.07ms** (`components/agent-interfaces/measure.sh`, `resident_exact_query_p95_ms`). See §4 invariant above. |
| **Reported separately** | Cold-start process latency — interpreter spawn and import, not graph work |
| **Invariance gate** | Transport-specific absolute budgets plus scale invariance (OW-AC-08) |
| **Response surface** | Machine response ≤1.15x evidence-packet tokens (OW-AC-06) |
| **Receipts** | [agent-cycle tracker](../../evaluation/graybox-cycles/2026-08-02-agent-cycle-efficiency-quality-tracker.md) |

## 7. Technology resolution

- **Decision class:** **ADOPT** (MCP protocol) + **BUILD** (both transports over the shared core)
- **Selected:** Model Context Protocol for the resident server; Python `argparse` for the CLI; `keyring>=24.0.0` for credential lookup
- **Standard / protocol:** MCP — the reason an agent client can register the server without bespoke glue
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | CLI only | Every invocation pays the interpreter and import floor; that cost dominates the actual retrieval by roughly three orders of magnitude at Flask scale |
  | A bespoke HTTP/RPC daemon | Reinvents a transport that agent clients already speak; MCP is the standard here and WRAPping it is cheaper than owning it |
  | Long-lived CLI with a socket | The resident-process win without the ecosystem — clients would each need custom integration |
  | Storing credentials in the repo or env files | `keyring` moves secret storage to the OS keychain and removes the obligation from this project |

- **Fit gap:** MCP defines transport and tool description, not retrieval semantics — query classes, budgets, and packet formats remain ours.
- **BUILD justification:** the transports are thin; the core they share is the differentiator. Neither transport is itself a BUILD claim.
- **Seam:** `mcp/machine_contract.py` (capability identity), `cli/parser.py` (argument surface)
- **Exit cost:** **LOW** for MCP — the protocol is a boundary, and the CLI already proves the core runs without it.
- **Operational owner:** us (both processes are local; no hosted component)
- **Failure mode:** resident server unavailable ⇒ the CLI path still answers, at cold-start latency.
- **Open questions:** OW-AC-01, OW-AC-08/09, OW-D-03 — [open-work.md](../../open-work.md)
