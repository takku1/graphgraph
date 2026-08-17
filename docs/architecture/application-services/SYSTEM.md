# Application Services (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Orchestrate compile, cache, freshness, and control receipts above retrieval and planning; does not re-implement ranking or packet encoding.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One `CompilerDriver` seam for all transports.

## 3. Interface Contracts

- **Inputs:** `query_text`, `native_store`, `task_subgraph`
- **Outputs:** `control_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A process-local graph cache SHALL be reused across service calls in a resident process, as checked by `components/application-services/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a packet cache key is computed THEN it SHALL exclude the tool's own `.graphgraph/` artifacts, as checked by `tests/test_control.py`.
  - `EvidenceStage:` Measured
- **[Event-driven]** WHEN a service reports project status THE SYSTEM SHALL distinguish a validated active build from a stale one, as checked by `tests/test_mcp_project_status.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Transport adapters SHALL NOT reproduce the compiler-driver schedule.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-AS-001:** Services orchestrate; they do not re-implement retrieval or planning.
- **ADR-AS-002:** `CompilerDriver.compile(DriverRequest)` is the single external compile seam.
- **ADR-AS-003:** Anchor discovery is the service's job, not the caller's.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/services/__init__.py`, `src/graphgraph/services/cache_identity.py`, `src/graphgraph/services/compiler_driver.py`, `src/graphgraph/services/context.py`, `src/graphgraph/services/control.py`, `src/graphgraph/services/ecosystems.py`, `src/graphgraph/services/freshness.py`, `src/graphgraph/services/lifecycle.py`, `src/graphgraph/services/project_status.py`, `src/graphgraph/services/query.py`, `src/graphgraph/services/response_surface.py`, `src/graphgraph/services/runtime_probes.py`, `src/graphgraph/services/snippets.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_context_compiler.py`, `tests/test_control.py`, `tests/test_mcp_project_status.py`, `tests/test_public_contracts.py`, `tests/test_response_surface.py`

## 7. Measurement Seams

- **Primary Metric:** `resident_compile_ms` (`direction: lower`); cache hit rate (`direction: higher`)
- **Evaluation Gate Path:** `components/application-services/measure.sh`
- **Correctness Backpressure:** `components/application-services/checks.sh`
- **Telemetry Surface:** freshness state, cache identity, compile timings, workflow receipts.
- **Branching Policy:** isolated candidate; empty source delta must remain fresh (OW-AC-02).

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** The compiler driver creates one schedule across CLI, MCP, HTTP, Python, and acceptance callers. A workflow framework would add vocabulary without removing a decision.
- **Selected:** in-repo service modules on Python 3.10, stdlib only
- **Standard / protocol:** none — the protocol boundary is Agent Interfaces
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Workflow / orchestration framework | A handful of sequential calls; extra vocabulary, no decision removed. |
  | Task queue | Operations are synchronous and sub-second on the resident path. |
  | Pushing orchestration into CLI/MCP | Duplicates the schedule across transports. |

- **Fit gap:** CLI capability-identity parity with MCP is still open (OW-AC-09).
- **Seam:** `src/graphgraph/services/compiler_driver.py`
- **Exit cost:** LOW — internal; no external contract depends on its shape.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a missing or invalid active graph surfaces through `project_status` with a re-scan instruction.
- **Open questions:** OW-AC-02, OW-Q08
