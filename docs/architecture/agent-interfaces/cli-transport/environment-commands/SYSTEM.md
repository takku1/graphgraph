# Environment and Installation Commands (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Report what this installation can actually do — grammar availability, project status, advertised capability identity — and install or verify the distribution artifacts agent clients register; does not answer a retrieval query, write the graph, or own the parser's import budget.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One environment-reporting and artifact-installation family sharing the advertised capability record.

## 3. Interface Contracts

- **Inputs:** `parsed_invocation`, `control_receipt`
- **Outputs:** `environment_report`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Capability identity SHALL be advertised on CLI as well as MCP, per OW-AC-09 and `tests/test_mcp_machine_contract.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** The advertised CLI capability SHALL be derived from the same machine contract the MCP transport advertises, not from a second hand-maintained list.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Environment capability SHALL be reported from a live frontend probe, naming both ready and unavailable languages, rather than from documentation.
  - `EvidenceStage:` Observed
- **[Conditional]** IF generated distribution artifacts are stale THEN a check SHALL fail and name each stale path with its source rather than silently regenerate it.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CEC-001:** `graphgraph doctor` is the authority on environment capability, not documentation. A grammar that failed to install is a runtime fact, and a document claiming otherwise is a defect report waiting to be filed against retrieval.
- **ADR-CEC-002:** CLI capability identity reads the MCP machine contract rather than restating it. ADR-AI-002 makes a one-sided capability a defect, and two independent lists would make that defect invisible until a client noticed.
- **ADR-CEC-003:** The artifact check refuses rather than repairs. A check that silently regenerates makes a stale committed artifact indistinguishable from a current one in CI.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/cli/diagnostics.py`, `src/graphgraph/cli/install.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_distribution_artifacts.py`, `tests/test_project_atlas.py`

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** doctor findings, ready and unavailable grammars, advertised capability record, distribution artifact status.
- **Branching Policy:** isolated candidate; capability parity with MCP is a hard gate (ADR-AI-002).
- **Known granularity gap:** this leaf contributes to the component-level `cli_cold_start_ms` gate but has no metric of its own — capability parity is a correctness check, not a number. No per-child metric has been recorded, and none is asserted here with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — these commands read this repository's own capability record and write this repository's own artifact layouts. Nothing external knows either shape.
- **Selected:** Python 3.10 `argparse` handlers over the in-repo distribution and machine-contract modules; keyring 25.7.0 for credential lookup
- **Standard / protocol:** none for diagnostics; MCP client configuration formats for the installed artifacts
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | A packaging installer (pipx, an OS package) | Installs the tool; it does not register agent-client artifacts or answer "which grammars are ready here". |
  | A generic health-check framework | Would report probe results but not the capability-parity contract, which is the reason this node exists. |
  | Documenting supported languages instead of probing | Exactly the failure ADR-CEC-001 rejects. |

- **Fit gap:** none for identity advertisement. Stale skill installs remain OW-D-03.
- **Seam:** `src/graphgraph/cli/diagnostics.py`
- **Exit cost:** LOW
- **Cost model:** one interpreter spawn per invocation; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unavailable grammar is reported as unavailable rather than assumed present.
- **Open questions:** OW-AC-09, OW-D-03
