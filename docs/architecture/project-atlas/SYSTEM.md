# Project Atlas (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Build a derived orientation artifact so an agent can answer where to start without dumping the full graph; does not become a second source of truth or a default unmeasured summary.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Atlas construction over the existing IR.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `atlas_artifact`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Atlas APIs SHALL be promoted only with held-out navigation tasks, as checked by `tests/test_navigation_eval.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF atlas claims reduce tokens THEN quality on orientation tasks SHALL NOT regress, as checked by `tests/test_navigation_eval.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** An orientation answer SHALL cite graph evidence rather than summarizing from file names alone.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-PA-001:** The atlas is rebuilt from the IR so it cannot drift into an independent store.
- **ADR-PA-002:** "Where do I start?" is a retrieval query with its own evaluation, not a templated report.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/services/project_atlas.py`, `src/graphgraph/analysis/navigation.py`.
- **Test Surface Seam:** `tests/test_navigation_eval.py`, `tests/test_project_atlas.py`, `tests/test_project_conventions.py`

## 7. Measurement Seams

- **Primary Metric:** `orientation_task_success` (`direction: higher`)
- **Correctness Backpressure:** `components/project-atlas/checks.sh`
- **Telemetry Surface:** language/runtime stratum coverage and tokens to first useful orientation.
- **Branching Policy:** isolated candidate; panel existence is not a substitute for scored orientation success (OW-AC-10).

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — cheap graph-derived orientation is the claim under test against README-plus-directory-tree.
- **Selected:** in-repo atlas construction on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | LLM-generated repository wikis | A model call per repository; stale when code moves. |
  | README plus directory tree | The free baseline the atlas must beat. |
  | Community-detection libraries | Clustering primitives already exist in the IR. |

- **Fit gap:** orientation-task success is not yet scored across the ≥5-language panel (OW-AC-10).
- **Seam:** `src/graphgraph/services/project_atlas.py::build_project_atlas`
- **Exit cost:** LOW — derived artifact.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** with no validated active graph the atlas is unavailable rather than approximate.
- **Open questions:** OW-AC-10
