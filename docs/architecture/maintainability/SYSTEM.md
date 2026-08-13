# Maintainability Convergence (L1)

## 1. System Intent & Responsibility

Keep GraphGraph's internal structure changeable without weakening its measured
runtime behavior; does not own feature design, formatting preferences, or a
repository-wide demand that every function satisfy one arbitrary complexity
threshold.

## 2. Sub-System Decomposition

- **[Structural Complexity Ratchet](./structural-ratchet/SYSTEM.md)** — turns the observed hotspot inventory into non-regression telemetry.
- **[Cold Contract Authority](./cold-contract-authority/SYSTEM.md)** — removes mirrored transport-name authorities while preserving parser cold start.
- **[Retrieval Orchestration](./retrieval-orchestration/SYSTEM.md)** — separates the highest-complexity measured hot path at behavioral phase boundaries.

## 3. Interface Contracts

- **Inputs:** Python source, architecture contracts, the locked development toolchain, and existing component measurements.
- **Outputs:** enforceable structural receipts, single-authority cold catalogs, and smaller orchestration modules with unchanged public results.

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN maintainability work changes production code THE SYSTEM SHALL run the owning component's correctness and primary-metric gates.
  - `EvidenceStage: Observed` — `components/*/{checks,measure}.sh` and `harness/hypothesis_runner.py`.
- **[Ubiquitous]** The maintainability programme SHALL reduce or preserve measured structural complexity rather than substitute file-count or line-count aesthetics.
  - `EvidenceStage: Measured` — the initial Ruff inventory reported 249 diagnostics; the retrieval decomposition lowered the promoted baseline to 248.
- **[Conditional]** IF a generic filename names one coherent package-qualified domain abstraction THEN THE SYSTEM SHALL retain it unless a measured ambiguity exists.
  - `EvidenceStage: Observed` — `tests/test_module_boundaries.py` already verifies body ownership rather than filename fashion.

## 5. Architectural Decisions (ADRs)

- **ADR-MC-001:** Ratchet the observed baseline; the initial 249-count inventory is now superseded by the promoted best-known count of 248.
- **ADR-MC-002:** Decompose at independently testable behavioral phases, not at target line counts.
- **ADR-MC-003:** Cold-start behavior is an interface constraint. Removing a duplicate catalog may not reintroduce eager subsystem imports.
