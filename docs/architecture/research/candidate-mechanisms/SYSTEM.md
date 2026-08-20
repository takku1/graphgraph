# Candidate Mechanisms (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Hold unpromoted retrieval and coverage mechanisms so they can be scored against production without being on the production path; does not own the claim record or ship a default behavior change.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Off-path candidate mechanisms sharing one promotion gate.

## 3. Interface Contracts

- **Inputs:** `registered_claims`
- **Outputs:** `research_scores`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A candidate SHALL NOT be described as promotable on a bare field-ranked baseline, as checked by `tests/test_attention_field_coupling.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Production retrieval SHALL NOT import this module; such an import is a defect rather than an optimization.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a candidate is evaluated THEN it SHALL be measured inside the production ranking path rather than against a reimplemented baseline, so the comparison is not to a strawman.
  - `EvidenceStage:` Measured

## 5. Architectural Decisions (ADRs)

- **ADR-CM-001:** Candidates stay off the hot path until they pass their promotion gate; the default behavior does not change to accommodate an experiment.
- **ADR-CM-002:** Further influence-field tuning is refuted and closed. It is not reopened without a task set capable of detecting a field contribution at all — an experiment that cannot fail is not an experiment.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/research/attention_field.py`, `src/graphgraph/research/static_cover.py`
- **Test Surface Seam:** `tests/test_attention_field_coupling.py`, `tests/test_attention_field_research.py`, `tests/test_static_cover_research.py`

## 7. Measurement Seams

- **Primary Metric:** `registry_dangling_sources` (target `0`, `direction: lower`)
- **Evaluation Gate Path:** `components/research/measure.sh`
- **Correctness Backpressure:** `components/research/checks.sh`
- **Telemetry Surface:** experiment scores, candidate-vs-production deltas.
- **Branching Policy:** isolated candidate; production retrieval imports of `research/` are a defect.
- **Known granularity gap:** this leaf shares the component's registry metric. A candidate's own promotion measurement is defined per experiment against the retrieval eval harness, not by a standing metric here.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the mechanisms under test are this project's own hypotheses about retrieval; there is nothing to procure.
- **Selected:** in-repo laboratory on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | networkx / igraph | The oracle is exact and small; a library approximation is the thing under test. |
  | Notebooks | Not an executable gate and not reviewable as a diff. |

- **Fit gap:** the oracle does not scale; it is a reference, not a runtime.
- **Seam:** `src/graphgraph/research/attention_field.py`
- **Exit cost:** LOW — unwired from production.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a broken candidate fails its own tests; production behavior is unchanged.
- **Open questions:** OW-P1, OW-Q10, RF-01
