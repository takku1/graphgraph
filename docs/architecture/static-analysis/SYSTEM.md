# Static Analysis (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Turn a repository and optional documents into graph IR emissions through deterministic language frontends and name resolution; does not own runtime tracing, packet encoding, or a compiler-grade whole-program fixpoint.

## 2. Sub-System Decomposition

- **[Language Frontends](./language-frontends/SYSTEM.md)** — parse source and documents into syntax IR.
- **[Name Resolution](./name-resolution/SYSTEM.md)** — bind call sites to callees from typed local facts.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `extracted_nodes`, `extracted_edges`, `scan_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Unknown receivers SHALL remain explicit; name-only guess edges are not trusted topology.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a tree-sitter grammar cannot be loaded THEN THE SYSTEM SHALL record the reason and skip that language rather than abort the scan.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Runtime `observed_calls` SHALL keep provenance distinct from static edges.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-SA-001:** Tree-sitter first; compiler-grade tiers only as measured secondary paths (RF-03).
- **ADR-SA-002:** Bounded k-hop obligation discharge, not a whole-program fixpoint by default.
- **ADR-SA-003:** Grammar loading is lazy and failure-tolerant so a missing grammar degrades one language, never the scan.
