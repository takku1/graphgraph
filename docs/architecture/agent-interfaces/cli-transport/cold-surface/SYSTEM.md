# Cold Command Surface (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Own the process entry point, the cold-import contract every command family is measured against, the shared machine-readable serializer, and the static description commands; does not implement a retrieval answer, mutate a saved graph, or probe the environment.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One entry point and one serializer sharing the cold-import budget they are measured on.

## 3. Interface Contracts

- **Inputs:** `query_text`, `control_receipt`
- **Outputs:** `parsed_invocation`, `transport_response`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN the CLI parser is constructed THE SYSTEM SHALL NOT import planning, representation, scanner, retrieval, platform, `pathspec`, or `asyncio`, as checked by `tests/test_surface_constants.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Cold-start CLI timings SHALL be labelled separately from resident retrieval, as checked by `components/agent-interfaces/measure.sh`.
  - `EvidenceStage:` Measured
- **[Event-driven]** WHEN the process starts THE SYSTEM SHALL reconfigure its standard streams to UTF-8 with replacement, so packet output does not crash on a narrow Windows code page.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Machine-oriented output SHALL default to compact JSON, with indentation only on explicit request.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CCS-001:** Parser construction stays import-light; runtime catalogs project from cold contracts. This is the node that owns ADR-AI-001's cold-path constraint, so every other command family can be judged against one budget rather than each defending its own imports.
- **ADR-CCS-002:** One serializer for machine output. Two JSON writers eventually disagree about separators or ensure_ascii, and an agent parsing the difference sees a transport defect.
- **ADR-CCS-003:** Description commands live here because they answer from static catalogs. Putting them beside a command family that loads a graph would make the cheapest commands pay the most expensive import.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/cli/__init__.py`, `src/graphgraph/cli/__main__.py`, `src/graphgraph/cli/descriptions.py`, `src/graphgraph/cli/output.py`
- **Test Surface Seam:** `tests/test_surface_constants.py`, `tests/test_public_contracts.py`, `tests/test_cli_mcp.py`

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** import weight at parser construction, module count on the cold path.
- **Branching Policy:** isolated candidate; parser-import tests are a hard gate.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — an `argparse` entry point plus a JSON writer. The differentiator is not the CLI, and every framework alternative loses on the one property this node is measured on.
- **Selected:** Python 3.10 `argparse` and `json` from the standard library
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Click / Typer | Extra import weight on the cold path this node measures. |
  | `rich` for output | Pulls a rendering stack into the cold path to format output an agent parses, not reads. |
  | `orjson` | A compiled dependency to save microseconds inside an interpreter-startup-dominated budget. |

- **Fit gap:** `src/graphgraph/cli/parser.py` implements the parser this node's cold-import invariant is asserted about but is not listed in the CLI Transport implementation-file inventory it was decomposed from; the omission is inherited, not introduced here, and this leaf does not claim the file.
- **Seam:** `src/graphgraph/cli/output.py`
- **Exit cost:** LOW
- **Cost model:** one interpreter spawn per invocation; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a heavier import lands on the cold path and the parser-import test fails before latency drifts.
- **Open questions:** OW-D-03
