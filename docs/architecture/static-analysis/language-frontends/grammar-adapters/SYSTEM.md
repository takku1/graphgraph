# Grammar Adapters (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Acquire a tree-sitter grammar per language, declare which node types mean definition, name, and call for it, and emit the per-language facts — receiver types, impl owners, callable idioms, external API summaries — that syntax alone cannot recover; does not walk the corpus, resolve a call to a graph target, or build edges.

## 2. Sub-System Decomposition

**Atomic leaf (procured).** Tree-sitter is the vendor; only grammar selection and per-language fact extraction sit on this side of the procurement boundary.

## 3. Interface Contracts

- **Inputs:** `source_ir_revisions`
- **Outputs:** `parse_trees`, `language_facts`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a tree-sitter grammar cannot be loaded THEN THE SYSTEM SHALL record the reason in `_LANGUAGE_LOAD_ERRORS` and skip that language.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a source suffix has no per-language grammar profile THEN THE SYSTEM SHALL fall back to the union profile rather than to an empty one, so an unrecognised suffix behaves exactly as it did before profiles existed.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a parser for a language has already been constructed THE SYSTEM SHALL reuse the cached parser rather than rebuild it per file.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** An external API summary SHALL apply only to a binding whose import names the summarized package, so a same-named local helper never acquires the summarized behavior.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A language adapter SHALL emit facts without resolving a graph target, so precedence and ambiguity stay with the shared binding layer.
  - `EvidenceStage:` Unknown

## 5. Architectural Decisions (ADRs)

- **ADR-GA-001:** Adopt tree-sitter and `tree-sitter-language-pack` rather than per-language compiler frontends on the default scan path.
- **ADR-GA-002:** Isolate grammar acquisition in `scanner/frontends/languages.py`, so a missing or ABI-incompatible grammar is one module's failure rather than a scan-wide one.
- **ADR-GA-003:** Per-language grammar profiles replace the four global union tables. The union shipped fifteen languages and still works as the unknown-suffix fallback, but it made every language pay for every other language's node types, and it made a per-language node-type mistake invisible.
- **ADR-GA-004:** Receiver-type inference is per language and deliberately shallow — declaration shapes that name a type outright. A wrong receiver type is worse than an absent one, because it produces a confidently mis-targeted edge rather than a gap.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/scanner/frontends/cpp.py`, `src/graphgraph/scanner/frontends/csharp.py`, `src/graphgraph/scanner/frontends/external_summaries.py`, `src/graphgraph/scanner/frontends/go.py`, `src/graphgraph/scanner/frontends/grammars.py`, `src/graphgraph/scanner/frontends/javascript.py`, `src/graphgraph/scanner/frontends/languages.py`, `src/graphgraph/scanner/frontends/model.py`, `src/graphgraph/scanner/frontends/python.py`, `src/graphgraph/scanner/frontends/rust.py`, `src/graphgraph/scanner/frontends/typescript.py`
- **Test Surface Seam:** `tests/test_grammar_profiles.py`, `tests/test_receiver_type_resolution.py`, `tests/corpus/polyglot/core.py`, `tests/corpus/polyglot/helper.py`, `tests/corpus/polyglot/core.rs`, `tests/corpus/polyglot/helper.rs`

## 7. Measurement Seams

- **Primary Metric:** `scan_wall_ms` (observation, `direction: lower`)
- **Evaluation Gate Path:** `components/static-analysis/measure.sh`
- **Correctness Backpressure:** `components/static-analysis/checks.sh`
- **Telemetry Surface:** frontend identity, per-language load errors, parser cache reuse, per-language receiver-resolution volume.
- **Branching Policy:** isolated candidate; merge only when scanner checks pass and scan telemetry does not regress without a recorded cause.
- **Known granularity gap:** this leaf shares the component-level `scan_wall_ms` gate rather than carrying a per-language resolution metric of its own. Recorded here rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** ADOPT
- **Selected:** tree-sitter 0.25.2, tree-sitter-language-pack 1.10.9, locked in `uv.lock`
- **Dependency:** tree-sitter
- **Pin:** 0.25.2
- **Standard / protocol:** tree-sitter grammar ABI
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Language servers (LSP) | A per-language daemon per repository; incompatible with the cold-start CLI budget. |
  | Compiler frontends (for example Rust THIR) | Highest fidelity, but one toolchain per language and a build step per scan; held as RF-03. |
  | Regex-only extraction | Cannot carry scope or typed facts; retained only as the no-grammar fallback. |
  | Per-grammar packages instead of the language pack | One dependency and one ABI pin per language, multiplied by fifteen languages. |

- **Fit gap:** tree-sitter yields syntax, not callee binding. Name resolution is the sibling BUILD.
- **Seam:** `src/graphgraph/scanner/frontends/languages.py`
- **Exit cost:** HIGH — grammar ABI and per-language node-type assumptions are spread across the adapters.
- **Cost model:** no service spend; parse CPU and memory scale with corpus size.
- **Liability transferred:** grammar packaging and ABI compatibility.
- **Operational owner:** us (vendored grammars, no service)
- **Failure mode:** a missing grammar records an error and that language is skipped; other languages continue.
- **Open questions:** RF-03
