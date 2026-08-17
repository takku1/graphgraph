# MCP Transport (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Serve the shared instruction set from a long-lived process over the Model Context Protocol; does not own retrieval semantics, packet catalogs, or implicit graph rebuilds.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** The server speaks MCP; there is no MCP SDK in the inventory, so the transport is custom code over the protocol.

## 3. Interface Contracts

- **Inputs:** `query_text`, `context_packet`, `control_receipt`
- **Outputs:** `transport_response`

## 4. Invariants (EARS + Epistemic Stage)

- **[State-driven]** WHILE the server process is warm THE SYSTEM SHALL reuse the memoized graph load across tools, as checked by `components/agent-interfaces/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Capability identity SHALL be machine-readable on the MCP envelope via `tests/test_mcp_machine_contract.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a tool is read-only THEN it SHALL NOT trigger a silent full reindex.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-MCP-001:** Adopt MCP rather than a bespoke HTTP/RPC daemon so existing agent clients can register the server.
- **ADR-MCP-002:** Residency is a process-lifetime property, not a missing component.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/mcp/__init__.py`, `src/graphgraph/mcp/__main__.py`, `src/graphgraph/mcp/descriptions.py`, `src/graphgraph/mcp/dispatch.py`, `src/graphgraph/mcp/graph_management.py`, `src/graphgraph/mcp/machine_contract.py`, `src/graphgraph/mcp/platform_tools.py`, `src/graphgraph/mcp/retrieval_tools.py`, `src/graphgraph/mcp/server.py`, `src/graphgraph/benchmark/resident_query.py`
- **Test Surface Seam:** `tests/test_mcp_machine_contract.py`, `tests/test_mcp_project_status.py`, `tests/test_cli_mcp.py`, `tests/test_resident_query.py`.

## 7. Measurement Seams

- **Primary Metric:** `resident_exact_query_p95_ms` (target `<=250` ms warm MCP exact relation, `direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** capability identity, load fingerprint, per-tool timings.
- **Branching Policy:** isolated candidate; CLI parity must remain (ADR-AI-002).

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** The wire standard is MCP, but no MCP SDK is locked in this repository. The stdio server, tool dispatch, and capability identity are custom. A WRAP over a missing library would invent a procurement.
- **Selected:** in-repo MCP stdio server on Python 3.10; keyring 25.7.0 for credential lookup
- **Standard / protocol:** MCP
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | CLI only | Every invocation pays the interpreter floor; ~1000x slower than resident at Flask scale. |
  | Official MCP Python SDK | Would be the WRAP if it were already a locked dependency; adding it now is a procurement change, not this leaf's job. |
  | Bespoke HTTP/RPC daemon | Reinvents a transport agent clients already speak. |
  | Long-lived CLI socket | Resident win without the ecosystem. |

- **Fit gap:** MCP defines transport and tool description, not retrieval semantics.
- **Seam:** `src/graphgraph/mcp/machine_contract.py`
- **Exit cost:** LOW — the protocol is a boundary; the CLI already proves the core runs without it.
- **Cost model:** no hosted spend; one local long-lived process.
- **Liability transferred:** protocol compatibility with MCP clients.
- **Operational owner:** us
- **Failure mode:** resident server unavailable; CLI still answers at cold-start latency.
- **Open questions:** OW-AC-01, OW-AC-08
