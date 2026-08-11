# Persistent Storage (L1)

> **Packages:** `storage/`, `runtime/`, `io/`  
> **Children:** [native-graph-store.md](./native-graph-store.md), [incremental-update-protocol.md](./incremental-update-protocol.md)  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Native Storage Contract

## 1. Intent

**Native graph store** for project-local persistence: full-fidelity sectioned `.gg` (GGB4 family) with identity/detail/edge/relation sections and checksums. Legacy formats are migration inputs via `load_any` / ingest—not auto-selected active stores.

```text
source → Graph IR → binary graph.gg → selected subgraph → context packet
                                              ↘ JSON control receipt
```

## 2. Decomposition

| Child | Role |
|-------|------|
| [native-graph-store.md](./native-graph-store.md) | Sectioned store architecture (v4 proposal lineage) |
| [incremental-update-protocol.md](./incremental-update-protocol.md) | Delta / refresh protocol |
| Atomic state & locks | `runtime/state.py` (OS advisory locks; age alone does not revoke live owners) |
| Manifest / cache | `runtime/manifest.py`, `runtime/cache.py`, `io/cache.py` |
| Discovery | Active graph path resolution (`io/discovery.py`) |

## 3. Interfaces

| | |
|--|--|
| **Inputs** | Full or delta IR, output path overrides |
| **Outputs** | `.graphgraph/graph.gg`, fingerprints for process memoization |
| **Invariants** | Auto-discover `.graphgraph/graph.gg` unless overridden |

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Active store discovery SHALL prefer native `.gg` over legacy interchange.
  - `EvidenceStage: Observed` — `io/discovery.py`.
- **[Event-driven]** WHEN the source delta is empty THE SYSTEM SHOULD avoid a full rebuild (OW-Q07-A).
  - `EvidenceStage: Sampled` — `tests/test_storage_delta.py`; the no-op incremental gate is still open.
- **[Ubiquitous]** Packet `#gg` text SHALL NOT be confused with the binary store encoding.
  - `EvidenceStage: Observed` — distinct code paths (`packets/` vs `storage/backends.py`).
- **[Ubiquitous]** A cache key SHALL NOT be derived from artifacts the tool itself writes under `.graphgraph/`.
  - `EvidenceStage: Measured` — a key that fingerprinted the tool's own `kv_cache.json` self-invalidated on every run (0% hit rate on external repositories); excluding it restored the hit path. See [the consolidated cache measurement](../../evaluation/graybox-cycles/README.md#instrument-and-representation-measurements).
- **[Conditional]** IF a state-file lock is held by a live owner THEN age alone SHALL NOT revoke it.
  - `EvidenceStage: Observed` — defect 1 in the [defect ledger](../../evaluation/defect-ledger.md), fixed.

## 5. ADRs

- **ADR-ST-001:** The native `.gg` store is embedded and file-based — no database server, no daemon. Cold-start CLI latency is a measured budget in this project, and a server hop would sit inside it.
- **ADR-ST-002:** Legacy formats (`ggb2`, `ggb3`, JSON) load but are never auto-selected as the active store; they are migration inputs only, which keeps one write path and many read paths.
- **ADR-ST-003:** `platform/evidence_store.py` may use SQLite — it is stdlib and embedded, so it does not violate ADR-ST-001. This is the optional evidence layer, not the graph store.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `storage/backends.py` (GGB2/3/4 read, v4 write), `storage/sectioned.py`, `runtime/state.py`, `runtime/manifest.py`, `io/cache.py`, `io/discovery.py` |
| **Test surface** | `tests/test_sectioned_storage.py`, `tests/test_storage_delta.py`, `tests/test_context_compiler.py` |
| **Determinism gate** | A canonical, timestamp-free graph dump — byte-identity across a change is what makes a storage or scan optimization safe to land |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Store load time on the cold CLI path (`direction: lower`) |
| **Secondary metric** | On-disk size at equal fidelity (`direction: lower`) |
| **Harness** | `benchmarks/context_graph/storage_backend_bakeoff.py`, `benchmarks/context_graph/bitpack_benchmark.py` |
| **Recorded results** | [empirical-evaluation.md](../../evaluation/empirical-evaluation.md) § Storage Backend Bake-Off, § Native Exact-Lookup Staging |
| **Design notes** | `benchmarks/context_graph/storage_design_research.md` |
| **Correctness backpressure** | The storage test surface above plus the determinism gate |

## 8. Technology resolution

- **Decision class:** **BUILD** (native sectioned store)
- **Selected:** in-repo GGB4 sectioned format — identity / detail / edge / relation sections with checksums
- **Standard / protocol:** none for the store; JSON remains the interchange/import path
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Neo4j / a graph database | Requires a server daemon and a query-compiler hop inside a latency budget measured in milliseconds; full analysis in [comparisons/neo4j.md](../../research/comparisons/neo4j.md) |
  | SQLite as the graph store | Embedded and viable, but a row-store shape penalizes the whole-section reads this access pattern is built around; retained for the *evidence* store where the access pattern is genuinely relational |
  | Pickle / JSON | JSON is kept as interchange; as the active store it is large and parse-bound. Pickle is not a safe format to load from a repository |
  | Embedded analytics engines (DuckDB, Kùzu) | Another dependency and file format to own for a workload that is a sectioned array read; revisit only if a measured load-time win appears |

- **Fit gap:** the store is deliberately single-project and single-writer. Cross-repository federation is a retrieval-layer concern, not a storage feature.
- **BUILD justification:** cost inversion at this scale — the access pattern (load a whole section, mmap-friendly, no query language) is narrow enough that a general engine's overhead dominates its benefit.
- **Seam:** `storage/backends.py` (`save_graph_binary` / `load_graph_binary`, `is_binary_gg`)
- **Exit cost:** **HIGH** — the format is the project's persistence contract; `load_any` limits the blast radius on the read side only.
- **Operational owner:** us
- **Failure mode:** a truncated or checksum-failing store fails the load rather than returning a partial graph; discovery then reports no active graph and the CLI directs the user to re-scan.
- **Open questions:** OW-AC-02, OW-Q07-* — [open-work.md](../../open-work.md)
