# Persistent Storage (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Persist and incrementally update the native sectioned `.gg` store; does not auto-select legacy interchange formats or host a database server.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One embedded store and one incremental splice protocol.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `native_store`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Active store discovery SHALL prefer native `.gg` over legacy interchange.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN the source delta is empty THE SYSTEM SHALL avoid a full rebuild, as checked by `tests/test_storage_delta.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Packet `#gg` text SHALL NOT be used as the binary store encoding.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a state-file lock is held by a live owner THEN age alone SHALL NOT revoke it.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-ST-001:** Embedded custom `.gg` store. A general database is farther from the LLM compilation target: the access pattern is whole-section materialization into graph IR, then into a model-facing packet, not ad-hoc query from a person. No database server inside the cold-start budget.
- **ADR-ST-002:** Legacy `ggb2` / `ggb3` / JSON load but are never auto-selected as the active store.
- **ADR-ST-003:** SQLite may be used only by the optional evidence layer, not as the graph store.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/io/__init__.py`, `src/graphgraph/io/cache.py`, `src/graphgraph/io/core.py`, `src/graphgraph/io/discovery.py`, `src/graphgraph/runtime/__init__.py`, `src/graphgraph/runtime/cache.py`, `src/graphgraph/runtime/manifest.py`, `src/graphgraph/runtime/state.py`, `src/graphgraph/storage/__init__.py`, `src/graphgraph/storage/backends.py`, `src/graphgraph/storage/delta.py`, `src/graphgraph/storage/sectioned.py`
- **Test Surface Seam:** `tests/test_sectioned_storage.py`, `tests/test_storage_delta.py`, `tests/test_io.py`.

## 7. Measurement Seams

- **Primary Metric:** `store_load_ms` (target measured on the cold CLI path, `direction: lower`)
- **Evaluation Gate Path:** `components/storage/measure.sh`
- **Correctness Backpressure:** `components/storage/checks.sh`
- **Telemetry Surface:** section checksums, manifest hash, incremental file counts.
- **Branching Policy:** isolated candidate; determinism dump plus storage checks must pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Cost inversion at this scale — whole-section mmap reads are narrower than a general graph engine; a server hop sits inside a millisecond budget.
- **Selected:** in-repo GGB4 sectioned format on Python 3.10
- **Standard / protocol:** none for the store; JSON remains interchange
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Neo4j | Server daemon and query-compiler hop inside a millisecond budget. |
  | SQLite as the graph store | Row-store shape penalizes whole-section reads; retained only for evidence. |
  | Pickle / JSON as the active store | JSON is interchange only; Pickle is unsafe to load from a repository. |
  | DuckDB or Kùzu | Extra engine and file format for a sectioned array read. |

- **Fit gap:** single-project, single-writer. Federation is a retrieval concern.
- **Seam:** `src/graphgraph/storage/backends.py`
- **Exit cost:** HIGH — native persistence contract; `load_any` limits read-side blast radius.
- **Cost model:** local disk; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** checksum failure refuses the load; discovery reports no active graph.
- **Open questions:** OW-AC-02, OW-Q07
