# Corpus Ingestion (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Walk the repository under ignore rules, materialize each surviving file as one versioned `SourceIR` revision, and assemble the scan receipt and graph metadata; does not load a grammar, infer a receiver type, or derive call edges.

## 2. Sub-System Decomposition

**Atomic leaf (procured).** Ignore-file semantics are adopted behind one traversal-and-assembly path.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `source_ir_revisions`, `scan_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN ignore rules match a directory THE SYSTEM SHALL prune that directory before descent rather than walk and discard each file, as checked by `tests/test_scanner.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A `SourceIR` revision SHALL be derived from the artifact version, the file suffix, and the file bytes alone, so the same content at two paths cannot be distinguished by path or scan order.
  - `EvidenceStage:` Observed
- **[Conditional]** IF the resident syntax-artifact cache exceeds its bound THEN THE SYSTEM SHALL evict the least recently used entry rather than grow without limit.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Truncation of a scan SHALL be reported in the receipt rather than left implicit, so a partial graph is distinguishable from a complete one.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CI-001:** Directories are pruned at descent, not filtered after the walk. On a large corpus the cost of an ignored subtree is the traversal itself, so a post-hoc filter pays for exactly the work the ignore file exists to avoid.
- **ADR-CI-002:** `SourceIR` is content-addressed rather than path-addressed, so a downstream evidence pass can prove it read the same revision the extractor did without re-reading the file.
- **ADR-CI-003:** Receipt assembly lives with traversal, not with derivation. What was skipped, truncated, or unavailable is a fact about the corpus pass; a derivation stage that never saw the pruned files cannot report on them.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/scanner/__init__.py`, `src/graphgraph/scanner/ast.py`, `src/graphgraph/scanner/core.py`, `src/graphgraph/scanner/doc.py`, `src/graphgraph/scanner/files.py`, `src/graphgraph/scanner/history.py`, `src/graphgraph/scanner/imports.py`, `src/graphgraph/scanner/rust_references.py`, `src/graphgraph/scanner/source_ir.py`
- **Test Surface Seam:** `tests/test_scanner.py`, `tests/test_scanner_docs.py`, `tests/test_scanner_history.py`, `tests/test_scanner_imports.py`, `tests/test_scanner_incremental.py`, `tests/test_platform.py`

## 7. Measurement Seams

- **Primary Metric:** `scan_wall_ms` (observation, `direction: lower`)
- **Evaluation Gate Path:** `components/static-analysis/measure.sh`
- **Correctness Backpressure:** `components/static-analysis/checks.sh`
- **Telemetry Surface:** ignore-prune receipt, ignored and truncated file counts, doc-extraction profiles, syntax-artifact cache hit rate.
- **Branching Policy:** isolated candidate; merge only when scanner checks pass and scan telemetry does not regress without a recorded cause.

## 8. Technology Resolution

- **Decision class:** ADOPT
- **Selected:** pathspec 1.1.1, locked in `uv.lock`; in-repo traversal and receipt assembly on Python 3.10
- **Dependency:** pathspec
- **Pin:** 1.1.1
- **Standard / protocol:** `.gitignore` pattern syntax via pathspec
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Shell out to `git ls-files` | Requires a git checkout and a subprocess per scan; the scanner must also work on an unversioned directory. |
  | Hand-rolled glob matcher | Re-implements published `.gitignore` precedence rules, including negation and directory anchoring, with no upstream to inherit fixes from. |
  | `gitignore-parser` | Narrower coverage of the same syntax and a smaller maintenance base than pathspec. |

- **Fit gap:** pathspec matches patterns; it does not decide descent. Pruning at descent is this leaf's own code and is where the traversal cost is actually avoided.
- **Seam:** `src/graphgraph/scanner/files.py`
- **Exit cost:** LOW — ignore matching is confined to one module behind `CollectFilesResult`.
- **Cost model:** no service spend; scan CPU and memory scale with corpus size.
- **Liability transferred:** `.gitignore` pattern semantics.
- **Operational owner:** us (library, no service)
- **Failure mode:** an unreadable file is skipped and recorded rather than aborting the scan.
- **Open questions:** none recorded
