# Syntax and Edge Derivation (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Walk a parsed tree without knowing its language, collect definitions and call sites, bind each use to the nearest visible declaration, and turn the survivors into graph nodes and edges; does not load a grammar, own per-language node-type tables, or walk the corpus.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One traversal-bind-emit path whose extractor selection, binding precedence, and edge construction share a single ambiguity rule.

## 3. Interface Contracts

- **Inputs:** `parse_trees`, `language_facts`
- **Outputs:** `syntax_ir`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a module-qualified call matches more than one candidate module or symbol THEN THE SYSTEM SHALL emit nothing rather than pick a winner.
  - `EvidenceStage:` Observed
- **[Conditional]** IF the `cpg` extractor is requested THEN THE SYSTEM SHALL raise rather than silently hand back the weakest extractor, because quietly degrading a request for type evidence is a false promise.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN extractor selection is left automatic and tree-sitter is unavailable THE SYSTEM SHALL fall back to regex extraction rather than fail the scan.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Emitted edges SHALL be deduplicated before they leave extraction, so a node reached by two traversal paths does not inflate degree.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Incremental extraction SHALL project restored context into the name index by the same rule clean extraction uses, so generated field nodes do not create false ambiguity that suppresses otherwise stable edges.
  - `EvidenceStage:` Unknown

## 5. Architectural Decisions (ADRs)

- **ADR-SD-001:** Binding precedence and ambiguity live in the shared layer, not in the language adapters. Fifteen adapters each deciding what "nearest declaration" means is fifteen chances to disagree, and the disagreement is invisible in the output graph.
- **ADR-SD-002:** Ambiguity abstains. A resolver that guesses between two equally plausible targets produces a confidently wrong edge, which is more expensive to detect downstream than a missing one.
- **ADR-SD-003:** Module-qualified resolution reuses the import bindings the graph already carries rather than adding a second name-resolution mechanism, so a class call that falls through the module path is self-correcting rather than mis-typed.
- **ADR-SD-004:** `frontends/__init__.py` stays the stable import path for the whole extraction surface, so the internal layer split (model -> languages -> syntax -> edges -> extractors) can move without breaking callers.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/scanner/frontends/__init__.py`, `src/graphgraph/scanner/frontends/binding_providers.py`, `src/graphgraph/scanner/frontends/edges.py`, `src/graphgraph/scanner/frontends/extractors.py`, `src/graphgraph/scanner/frontends/module_calls.py`, `src/graphgraph/scanner/frontends/syntax.py`
- **Test Surface Seam:** `tests/test_scanner_frontends.py`, `tests/test_receiver_type_resolution.py`, `tests/test_grammar_profiles.py`

## 7. Measurement Seams

- **Primary Metric:** `scan_wall_ms` (observation, `direction: lower`)
- **Evaluation Gate Path:** `components/static-analysis/measure.sh`
- **Correctness Backpressure:** `components/static-analysis/checks.sh`
- **Telemetry Surface:** extractor identity, fallback counts, resolved versus abstained call sites, edge counts by relation.
- **Branching Policy:** isolated candidate; merge only when scanner checks pass and scan telemetry does not regress without a recorded cause.
- **Known granularity gap:** this leaf shares the component-level `scan_wall_ms` gate rather than carrying a resolution-precision metric of its own. Recorded here rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Fatal fit gap in the adopted vendor — tree-sitter yields syntax, not callee binding, and no grammar package resolves a name across files. This is the layer the parent's ADOPT explicitly does not cover.
- **Selected:** in-repo traversal, binding, and edge construction on Python 3.10
- **Standard / protocol:** none; consumes the tree-sitter node ABI and emits in-repo graph types
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Language servers (LSP) for resolution | A per-language daemon per repository; the same cold-start objection that ruled them out as frontends. |
  | `tree-sitter` queries per language | Pushes resolution back into fifteen per-language query files, which is the disagreement ADR-SD-001 exists to prevent. |
  | Stack-graphs / scope-graph libraries | Would require per-language stack-graph rules for every shipped grammar; the coverage gap lands exactly on the languages that resolved worst. |
  | Compiler-grade name resolution per language | One toolchain per language and a build step per scan; held as RF-03. |

- **Fit gap:** resolution is syntactic and abstains under ambiguity, so recall is bounded by what declaration shapes name a type outright.
- **Seam:** `src/graphgraph/scanner/frontends/__init__.py`
- **Exit cost:** HIGH — every relation in the graph is produced here; replacing it replaces the edge semantics.
- **Cost model:** no service spend; resolution CPU scales with call-site count.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unresolvable call site abstains and is counted rather than emitting a guessed edge.
- **Open questions:** RF-03
