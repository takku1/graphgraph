# Research Laboratory (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Hold unpromoted candidate mechanisms with an executable claim registry; does not own production ranking and SHALL NOT sit on the hot path.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Registry plus off-path laboratory modules.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `research_scores`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Every claim in the registry SHALL resolve to a source path that exists, as enforced by `tests/test_research_registry.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A candidate SHALL NOT be described as promotable on a bare field-ranked baseline, as checked by `tests/test_attention_field_coupling.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Mechanisms in this laboratory SHALL be off the production path.
  - `EvidenceStage:` Observed
- **[Conditional]** IF an experiment is recorded THEN its claim, mechanism, and source SHALL be registered together, as checked by `tests/test_research_registry.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-RE-001:** Research code ships in the package but never on the hot path.
- **ADR-RE-002:** The claim registry is executable; a deleted source is a test failure.
- **ADR-RE-003:** Negative results are retained with the same status as positive ones.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/benchmark/extraction_density.py`, `src/graphgraph/benchmark/relation_latency.py`, `src/graphgraph/research/__init__.py`, `src/graphgraph/research/attention_field.py`, `src/graphgraph/research/registry.py`, `src/graphgraph/research/static_cover.py`
- **Test Surface Seam:** `tests/test_research_registry.py`, `tests/test_attention_field_coupling.py`, `tests/test_attention_field_research.py`, `tests/test_static_cover_research.py`.

## 7. Measurement Seams

- **Primary Metric:** `registry_dangling_sources` (target `0`, `direction: lower`)
- **Evaluation Gate Path:** `components/research/measure.sh`
- **Correctness Backpressure:** `components/research/checks.sh`
- **Telemetry Surface:** claim/source completeness and experiment scores.
- **Branching Policy:** isolated candidate; production retrieval imports of `research/` are a defect.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — falsifying the project's own hypotheses is the research programme; notebooks cannot gate CI.
- **Selected:** in-repo laboratory on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Notebooks | Not an executable gate and not reviewable as a diff. |
  | networkx / igraph | The oracle is exact and small; a library approximation is the thing under test. |
  | Deleting a line after a negative result | The refutation is load-bearing. |

- **Fit gap:** the oracle does not scale; it is a reference, not a runtime.
- **Seam:** `src/graphgraph/research/registry.py`
- **Exit cost:** LOW — unwired from production.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a broken registry fails the test suite; production behavior is unchanged.
- **Open questions:** OW-P1, OW-Q10, RF-01
