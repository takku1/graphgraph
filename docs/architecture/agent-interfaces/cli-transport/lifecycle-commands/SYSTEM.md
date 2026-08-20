# Graph Lifecycle Commands (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Own every CLI path that writes: scan, targeted update, removal, saved-graph validation, conversion, comparison, and packet-cache maintenance; does not answer a retrieval query, own the parser's import budget, or report environment capability.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One write-side command family sharing a single graph-resolution and refusal contract.

## 3. Interface Contracts

- **Inputs:** `parsed_invocation`
- **Outputs:** `lifecycle_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a scan or targeted update would shrink the saved graph unexpectedly THEN THE SYSTEM SHALL refuse and exit with the refusal rather than overwrite the graph.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a removal matches no path in the saved graph THE SYSTEM SHALL exit with that fact rather than report a successful no-op.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A graph published by a lifecycle command SHALL carry a validation result, so an unvalidated write cannot become the active store.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Cache commands SHALL resolve the graph through the same rule the query paths use, so a clear cannot target a different workspace's cache.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CLC-001:** An unexpected shrink is refused rather than written. A scan that silently loses nodes leaves a smaller, internally consistent graph that every downstream check reports as healthy, which is the worst available failure mode.
- **ADR-CLC-002:** A removal that matched nothing is an error, not a no-op. The operator's model of what is in the graph is wrong in that moment, and a success message confirms the wrong model.
- **ADR-CLC-003:** Cache maintenance shares the query paths' graph resolution. A cache keyed differently from the reader it serves has already caused cross-repository entry reuse in this codebase.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/cli/lifecycle.py`, `src/graphgraph/cli/graph_io.py`, `src/graphgraph/cli/cache.py`
- **Test Surface Seam:** `tests/test_cli_mcp.py`, `tests/test_public_contracts.py`

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** scan wall time, node and edge deltas, dropped-path counts, validation result, cache file paths.
- **Branching Policy:** isolated candidate; a refusal path must stay a refusal, never a warning.
- **Known granularity gap:** this leaf contributes to the component-level `cli_cold_start_ms` gate but has no metric of its own; scan throughput is measured by the scanner component, not here. No per-child metric has been recorded, and none is asserted here with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — these handlers translate flags into calls on the in-repo lifecycle services and turn their refusals into exit codes. The behavior worth owning lives in storage and scanner, not in this adapter.
- **Selected:** Python 3.10 `argparse` handlers over the in-repo lifecycle and IO services
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | A build tool (make/just) driving separate steps | Refusal semantics would live in shell exit codes rather than in a typed error the handler can name. |
  | A file-watcher daemon as the only write path | Makes an explicit, scriptable rebuild depend on a resident process; the CLI exists to work without one. |

- **Fit gap:** single-writer. Concurrent writers are arbitrated by runtime build state, not by these commands.
- **Seam:** `src/graphgraph/cli/lifecycle.py`
- **Exit cost:** LOW
- **Cost model:** one interpreter spawn per invocation; local disk only.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a refused write exits non-zero with the reason and leaves the prior graph intact.
- **Open questions:** OW-D-03
