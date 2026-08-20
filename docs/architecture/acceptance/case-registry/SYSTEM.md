# Case Registry and Ground Truth (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Register the canonical GG10-LC cases, hold their sealed ground truth, and build the disposable fixtures a scan-level or edit-loop-level case needs; does not drive the probe, compute a gate verdict, or run a live external repository.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One task registry whose case implementations share a single sealed-truth data model.

## 3. Interface Contracts

- **Inputs:** `context_packet`
- **Outputs:** `acceptance_task_set`, `case_result`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Ground truth SHALL be used only to score a produced packet, never as a retrieval seed.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a case's ground truth is not mechanically codified THEN its task SHALL be registered `pending` rather than counted as a pass.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A case whose property is scan-level or edit-loop-level SHALL build its own disposable fixture rather than mutating the target repository.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a name has two owners THE SYSTEM SHALL NOT let an unqualified query return one owner with full confidence, since a caller cannot tell a decisive answer from an arbitrary pick.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-ACR-001:** Cases are named against recorded defects (GG10-LC-*), so the registry is an inventory of observed failures rather than a wish list.
- **ADR-ACR-002:** Sealed truth lives on the task, not in the case body, so the one module that could leak an expected answer back into retrieval is the one module reviewed for it.
- **ADR-ACR-003:** A self-contained case owns its fixture. Cases that assert about scan boundaries, incremental splices, or transport parity must be able to fail on a machine that has no copy of the canonical target repository.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/acceptance/model.py`, `src/graphgraph/acceptance/tasks.py`, `src/graphgraph/acceptance/affected_tests_case.py`, `src/graphgraph/acceptance/boundary.py`, `src/graphgraph/acceptance/cache_latency.py`, `src/graphgraph/acceptance/delete_rename.py`, `src/graphgraph/acceptance/docs_case.py`, `src/graphgraph/acceptance/incremental.py`, `src/graphgraph/acceptance/parity.py`, `src/graphgraph/acceptance/qualification.py`, `src/graphgraph/acceptance/scope_case.py`
- **Test Surface Seam:** `tests/test_acceptance.py`, `tests/test_acceptance_exec.py`

## 7. Measurement Seams

- **Primary Metric:** `acceptance_pass_rate` (target `1.0` on active cases, `direction: higher`)
- **Evaluation Gate Path:** `components/acceptance/measure.sh`
- **Correctness Backpressure:** `components/acceptance/checks.sh`
- **Telemetry Surface:** registered task ids, per-case severity and status, ground-truth symbol sets.
- **Branching Policy:** isolated candidate; missing corpus yields no verdict, not a pass.
- **Known granularity gap:** this leaf shares the component-level `acceptance_pass_rate` gate rather than carrying a registry-specific metric (for example ground-truth staleness). No per-child metric has been recorded, and none is asserted here with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the sealed task set *is* the project's standard of proof, and a purchased corpus would measure someone else's defects.
- **Selected:** in-repo task registry and case fixtures on Python 3.10
- **Standard / protocol:** none — the task set is project-specific
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | SWE-bench | Measures patch success, not context-representation cost. |
  | A generic fixture library | The cases assert about scan boundaries and splice identity, not about test data shapes. |
  | Recording the target repository as a vendored fixture | Freezes the very repository whose drift these cases exist to catch. |

- **Fit gap:** the canonical corpus is one external repository; rotating multi-language qualification is OW-AC-10.
- **Seam:** `src/graphgraph/acceptance/tasks.py`
- **Exit cost:** LOW — the registry observes the public surface and holds plain data.
- **Cost model:** local runs; temporary fixture directories only.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a missing target corpus leaves the case `pending` rather than defaulting to a pass.
- **Open questions:** OW-AC-10
