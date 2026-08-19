# Runtime Build State (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Publish which build is active, record its manifest, and arbitrate concurrent writers so a reader never observes a half-written revision; does not encode the store, discover candidate paths, or decide freshness policy for a query.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One state file, one manifest, one ownership lock.

## 3. Interface Contracts

- **Inputs:** `native_store`
- **Outputs:** `active_build`, `build_manifest`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a state-file lock is held by a live owner THEN age alone SHALL NOT revoke it.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A published build SHALL become visible to readers only after its manifest is complete, so a reader never selects a half-written revision.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a lock owner is no longer live THE SYSTEM SHALL allow reclamation rather than deadlocking the workspace.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-RS-001:** Liveness, not age, revokes a lock. A long scan is indistinguishable from a dead writer by timestamp alone, and a timeout-based lock silently corrupts the slower of two concurrent builds.
- **ADR-RS-002:** Publication is manifest-last, so partial section writes are invisible rather than requiring reader-side repair.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/runtime/__init__.py`, `src/graphgraph/runtime/cache.py`, `src/graphgraph/runtime/manifest.py`, `src/graphgraph/runtime/state.py`
- **Test Surface Seam:** `tests/test_io.py`, `tests/test_mcp_project_status.py`

## 7. Measurement Seams

- **Primary Metric:** `store_load_ms` (target measured on the cold CLI path, `direction: lower`)
- **Evaluation Gate Path:** `components/storage/measure.sh`
- **Correctness Backpressure:** `components/storage/checks.sh`
- **Telemetry Surface:** active build id, manifest hash, lock owner and liveness.
- **Branching Policy:** isolated candidate; storage checks must pass.
- **Known granularity gap:** this leaf currently shares the component-level `store_load_ms` gate rather than carrying an ownership-specific metric. Recorded in `ROADMAP.md` as `R-002` rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable at this scale — single-writer, single-host ownership over a local file; every distributed-lock option below transfers no liability this project actually carries.
- **Selected:** in-repo state file plus liveness check on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | `filelock` / `portalocker` | Adds a dependency for advisory locking this already does; does not answer owner liveness, which is the actual invariant. |
  | Redis or etcd lease | Network service inside a cold-start budget for a single-host, single-writer workspace. |
  | OS mandatory file locks | Semantics differ across Windows and POSIX, which is the platform matrix this project ships on. |

- **Fit gap:** single-host. Multi-machine writers are not supported and are not a stated goal.
- **Seam:** `src/graphgraph/runtime/state.py`
- **Exit cost:** MEDIUM — publication order is depended on by discovery and freshness reporting.
- **Cost model:** local disk; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unreadable state file reports no active build rather than electing one.
- **Open questions:** OW-AC-02, R-002
