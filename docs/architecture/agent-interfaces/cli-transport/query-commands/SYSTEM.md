# Query and Planning Commands (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Turn a parsed invocation into a retrieval, planning, evaluation, or platform-compilation answer over an already-saved graph; does not build or mutate the graph, own the parser's import budget, or report on the environment.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One read-only command family over the compiler driver and planner.

## 3. Interface Contracts

- **Inputs:** `parsed_invocation`, `query_text`, `context_packet`
- **Outputs:** `retrieval_result`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN the operator asks for exact callers or callees THE SYSTEM SHALL accept `callers`/`callees` without a `--direction` flag, as checked by `tests/test_cli_mcp.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A query command SHALL defer its retrieval, packet, and platform imports to call time, so registering the command costs nothing on the cold path.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A query command SHALL read the saved graph and SHALL NOT trigger an implicit rebuild.
  - `EvidenceStage:` Unknown

## 5. Architectural Decisions (ADRs)

- **ADR-CQC-001:** These commands import lazily inside their handlers rather than at module scope. The parser must name them to build `--help`, so module-scope imports here would defeat the cold-import contract regardless of how light the entry point is.
- **ADR-CQC-002:** A missing exact target is an exit-1 condition, not an empty success. An agent scripting the CLI distinguishes "no answer" from "no such symbol" by exit code, and collapsing them turns a retrieval bug into a silent empty result.
- **ADR-CQC-003:** Planning, evaluation, and platform compilation sit with retrieval because they all read one saved graph and answer without mutating it; the split that matters is read versus write, not query versus plan.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/cli/retrieval.py`, `src/graphgraph/cli/planning_commands.py`, `src/graphgraph/cli/evaluation.py`, `src/graphgraph/cli/platform.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_relation_latency.py`, `tests/test_platform.py`, `tests/test_public_contracts.py`

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** per-command wall time, packet node/edge counts, plan class and hop count.
- **Branching Policy:** isolated candidate; CLI parity with MCP must remain (ADR-AI-002).
- **Known granularity gap:** this leaf shares the component-level `cli_cold_start_ms` gate rather than carrying a per-command answer-latency metric of its own. No per-child metric has been recorded, and none is asserted here with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable relative to the shared core — these are thin argument-to-driver adapters. The retrieval behavior they expose is owned elsewhere; nothing here is worth procuring.
- **Selected:** Python 3.10 `argparse` handlers over the in-repo compiler driver and planner
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | A generic query-language front end | The instruction set is already shared with MCP; a second grammar would be a second contract to keep in parity. |
  | Shelling out to the MCP server | Makes every scripted query depend on a resident process the CLI exists to be independent of. |

- **Fit gap:** these commands answer from a saved graph; freshness against the working tree is reported, not enforced, by this leaf.
- **Seam:** `src/graphgraph/cli/retrieval.py`
- **Exit cost:** LOW
- **Cost model:** one interpreter spawn per invocation; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a missing target exits 1 rather than returning an empty answer as success.
- **Open questions:** OW-AC-09
