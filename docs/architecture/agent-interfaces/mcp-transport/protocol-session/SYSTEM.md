# Protocol Session and Capability Identity (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Frame JSON-RPC requests onto handlers, keep the resident process warm enough to meet the interactive latency SLO, and publish a machine-readable capability record for the whole tool surface; does not implement a tool's answer or own retrieval semantics.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One stdio session loop, one dispatch table, and one capability record measured by one residency SLO.

## 3. Interface Contracts

- **Inputs:** `control_receipt`, `tool_result`, `tool_catalog`
- **Outputs:** `transport_response`, `capability_identity`

## 4. Invariants (EARS + Epistemic Stage)

- **[State-driven]** WHILE the server process is warm THE SYSTEM SHALL reuse the memoized graph load across tools, as checked by `components/agent-interfaces/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Capability identity SHALL be machine-readable on the MCP envelope via `tests/test_mcp_machine_contract.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a handler raises THEN THE SYSTEM SHALL return a JSON-RPC error carrying the request id rather than terminating the session.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN an unsupported JSON-RPC method arrives THE SYSTEM SHALL answer with an error rather than silently ignore it.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The recurring machine-facing tool contract SHALL stay under a declared character ceiling, so the advertised surface cannot grow without a recorded decision.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The resident session SHALL name the exact tools its latency SLO is asserted over, rather than claiming a whole-surface guarantee.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-MPS-001:** Dispatch is a separate module from the handlers it calls, and resolves them at call time. Tests and integrations patch handler symbols; a dispatch table bound at import would make those patches silently ineffective.
- **ADR-MPS-002:** Residency is a process-lifetime property, so the latency SLO belongs here rather than on any one tool. The gate is set well above the measured floor so a slower machine fails only on a real regression, not on noise.
- **ADR-MPS-003:** Capability identity is one record with a ceiling on its recurring size. The advertised surface is paid for on every session, so growth is a decision, not a side effect of adding a tool.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/mcp/__init__.py`, `src/graphgraph/mcp/__main__.py`, `src/graphgraph/mcp/dispatch.py`, `src/graphgraph/mcp/machine_contract.py`, `src/graphgraph/mcp/server.py`, `src/graphgraph/benchmark/resident_query.py`
- **Test Surface Seam:** `tests/test_mcp_machine_contract.py`, `tests/test_resident_query.py`, `tests/test_cli_mcp.py`

## 7. Measurement Seams

- **Primary Metric:** `resident_exact_query_p95_ms` (target `<=250` ms warm MCP exact relation, `direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** capability identity, load fingerprint, session tool catalog, per-request timings.
- **Branching Policy:** isolated candidate; CLI parity must remain (ADR-AI-002).

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Fatal fit gap — the wire standard is MCP, but no MCP SDK is locked in this repository, so the stdio session, dispatch, and capability identity are custom. A WRAP over a library that is not in the inventory would invent a procurement.
- **Selected:** in-repo MCP stdio session on Python 3.10; keyring 25.7.0 for credential lookup
- **Standard / protocol:** MCP over JSON-RPC 2.0
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Official MCP Python SDK | Would be the WRAP if it were already a locked dependency; adding it now is a procurement change, not this leaf's job. |
  | Bespoke HTTP/RPC daemon | Reinvents a transport agent clients already speak. |
  | Long-lived CLI socket | Resident win without the ecosystem. |
  | An ASGI/RPC framework for framing | Brings a server stack for a line-delimited stdio loop inside a warm-latency budget. |

- **Fit gap:** MCP defines transport and tool description, not retrieval semantics.
- **Seam:** `src/graphgraph/mcp/machine_contract.py`
- **Exit cost:** LOW — the protocol is a boundary; the CLI already proves the core runs without it.
- **Cost model:** no hosted spend; one local long-lived process.
- **Liability transferred:** protocol compatibility with MCP clients.
- **Operational owner:** us
- **Failure mode:** a handler exception becomes a JSON-RPC error on that request; the session survives and the CLI remains available if the server does not.
- **Open questions:** OW-AC-01, OW-AC-08
