# Result Quality (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Score an assembled retrieval result and derive affected-test recommendations from it; does not select the subgraph, change ranking, or encode the packet.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One scoring and recommendation phase over the selected result.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`
- **Outputs:** `quality_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Answerability SHALL report minimum-evidence and neighborhood-completeness as separate facts rather than collapsing them into one flag.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Retrieval confidence SHALL be derived from anchor evidence rather than restating text-only query-class certainty.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a change set is supplied THE SYSTEM SHALL recommend affected tests from declared test edges rather than from filename similarity, as checked by `tests/test_retrieval_section_relevance.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF no evidence supports an answer THEN the reported confidence SHALL be low rather than defaulted, as checked by `tests/test_abstention_red_controls.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-RQ-001:** Confidence is a property of retrieved evidence, not of query parsing. A constant class-certainty score reported as confidence is a number that cannot be wrong, and therefore cannot be useful.
- **ADR-RQ-002:** Completeness and sufficiency are reported separately. A neighborhood can be sufficient to answer while known to be truncated, and conflating the two hides the truncation.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/quality.py`, `src/graphgraph/retrieval/relevance.py`, `src/graphgraph/retrieval/test_recommendations.py`
- **Test Surface Seam:** `tests/test_retrieval_section_relevance.py`, `tests/test_abstention_red_controls.py`, `tests/test_retrieval.py`

## 7. Measurement Seams

- **Primary Metric:** `answer_confidence_ece` (target `<0.10`, `direction: lower`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** answerability status, retrieval confidence, minimum-evidence and completeness flags, recommended tests.
- **Branching Policy:** isolated candidate; a confidence change must move calibration error, not just the reported number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — a machine-checkable receipt stating how far the evidence goes is the product claim that distinguishes this from a search index.
- **Selected:** in-repo quality scoring on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Model-scored self-assessment | Adds a model call inside a millisecond budget and is unfalsifiable offline. |
  | Fixed confidence per query class | Constant by construction; cannot detect a wrong answer. |

- **Fit gap:** calibration is fitted on this project's labelled corpus; held-out calibration remains open.
- **Seam:** `src/graphgraph/retrieval/quality.py`
- **Exit cost:** LOW — scoring reads the assembled result and emits a receipt.
- **Cost model:** in-process CPU.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** missing evidence yields low confidence rather than a default.
- **Open questions:** OW-AC-04, OW-P0-04
