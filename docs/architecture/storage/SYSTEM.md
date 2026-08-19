# Persistent Storage (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Persist and incrementally update the native sectioned `.gg` store; does not auto-select legacy interchange formats or host a database server.

## 2. Sub-System Decomposition

- **[Sectioned Store Format](./sectioned-format/SYSTEM.md)** — encode, verify, and incrementally splice the native GGB4 section layout.
- **[Store Discovery and Interchange](./store-discovery/SYSTEM.md)** — locate the active store and read legacy interchange without promoting it.
- **[Runtime Build State](./runtime-state/SYSTEM.md)** — publish which build is active and arbitrate concurrent writers.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `native_store`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** No graph read or write SHALL require a database server inside the cold-start budget.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-ST-001:** Embedded custom `.gg` store. A general database is farther from the LLM compilation target: the access pattern is whole-section materialization into graph IR, then into a model-facing packet, not ad-hoc query from a person. No database server inside the cold-start budget.
- **ADR-ST-003:** SQLite may be used only by the optional evidence layer, not as the graph store.
- **ADR-ST-004:** Decomposed at the three independent failure modes the pre-split leaf already carried in its own invariant list — format/checksum failure, wrong-or-absent store selection, and stale ownership state. Each pre-split invariant lands in exactly one child, which is the evidence the seam is real rather than a file-tree rename.
