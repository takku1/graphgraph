# Compile Request Path (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Run the single `CompilerDriver` schedule from a request to a packet, a control receipt, and a response envelope that fits its budget; does not build or validate the saved graph, decide cache identity, or report project status.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One schedule shared by every transport, with the read-only query, snippet, and control renderers it dispatches to.

## 3. Interface Contracts

- **Inputs:** `query_text`, `task_subgraph`, `resident_graph`, `cache_identity`, `freshness_state`
- **Outputs:** `control_receipt`, `response_envelope`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A process-local graph cache SHALL be reused across service calls in a resident process, as checked by `components/application-services/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a machine JSON envelope exceeds the response-to-packet ratio THEN the clamp SHALL drop advisory fields only, keeping `control`, `anchors`, `query_class`, and `workflow` (OW-D-04).
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN advisory fields are dropped to meet the ratio THE SYSTEM SHALL record the clamp and the dropped keys in the envelope's `workflow.surface`.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a control receipt does not begin with the `CONTROL_VERSION` tag THEN parsing SHALL reject it rather than infer a shape.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Control gates SHALL be rendered and parsed in one fixed order, so a receipt is comparable across runs.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The query facade SHALL NOT infer a mutation from query text; a graph refresh happens only when the caller explicitly asks for one.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Freshness SHALL be checked on every query with no opt-out, and SHALL flag staleness rather than refuse the answer.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CR-001:** `CompilerDriver.compile(DriverRequest)` is the single external compile seam. Every transport — CLI, MCP, HTTP, Python, acceptance — enters here, so a scheduling change lands once.
- **ADR-CR-002:** Anchor discovery is the service's job, not the caller's. A caller that must supply node IDs cannot ask a natural-language question, which is the interface this project is for.
- **ADR-CR-003:** Indentation is not evidence. The response clamp trims presentation and advisory provenance before it trims anything a machine client dispatches on — a fallback that is valid JSON but missing routing keys is a surface defect, not a smaller answer.
- **ADR-CR-004:** The control receipt is a fixed-order, versioned string rather than a free-form dict, so two runs can be diffed without a schema negotiation.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/services/__init__.py`, `src/graphgraph/services/compiler_driver.py`, `src/graphgraph/services/context.py`, `src/graphgraph/services/control.py`, `src/graphgraph/services/query.py`, `src/graphgraph/services/response_surface.py`, `src/graphgraph/services/snippets.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_context_compiler.py`, `tests/test_control.py`, `tests/test_cycle5_regressions.py`, `tests/test_public_contracts.py`, `tests/test_query_compiler.py`, `tests/test_response_surface.py`

## 7. Measurement Seams

- **Primary Metric:** `context_compile_warm_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/application-services/measure.sh`
- **Correctness Backpressure:** `components/application-services/checks.sh`
- **Telemetry Surface:** compile timings, control receipt gates, response-to-packet ratio and clamp record, anchor counts.
- **Branching Policy:** isolated candidate; `components/application-services/measure.sh` measures this leaf directly — it drives `CompilerDriver.compile` — so a regression here is visible in the component metric.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the driver creates one schedule across CLI, MCP, HTTP, Python, and acceptance callers, and the response-surface clamp is a project-specific budget contract no framework expresses.
- **Selected:** in-repo service modules on Python 3.10, stdlib only
- **Standard / protocol:** none — the protocol boundary is Agent Interfaces
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Workflow / orchestration framework | A handful of sequential calls; extra vocabulary, no decision removed. |
  | Task queue | Operations are synchronous and sub-second on the resident path. |
  | Pushing orchestration into CLI/MCP | Duplicates the schedule across transports — the exact thing the fourth invariant forbids. |
  | A generic response-size middleware | Trims by bytes without knowing which keys a machine client dispatches on. |

- **Fit gap:** CLI capability-identity parity with MCP is still open (OW-AC-09).
- **Seam:** `src/graphgraph/services/compiler_driver.py`
- **Exit cost:** LOW — internal; no external contract depends on its shape.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a missing or invalid active graph surfaces as an actionable receipt with a re-scan instruction rather than an exception.
- **Open questions:** OW-AC-09, OW-D-04, OW-Q08
