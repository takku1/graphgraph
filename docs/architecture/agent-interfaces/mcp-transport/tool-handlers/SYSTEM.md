# Tool Schemas and Handlers (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Declare the advertised MCP tool catalog and implement each handler over the shared retrieval, graph-management, platform, and introspection surfaces; does not frame JSON-RPC, own process residency, or publish the capability record.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One tool catalog whose schemas and handlers share a single argument-validation contract.

## 3. Interface Contracts

- **Inputs:** `query_text`, `context_packet`
- **Outputs:** `tool_result`, `tool_catalog`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Every tool's declared required arguments SHALL be validated at the boundary, naming each missing argument and its allowed values, rather than surfacing an unhandled key error.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a splice or removal tool receives an empty or non-list `paths` argument THE SYSTEM SHALL reject the call rather than fall back to a tree walk.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A graph-mutating tool SHALL return a receipt naming whether a write was performed and the validation result of the graph it published.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Introspection tools SHALL answer from the shared ontology, traversal, frontend, and packet-format catalogs rather than from a second description list.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-MTH-001:** Argument validation is one function driven by each tool's declared schema, not per-handler guards. The observed failure was several handlers doing a bare key access, which returned a cryptic error naming neither the problem nor the fix.
- **ADR-MTH-002:** A splice tool refuses rather than degrades. Falling back to a full tree walk when `paths` is empty turns a caller's mistake into the most expensive operation in the system, disguised as success.
- **ADR-MTH-003:** Introspection reads the same catalogs the engine uses. A hand-maintained tool description drifts from the behavior it describes, and an agent has no way to notice.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/mcp/descriptions.py`, `src/graphgraph/mcp/graph_management.py`, `src/graphgraph/mcp/platform_tools.py`, `src/graphgraph/mcp/retrieval_tools.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_mcp_project_status.py`, `tests/test_mcp_machine_contract.py`

## 7. Measurement Seams

- **Primary Metric:** `resident_exact_query_p95_ms` (target `<=250` ms warm MCP exact relation, `direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** per-tool timings, packet node/edge counts, mutation receipts, freshness classification.
- **Branching Policy:** isolated candidate; CLI parity must remain (ADR-AI-002).
- **Known granularity gap:** this leaf shares the component-level `resident_exact_query_p95_ms` gate, which is asserted over the named session tools rather than per handler. No per-tool metric has been recorded, and none is asserted here with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Fatal fit gap — the handlers expose this repository's own retrieval and graph-lifecycle semantics, which no MCP SDK or generic tool framework knows; and with no MCP SDK in the inventory there is nothing here to WRAP.
- **Selected:** in-repo tool schemas and handlers on Python 3.10 over the shared retrieval, lifecycle, and platform services
- **Standard / protocol:** MCP tool schema (JSON Schema `inputSchema`)
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Official MCP Python SDK decorators | Would be the WRAP if it were already a locked dependency; adding it now is a procurement change, not this leaf's job. |
  | A generic JSON-Schema validation library | The boundary check also enumerates allowed values from the tool's own schema; a validator would report violations without that guidance. |
  | Auto-generating tools from the CLI parser | The recurring schema cost is what the capability ceiling governs; generated descriptions cannot be budgeted. |

- **Fit gap:** MCP defines transport and tool description, not retrieval semantics; the answers these handlers return are owned by the retrieval and storage subsystems.
- **Seam:** `src/graphgraph/mcp/retrieval_tools.py`
- **Exit cost:** LOW — handlers call shared services that the CLI already exercises independently.
- **Cost model:** no hosted spend; work happens inside the resident process.
- **Liability transferred:** tool-schema compatibility with MCP clients.
- **Operational owner:** us
- **Failure mode:** an invalid call is refused with a message naming the missing argument; no partial mutation is performed.
- **Open questions:** OW-AC-01, OW-AC-08
