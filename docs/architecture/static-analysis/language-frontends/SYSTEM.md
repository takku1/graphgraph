# Language Frontends (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Parse supported source languages and document formats into syntax IR and file-level symbols; does not bind receivers, persist the graph, or abort a scan when one grammar is missing.

## 2. Sub-System Decomposition

- **[Corpus Ingestion](./corpus-ingestion/SYSTEM.md)** — walk the repository under ignore rules, materialize each file revision, and assemble the scan receipt.
- **[Grammar Adapters](./grammar-adapters/SYSTEM.md)** — acquire tree-sitter grammars, declare per-language node-type profiles, and emit per-language facts.
- **[Syntax and Edge Derivation](./syntax-derivation/SYSTEM.md)** — language-agnostic traversal, binding, and edge construction over the parsed trees.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `syntax_ir`, `scan_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Frontend emissions SHALL share one `SourceIR` revision with later CPG evidence passes, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-LF-001:** Adopt tree-sitter and `tree-sitter-language-pack` rather than per-language compiler frontends on the default scan path.
- **ADR-LF-002:** Isolate grammar acquisition in `scanner/frontends/languages.py`.
- **ADR-LF-003:** Decomposed at the procurement boundary the pre-split leaf already straddled. Corpus traversal fails on ignore and truncation semantics, grammar adaptation fails on ABI and per-language node types, and derivation fails on binding and ambiguity — three unrelated failure modes that were sharing one gate. Each pre-split invariant lands in exactly one child, which is the evidence the seam is real rather than a file-tree rename.
