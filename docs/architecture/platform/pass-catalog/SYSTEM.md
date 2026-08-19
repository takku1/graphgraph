# Compiler Pass Catalog (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Declare which optional compiler passes and evidence providers exist, schedule the ones a request selected over graph IR, merge their evidence, and fingerprint artifacts so a reusable analysis is invalidated when its inputs move; does not implement any individual analysis, own the on-disk evidence cache, or expose a transport.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One pass catalog and one provider registry sharing a single scheduling seam.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `evidence_batches`, `provider_analyses`
- **Outputs:** `optional_evidence`, `pass_catalog`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Optional passes SHALL NOT be advertised as default behavior without measurement.
  - `EvidenceStage:` Observed
- **[Conditional]** IF two registered passes share a name THEN catalog construction SHALL raise rather than let one silently shadow the other.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a pass declares a cache scope other than `none` THEN it SHALL also declare itself deterministic.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Merged provider evidence SHALL NOT introduce an edge whose endpoints are absent from the graph.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Artifact and analysis caches SHALL be bounded, evicting least-recently-used entries rather than growing with the session.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-PC-001:** A pass is a declared contract (`requires` / `produces` / `preserves` / `cost`) before it is a callable, so the set of optional capabilities can be answered without importing any analysis.
- **ADR-PC-002:** The package export surface is lazy (PEP 562): building the CLI parser needs only `COMPILER_PASS_NAMES`, and eager imports made every consumer pay for the whole platform stack.
- **ADR-PC-003:** Cache eligibility is derived from the pass contract rather than configured per call, because a non-deterministic pass that is allowed to cache is indistinguishable from a correct one until a rerun disagrees.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/__init__.py`, `src/graphgraph/platform/artifacts.py`, `src/graphgraph/platform/compiler.py`, `src/graphgraph/platform/contracts.py`
- **Test Surface Seam:** `tests/test_platform.py`, `tests/test_public_contracts.py`, `tests/test_surface_constants.py`

## 7. Measurement Seams

- **Primary Metric:** `optional_pass_marginal_recall` (`direction: higher` vs the pass being off)
- **Correctness Backpressure:** `components/platform/checks.sh`
- **Telemetry Surface:** pass catalog and contracts, artifacts compiled vs reused, provider receipts, invalidation receipts.
- **Branching Policy:** isolated candidate; an optional pass becomes default only on measured gain.
- **Known granularity gap:** this component has no evaluation probe script at all. The parent's `optional_pass_marginal_recall` has no experiment design yet — which pass, against which held-out panel, and against which off-baseline is unfixed — so no number is claimed for this leaf and the metric name above is a target, not a measurement.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the pass contract is what lets an optional capability be advertised, costed, and cached without being on by default, which is the promotion gate this whole subtree exists to enforce.
- **Selected:** in-repo pass catalog and provider registry on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Plugin/entry-point registry | Import cost and indirection for a closed, in-repo pass set; also loses the static contract table. |
  | Generic pipeline/DAG framework | Adds scheduling vocabulary for three passes and removes no decision. |
  | `functools.lru_cache` for analyses | Keyed on arguments, not on artifact revision and digest, so it cannot express the invalidation invariant. |

- **Fit gap:** the catalog schedules; it does not decide promotion. Promotion remains a measured decision recorded outside this leaf.
- **Seam:** `src/graphgraph/platform/compiler.py`
- **Exit cost:** MEDIUM — the pass contract shape is read by transport and diagnostic surfaces.
- **Cost model:** local CPU and bounded in-process caches; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unavailable pass is reported as unavailable and dropped from the schedule; the compile proceeds without it.
- **Open questions:** OW-Q08
