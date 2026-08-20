# Intermediate Representation (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Hold the canonical in-memory graph IR shared by extraction, storage, retrieval, and packet encoding; does not own prompt-facing encodings or a query language.

## 2. Sub-System Decomposition

- **[Graph Record Model and Traversal](./graph-model/SYSTEM.md)** — the three record types, ontology relation policy, and the traversal and coupling views over them.
- **[Concept and Terminology Layer](./concept-layer/SYSTEM.md)** — canonical term keys, the interpretation-concept registry, and doc/code link health.

## 3. Interface Contracts

- **Inputs:** `extracted_nodes`, `extracted_edges`
- **Outputs:** `graph_ir`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Consumers that need complete materialization SHALL use the in-memory IR; the binary store is a persistence optimization.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-GIR-001:** The IR is the logical model; the store is a serialization of it.
- **ADR-GIR-002:** External schemas bind loosely and only on ingest.
- **ADR-GIR-003:** Decomposed along the two independent failure modes the pre-split leaf already carried: a record/relation-policy failure corrupts every traversal, while a terminology failure degrades semantic linking without touching structural retrieval. The two source packages are the observable seam — `concepts/` imports `graph/` and never the reverse — so the split is a dependency direction that already exists, not a file-tree rename.
