# CLI Transport (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Expose the shared instruction set as a one-shot process for scripting, scan, and diagnostics; does not own retrieval algorithms or claim CLI latency as core retrieval latency.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Argparse dispatch over the compiler driver.

## 3. Interface Contracts

- **Inputs:** `query_text`, `context_packet`, `control_receipt`
- **Outputs:** `transport_response`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN the CLI parser is constructed THE SYSTEM SHALL NOT import planning, representation, scanner, retrieval, platform, `pathspec`, or `asyncio`, as checked by `tests/test_surface_constants.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Capability identity SHALL be advertised on CLI as well as MCP, per OW-AC-09 and `tests/test_mcp_machine_contract.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Cold-start CLI timings SHALL be labelled separately from resident retrieval, as checked by `components/agent-interfaces/measure.sh`.
  - `EvidenceStage:` Measured
- **[Event-driven]** WHEN the operator asks for exact callers or callees THE SYSTEM SHALL accept `callers`/`callees` without a `--direction` flag, as checked by `tests/test_cli_mcp.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN an exact lookup target is missing or `select --mode exists` is false THE SYSTEM SHALL exit 1, as checked by `tests/test_cli_mcp.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-CLI-001:** Parser construction stays import-light; runtime catalogs project from cold contracts.
- **ADR-CLI-002:** `graphgraph doctor` is the authority on environment capability, not documentation.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/cli/__init__.py`, `src/graphgraph/cli/__main__.py`, `src/graphgraph/cli/cache.py`, `src/graphgraph/cli/descriptions.py`, `src/graphgraph/cli/diagnostics.py`, `src/graphgraph/cli/evaluation.py`, `src/graphgraph/cli/graph_io.py`, `src/graphgraph/cli/install.py`, `src/graphgraph/cli/lifecycle.py`, `src/graphgraph/cli/output.py`, `src/graphgraph/cli/planning_commands.py`, `src/graphgraph/cli/platform.py`, `src/graphgraph/cli/retrieval.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_public_contracts.py`, `tests/test_relation_latency.py`, `tests/test_surface_constants.py`

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** import weight, doctor findings, capability identity.
- **Branching Policy:** isolated candidate; parser-import tests are a hard gate.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable relative to the shared core — argparse dispatch plus cold catalogs. The differentiator is not the CLI itself.
- **Selected:** Python 3.10 `argparse`; keyring 25.7.0 for credential lookup
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Click / Typer | Extra import weight on the cold path this node measures. |
  | Making CLI the only transport | Pays the interpreter floor on every interactive query. |

- **Fit gap:** none for identity advertisement. Stale skill installs remain OW-D-03.
- **Seam:** `src/graphgraph/cli/parser.py` 
- **Exit cost:** LOW
- **Cost model:** one interpreter spawn per invocation; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** CLI remains available when MCP is not; answers at cold-start latency.
- **Open questions:** OW-AC-09, OW-D-03
