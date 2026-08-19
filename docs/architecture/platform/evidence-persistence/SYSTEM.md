# Evidence Persistence (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Cache provider evidence across runs, keyed by provider and source path, and refuse any cached batch or sidecar that no longer matches the source or schema it was computed from; does not decide which providers exist, run an analysis itself, or arbitrate the workspace's active build.

## 2. Sub-System Decomposition

**Atomic leaf (procured).** One embedded SQLite store plus the atomic-write and lock primitives it shares with the rest of the platform.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `provider_analyses`
- **Outputs:** `evidence_batches`, `platform_state`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a semantic sidecar mismatches active graph topology THEN THE SYSTEM SHALL reject it as stale, as checked by `tests/test_cycle5_regressions.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a persisted store's recorded version is not `EVIDENCE_STORE_VERSION` THEN THE SYSTEM SHALL discard it and start empty rather than read it under the current schema.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A cached batch SHALL be keyed by provider and source path together, so one provider's staleness cannot invalidate another's.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a source file's content hash changes THEN the batch cached for that path SHALL be recomputed rather than reused.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** State writes SHALL be atomic and lock-guarded, so an interrupted run leaves a readable previous revision rather than a truncated one.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-EP-001:** SQLite is acceptable here — and only here — because it is embedded stdlib with no server, which is the exact condition ADR-ST-001 refuses for the graph store itself.
- **ADR-EP-002:** The cache is partitioned per provider and per path rather than per graph revision, because the reuse this store exists for is file-granular: one edited file must not cost a full re-analysis.
- **ADR-EP-003:** A version mismatch discards rather than migrates. A cache is reconstructible by definition, so a migration path would be liability without a payoff.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/evidence_store.py`, `src/graphgraph/platform/persistence.py`
- **Test Surface Seam:** `tests/test_platform.py`, `tests/test_cycle5_regressions.py`

## 7. Measurement Seams

- **Primary Metric:** `optional_pass_marginal_recall` (`direction: higher` vs the pass being off)
- **Correctness Backpressure:** `components/platform/checks.sh`
- **Telemetry Surface:** artifacts compiled vs reused, cache-hit flags per provider, store version, paths refreshed.
- **Branching Policy:** isolated candidate; platform checks must pass.
- **Known granularity gap:** this component has no evaluation probe script at all, and this leaf's natural metric — evidence-cache reuse rate — is not the parent's recall metric at all. Neither is measured today; the experiment design is still open, so no number is claimed rather than a placeholder being recorded.

## 8. Technology Resolution

- **Decision class:** BUY (adopt stdlib)
- **Selected:** Python 3.10 `sqlite3` for the batch store; in-repo atomic-write and lock helpers re-exported from `runtime.state`
- **Standard / protocol:** SQL
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | A second `.gg` sectioned store | The access pattern here is keyed row lookup by `(provider, path)` — the opposite of whole-section materialization. |
  | Plain JSON sidecar per provider | Rewrites the whole file per changed path; the legacy form is retained only for import. |
  | A server-backed cache (Redis, Postgres) | Network service inside a cold-start budget for a per-workspace reconstructible cache. |

- **Fit gap:** single-writer per workspace. Concurrent writers are arbitrated by the lock, not by the database.
- **Seam:** `src/graphgraph/platform/evidence_store.py`
- **Exit cost:** LOW — the store is a cache; deleting it costs one recompute, not data.
- **Cost model:** one local SQLite file; no service spend.
- **Liability transferred:** none — `sqlite3` ships with the interpreter this project already requires.
- **Operational owner:** us
- **Failure mode:** an unreadable or wrong-version store is discarded and providers recompute from source.
- **Open questions:** OW-Q08
