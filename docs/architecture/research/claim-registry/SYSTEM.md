# Claim Registry (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Bind every recorded research claim to its mechanism and to a source path that still exists, so a refutation cannot be quietly deleted; does not run experiments or score candidates.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One executable registry checked by a test rather than by review.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `registered_claims`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Every claim in the registry SHALL resolve to a source path that exists, as enforced by `tests/test_research_registry.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF an experiment is recorded THEN its claim, mechanism, and source SHALL be registered together, as checked by `tests/test_research_registry.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A refuted claim SHALL be retained with its refutation rather than removed, so the evidence that closed a line of work survives the line of work.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CR-001:** The registry is executable. A claim whose source was deleted is a failing test, not a stale document — this is the one invariant in the project mechanically strong enough to be recorded as more than assertion.
- **ADR-CR-002:** Rejected-claim evidence files are pinned by the registry. Any pruning of benchmark scripts must consult it first, because a file that looks unreferenced may be the sole evidence for a recorded refutation.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/research/__init__.py`, `src/graphgraph/research/registry.py`
- **Test Surface Seam:** `tests/test_research_registry.py`

## 7. Measurement Seams

- **Primary Metric:** `registry_dangling_sources` (target `0`, `direction: lower`)
- **Evaluation Gate Path:** `components/research/measure.sh`
- **Correctness Backpressure:** `components/research/checks.sh`
- **Telemetry Surface:** claim/source completeness, dangling source count.
- **Branching Policy:** isolated candidate; zero-tolerance invariant — any dangling source blocks.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — falsifying the project's own hypotheses and keeping the refutations executable is the research programme; notebooks cannot gate CI.
- **Selected:** in-repo registry on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Notebooks | Not an executable gate and not reviewable as a diff. |
  | A markdown findings log | Cannot fail a build when its evidence is deleted. |
  | Deleting a line after a negative result | The refutation is load-bearing. |

- **Fit gap:** the registry checks that sources exist, not that a claim's reasoning still holds.
- **Seam:** `src/graphgraph/research/registry.py`
- **Exit cost:** LOW — unwired from production.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a broken registry fails the test suite; production behavior is unchanged.
- **Open questions:** none
