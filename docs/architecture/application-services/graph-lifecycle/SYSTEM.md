# Graph Lifecycle and Cache Identity (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Build, incrementally refresh, and validate the saved graph, and derive the deterministic identity a cached answer is keyed on; does not compile a packet, render a control receipt, or decide what to tell a caller about project health.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One build-or-splice path plus the signature that decides whether its output can be reused.

## 3. Interface Contracts

- **Inputs:** `native_store`
- **Outputs:** `resident_graph`, `cache_identity`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a packet cache key is computed THEN it SHALL exclude the tool's own `.graphgraph/` artifacts, as checked by `tests/test_control.py`.
  - `EvidenceStage:` Measured
- **[Conditional]** IF an incremental refresh resolves to an empty changed-and-deleted path set THEN it SHALL be a no-op that reports `built=False` rather than a rebuild (OW-AC-02).
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Every save SHALL pass the catastrophic-shrink guard unless the caller explicitly forces it, so a mis-rooted scan cannot silently replace a full graph with a near-empty one.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a removal request matches nothing THEN it SHALL be treated as an idempotent no-op, while a removal that would match everything SHALL be refused first.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A graph SHALL be validated before it is published as the saved build.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-GL-001:** The cache key fingerprints project sources, never the tool's own generated artifacts. Keying on `.graphgraph/` contents made every write invalidate the cache that write had just populated — a self-invalidating cache is indistinguishable from no cache until the hit rate is measured.
- **ADR-GL-002:** An empty delta is a no-op, not a cheap rebuild. The manifest-backed path partition is what proves the request is exactly empty, so the guarantee is derived rather than assumed from an argument being falsy.
- **ADR-GL-003:** Destruction is checked before emptiness. A wrong-root removal can look identical to an idempotent one; ordering the checks the other way turns a user error into data loss.
- **ADR-GL-004:** Validation happens before publication, not on read. A reader that has to repair is a reader that can disagree with another reader.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/services/cache_identity.py`, `src/graphgraph/services/lifecycle.py`
- **Test Surface Seam:** `tests/test_control.py`, `tests/test_cli_mcp.py`, `tests/test_module_boundaries.py`, `tests/test_retrieval.py`, `tests/test_scanner_incremental.py`

## 7. Measurement Seams

- **Primary Metric:** `context_compile_warm_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/application-services/measure.sh`
- **Correctness Backpressure:** `components/application-services/checks.sh`
- **Telemetry Surface:** built / repaired flags, changed and deleted path counts, validation result, cache identity signature and dependency paths.
- **Branching Policy:** isolated candidate; empty source delta must remain a no-op (OW-AC-02).
- **Known granularity gap:** this leaf shares the component's `context_compile_warm_ms` gate, which measures the warm request path rather than build or splice cost. Cache hit rate — the number ADR-GL-001 was decided on — is telemetry here, not a gated metric.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Dependency liability — the guards this leaf exists for (catastrophic-shrink refusal, destruction-before-no-op ordering, artifact-excluding cache identity) are all project-specific corrections to defects this project actually hit; a generic build cache would reintroduce the self-invalidation ADR-GL-001 removes.
- **Selected:** in-repo lifecycle and signature modules on Python 3.10, stdlib only, over the storage delta primitives
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Generic build cache (`hashlib` over the tree, or a build tool's cache) | Keys on the whole working tree, which is exactly the self-invalidation defect. |
  | Filesystem watcher as the source of truth | Misses changes made while the process is not running; git and the manifest are durable. |
  | mtime-only change detection | Wrong across checkouts and worktree switches, which this project runs on routinely. |

- **Fit gap:** single-workspace. Concurrent writers are arbitrated by Runtime Build State, not here.
- **Seam:** `src/graphgraph/services/lifecycle.py`
- **Exit cost:** MEDIUM — the request path and status reporting both depend on `GraphBuildStatus` and the freshness signature shape.
- **Cost model:** local disk and CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a refresh that would shrink the graph catastrophically is refused and the previous build stays active.
- **Open questions:** OW-AC-02
