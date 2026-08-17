# Language Frontends (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Parse supported source languages and document formats into syntax IR and file-level symbols; does not bind receivers, persist the graph, or abort a scan when one grammar is missing.

## 2. Sub-System Decomposition

**Atomic leaf (procured).** Tree-sitter and ignore-file semantics are adopted behind the frontend seam.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `syntax_ir`, `scan_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a tree-sitter grammar cannot be loaded THEN THE SYSTEM SHALL record the reason in `_LANGUAGE_LOAD_ERRORS` and skip that language.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN ignore rules match a directory THE SYSTEM SHALL prune that directory before descent rather than walk and discard each file, as checked by `tests/test_scanner.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Frontend emissions SHALL share one `SourceIR` revision with later CPG evidence passes, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-LF-001:** Adopt tree-sitter and `tree-sitter-language-pack` rather than per-language compiler frontends on the default scan path.
- **ADR-LF-002:** Isolate grammar acquisition in `scanner/frontends/languages.py`.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/scanner/__init__.py`, `src/graphgraph/scanner/ast.py`, `src/graphgraph/scanner/core.py`, `src/graphgraph/scanner/doc.py`, `src/graphgraph/scanner/files.py`, `src/graphgraph/scanner/frontends/__init__.py`, `src/graphgraph/scanner/frontends/binding_providers.py`, `src/graphgraph/scanner/frontends/cpp.py`, `src/graphgraph/scanner/frontends/csharp.py`, `src/graphgraph/scanner/frontends/edges.py`, `src/graphgraph/scanner/frontends/external_summaries.py`, `src/graphgraph/scanner/frontends/extractors.py`, `src/graphgraph/scanner/frontends/go.py`, `src/graphgraph/scanner/frontends/grammars.py`, `src/graphgraph/scanner/frontends/javascript.py`, `src/graphgraph/scanner/frontends/languages.py`, `src/graphgraph/scanner/frontends/model.py`, `src/graphgraph/scanner/frontends/module_calls.py`, `src/graphgraph/scanner/frontends/python.py`, `src/graphgraph/scanner/frontends/rust.py`, `src/graphgraph/scanner/frontends/syntax.py`, `src/graphgraph/scanner/frontends/typescript.py`, `src/graphgraph/scanner/history.py`, `src/graphgraph/scanner/imports.py`, `src/graphgraph/scanner/rust_references.py`, `src/graphgraph/scanner/source_ir.py`
- **Test Surface Seam:** `tests/test_grammar_profiles.py`, `tests/test_scanner.py`, `tests/test_scanner_docs.py`, `tests/test_scanner_frontends.py`, `tests/test_scanner_history.py`, `tests/test_scanner_imports.py`, `tests/test_scanner_incremental.py`, `tests/corpus/polyglot/core.py`, `tests/corpus/polyglot/helper.py`, `tests/corpus/polyglot/core.rs`, `tests/corpus/polyglot/helper.rs`

## 7. Measurement Seams

- **Primary Metric:** `scan_wall_ms` (observation, `direction: lower`)
- **Evaluation Gate Path:** `components/static-analysis/measure.sh`
- **Correctness Backpressure:** `components/static-analysis/checks.sh`
- **Telemetry Surface:** frontend identity, fallback counts, ignore-prune receipt, and per-language load errors.
- **Branching Policy:** isolated candidate; merge only when scanner checks pass and scan telemetry does not regress without a recorded cause.

## 8. Technology Resolution

- **Decision class:** ADOPT
- **Selected:** tree-sitter 0.25.2, tree-sitter-language-pack 1.10.9, pathspec 1.1.1, locked in `uv.lock`
- **Dependency:** tree-sitter
- **Pin:** 0.25.2
- **Standard / protocol:** tree-sitter grammar ABI; `.gitignore` pattern syntax via pathspec
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Language servers (LSP) | A per-language daemon per repository; incompatible with the cold-start CLI budget. |
  | Compiler frontends (for example Rust THIR) | Highest fidelity, but one toolchain per language and a build step per scan; held as RF-03. |
  | Regex-only extraction | Cannot carry scope or typed facts. |

- **Fit gap:** tree-sitter yields syntax, not callee binding. Name resolution is the sibling BUILD.
- **Seam:** `src/graphgraph/scanner/frontends/languages.py`
- **Exit cost:** HIGH — grammar ABI and per-language node-type assumptions are spread across the frontends.
- **Cost model:** no service spend; scan CPU and memory scale with corpus size.
- **Liability transferred:** grammar packaging and ABI compatibility.
- **Operational owner:** us (vendored grammars, no service)
- **Failure mode:** a missing grammar records an error and that language is skipped; other languages continue.
- **Open questions:** RF-03
