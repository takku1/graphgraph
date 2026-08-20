# Sectioned Store Format (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Encode graph IR into the native GGB4 section layout, verify it on read, and splice an incremental delta without a full rebuild; does not choose which store is active, own runtime ownership state, or define packet text.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One section codec whose delta path shares its checksum contract.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `native_store`, `section_checksums`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN the source delta is empty THE SYSTEM SHALL avoid a full rebuild, as checked by `tests/test_storage_delta.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Packet `#gg` text SHALL NOT be used as the binary store encoding.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a section checksum does not verify THEN THE SYSTEM SHALL refuse the load rather than return partial graph IR, as checked by `tests/test_sectioned_storage.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A rewrite of unchanged input SHALL be byte-identical so determinism dumps can compare revisions.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-STF-001:** Whole-section materialization is the access pattern; the format optimizes sequential section reads rather than row lookup.
- **ADR-STF-002:** The delta splice reuses the full-write checksum contract instead of a second verification path, so an incremental store cannot be weaker than a rebuilt one.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/storage/__init__.py`, `src/graphgraph/storage/backends.py`, `src/graphgraph/storage/delta.py`, `src/graphgraph/storage/sectioned.py`
- **Test Surface Seam:** `tests/test_sectioned_storage.py`, `tests/test_storage_delta.py`

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
  | Pickle as the active store | Unsafe to load from a repository. |
  | DuckDB or Kùzu | Extra engine and file format for a sectioned array read. |

- **Fit gap:** single-writer. Concurrent ownership is arbitrated by Runtime Build State, not by the format.
- **Seam:** `src/graphgraph/storage/backends.py`
- **Exit cost:** HIGH — native persistence contract; `load_any` limits read-side blast radius.
- **Cost model:** local disk; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** checksum failure refuses the load.
- **Open questions:** OW-Q07
