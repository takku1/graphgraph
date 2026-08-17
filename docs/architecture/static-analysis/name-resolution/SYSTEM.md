# Name Resolution (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Bind member-call sites to callees from typed local facts, fields, and bounded obligation discharge; does not own parsing, runtime traces, or name-only guess edges.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One binding Module over frontend syntax IR.

## 3. Interface Contracts

- **Inputs:** `syntax_ir`
- **Outputs:** `extracted_nodes`, `extracted_edges`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Unknown receivers SHALL remain explicit; the binder SHALL NOT emit a `calls` edge from a name-only collision.
  - `EvidenceStage:` Observed
- **[Conditional]** IF concrete type facts conflict THEN THE SYSTEM SHALL join them to `ambiguous`, as checked by `tests/test_scanner_frontends.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN scanning incrementally THE SYSTEM SHALL re-join only affected fact keys when persistent facts are enabled, as checked by `tests/test_persistent_type_facts.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Receiver-type-resolved member-call edges SHALL hold independently-verified precision of at least 98 percent per language, as required by OW-AC-05 and checked in `tests/test_receiver_type_resolution.py`.
  - `EvidenceStage:` Measured

## 5. Architectural Decisions (ADRs)

- **ADR-NR-001:** Join existing per-file type facts across the project rather than run a whole-program Andersen analysis.
- **ADR-NR-002:** File-incremental scanning is a hard constraint; PyCG-style iterative whole-program points-to is rejected for the default path.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/scanner/frontends/persistent_facts.py`, `src/graphgraph/scanner/frontends/scope_graph.py`, `src/graphgraph/scanner/frontends/type_facts.py`, `src/graphgraph/scanner/resolution_report.py`
- **Test Surface Seam:** `tests/test_persistent_type_facts.py`, `tests/test_receiver_heldout.py`, `tests/test_receiver_type_resolution.py`, `tests/test_resolution_report.py`, `tests/test_scanner_frontends.py`, `tests/test_scope_graph.py`, `tests/corpus/heldout-receivers/py/app.py`, `tests/corpus/heldout-receivers/py/store.py`, `tests/corpus/heldout-receivers/py/user.py`

## 7. Measurement Seams

- **Primary Metric:** `receiver_resolution_precision` (target `>=0.98`, `direction: higher`)
- **Evaluation Gate Path:** `components/static-analysis/measure.sh`
- **Correctness Backpressure:** `components/static-analysis/checks.sh`
- **Telemetry Surface:** resolved / ambiguous / unknown receiver counts and `receiver_resolution_ratio`.
- **Branching Policy:** isolated candidate; merge only when precision does not fall below 98 percent on the held-out oracle and scanner checks pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — cheap cross-language receiver binding without a compiler or daemon is the capability under test; tree-sitter does not provide it.
- **Selected:** in-repo typed-fact join over Python 3.10, using frontend `syntax_ir`
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | PyCG-style inclusion analysis | Whole-program iterative fixpoint; incompatible with hash-diffed incremental scan. |
  | GitHub stack graphs | File-isolated by design; does not join field types across files, which is the measured gap. |
  | Language servers | Daemon per language; blows the cold-start budget. |

- **Fit gap:** none for incremental field-obligation promotion on Go/Rust/C++ or the held-out TS/C# precision table. Per-language volume on large third-party corpora remains OW-AC-05 follow-up only if this panel is judged too small.
- **Seam:** `src/graphgraph/scanner/frontends/type_facts.py` and the frontend binding providers
- **Exit cost:** HIGH — binding assumptions are spread across language frontends.
- **Cost model:** local CPU on scan; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** unresolved receivers stay unknown and emit no `calls` edge; topology is reported partial.
- **Open questions:** OW-AC-05, OW-Q02, OW-D-01, OW-D-02
