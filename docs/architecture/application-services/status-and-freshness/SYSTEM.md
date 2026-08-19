# Project Status and Freshness (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Answer whether the active build can be trusted and describe the project it was built from — freshness against git and the manifest, per-language conventions, and bounded runtime probes; does not build or repair the graph, and does not compile a packet.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One reporting path: classify the build, then describe the project around it.

## 3. Interface Contracts

- **Inputs:** `native_store`, `resident_graph`
- **Outputs:** `freshness_state`, `status_report`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN a service reports project status THE SYSTEM SHALL distinguish a validated active build from a stale one, as checked by `tests/test_mcp_project_status.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** `active_build` SHALL be reported as one of `validated`, `stale`, `invalid`, `unchecked`, or `absent` — never as a bare boolean (OW-AC-02).
  - `EvidenceStage:` Observed
- **[Conditional]** IF no graph is discoverable THEN the report SHALL name a next action rather than return an error alone.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Freshness SHALL be derived from git revision state and manifest file hashes, not from modification times alone.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A runtime probe SHALL be bounded by a timeout, and any probe failure SHALL be reported as a failed probe rather than raised out of the status call.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Per-language project conventions SHALL be declared as data keyed by the scanner's own language names, so a language the scanner parses cannot be silently absent from the conventions table.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-SF-001:** Status collapses validation and freshness into one label. A caller asking "can I trust this build" should not have to join two booleans and guess the precedence — an unvalidated graph is `invalid` regardless of how fresh it is.
- **ADR-SF-002:** Ecosystem conventions are data, not branches. The hand-written form gave a real 108-file Go application zero entry points and 17 of 61 test files while the scan underneath had extracted every symbol correctly, and the same failure was latent for every language that never got a branch.
- **ADR-SF-003:** Probes are bounded and non-fatal. A project's own toolchain is arbitrary code; status reporting must not inherit its ability to hang or crash.
- **ADR-SF-004:** Freshness never refuses an answer, only flags one. The check exists to make staleness visible, and a check that can block is a check callers will find a way to skip.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/services/ecosystems.py`, `src/graphgraph/services/freshness.py`, `src/graphgraph/services/project_status.py`, `src/graphgraph/services/runtime_probes.py`
- **Test Surface Seam:** `tests/test_mcp_project_status.py`, `tests/test_cli_mcp.py`, `tests/test_cycle5_regressions.py`, `tests/test_module_boundaries.py`, `tests/test_project_conventions.py`

## 7. Measurement Seams

- **Primary Metric:** `context_compile_warm_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/application-services/measure.sh`
- **Correctness Backpressure:** `components/application-services/checks.sh`
- **Telemetry Surface:** `active_build` label, freshness detail and scope, changed-path counts, detected ecosystems, probe results and notes.
- **Branching Policy:** isolated candidate; `active_build` classification must stay four-valued plus `unchecked` (OW-AC-02).
- **Known granularity gap:** this leaf shares the component's `context_compile_warm_ms` gate, which does not exercise status reporting at all — `measure.sh` drives `CompilerDriver.compile`. Freshness-check cost is the metric this leaf would want, and it is not gated today.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Fatal fit gap — the question is "is this specific saved graph still true of this specific working tree", which is answerable only against this project's own manifest and scan model; no external tool holds either side of that comparison.
- **Selected:** in-repo status, freshness, conventions, and probe modules on Python 3.10; `tomllib` (with a `tomli` fallback on 3.10) for project metadata
- **Standard / protocol:** git plumbing for revision state; TOML and JSON for project manifests
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Filesystem watcher daemon | A resident process for a question asked once per command, and blind to changes made while it was not running. |
  | Language-server / ecosystem-detection library per language | One dependency per ecosystem to answer questions the scanner's own language table already covers. |
  | `git status` shelling out per call | Already partly the mechanism, but the manifest hash is what distinguishes "touched" from "changed". |
  | Hand-written per-ecosystem branches | The status quo ADR-SF-002 replaced, with a measured failure behind it. |

- **Fit gap:** freshness is git-aware; a non-git working tree falls back to manifest hashes only.
- **Seam:** `src/graphgraph/services/project_status.py`
- **Exit cost:** LOW — the report is a JSON payload; its consumers are this project's own transports.
- **Cost model:** local disk, git, and bounded subprocesses; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an absent or unreadable graph reports `active_build: absent` with a `build_graph` next action.
- **Open questions:** OW-AC-02
