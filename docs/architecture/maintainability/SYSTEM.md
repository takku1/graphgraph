# Maintainability Convergence (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Keep GraphGraph's internal structure changeable without weakening measured runtime behavior; does not own feature design or a demand that every function meet one complexity threshold.

## 2. Sub-System Decomposition

- **[Structural Complexity Ratchet](./structural-ratchet/SYSTEM.md)** — turns the hotspot inventory into a non-regression gate.
- **[Cold Contract Authority](./cold-contract-authority/SYSTEM.md)** — one parser-safe catalog of names and defaults.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `structural_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN maintainability work changes production code THE SYSTEM SHALL run the owning component's correctness and primary-metric gates.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The maintainability programme SHALL reduce or preserve measured structural complexity rather than substitute file-count aesthetics, as checked by `components/maintainability/measure.sh`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF a generic filename names one coherent package-qualified domain abstraction THEN THE SYSTEM SHALL retain it unless a measured ambiguity exists.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-MC-001:** Ratchet the observed baseline; the promoted count is 248.
- **ADR-MC-002:** Decompose at independently testable behavioral phases, not target line counts.
- **ADR-MC-003:** Cold-start behavior is an interface constraint. Removing a duplicate catalog may not reintroduce eager subsystem imports.
- **ADR-MC-004:** This node holds cross-cutting code-health gates only. The retrieval phase contracts it once owned were moved to [Structural Retrieval](../information-retrieval/structural-retrieval/SYSTEM.md), under the domain they implement. A refactoring programme is a reason to create a contract, not a place to keep one; leaving them here forced a reader to consult two subtrees to understand one pipeline.
