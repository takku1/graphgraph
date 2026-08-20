# Concept and Terminology Layer (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Normalize labels into canonical term keys, detect and link the interpretation concepts that join documentation to code, and report whether that linking is dense enough to be used as retrieval evidence; does not define the record types, own traversal strength, or rank retrieval results.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One term normalizer feeding one concept registry and its coverage report.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `concept_links`, `concept_coverage`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF no source node was eligible for concept linking THEN THE SYSTEM SHALL report the coverage status as unavailable rather than as a zero coverage score.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Term normalization SHALL be a pure transform behind a size-bounded cache, so a long-lived resident process cannot retain every label it has ever seen.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A node's doc-or-code classification SHALL be derived from its declared kind and path rather than from retrieval-time scoring, so the same node classifies identically in every query.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CL-001:** External schemas bind loosely and only on ingest; the concept vocabulary is this project's, not an imported ontology's.
- **ADR-CL-002:** Concept link density is reported as a status with a reason (`unavailable` / `sparse` / `partial` / `strong`) rather than as a bare ratio, because a caller needs to know whether semantic evidence is usable at all before it weighs it.
- **ADR-CL-003:** Normalization is cached rather than precomputed. The cache is sized to the observed per-query working set, not to the process lifetime, so the bound is stated in terms of what one query touches.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/concepts/__init__.py`, `src/graphgraph/concepts/doccode.py`, `src/graphgraph/concepts/health.py`, `src/graphgraph/concepts/registry.py`, `src/graphgraph/concepts/terms.py`
- **Test Surface Seam:** `tests/test_concepts.py`

## 7. Measurement Seams

- **Primary Metric:** `expand_context_ms` (median of the timed expansions in the component gate, `direction: lower`)
- **Evaluation Gate Path:** `components/intermediate-representation/measure.sh`
- **Correctness Backpressure:** `components/intermediate-representation/checks.sh`
- **Telemetry Surface:** eligible/linked node counts, coverage status and reason, distinct term keys.
- **Branching Policy:** isolated candidate; concept-link health must not regress below the supported coverage threshold.
- **Known granularity gap:** this leaf currently shares the component-level `expand_context_ms` gate rather than carrying a concept-coverage metric of its own. Recorded as an open granularity gap rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — the normalizer is a handful of regular expressions and a frozen kind table; every NLP dependency considered would import a model to decide questions this answers from a node's declared kind.
- **Selected:** in-repo normalizer and concept registry on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | spaCy / NLTK lemmatization | Model download and import cost inside a cold-start budget for identifier splitting. |
  | An imported domain ontology (SKOS, schema.org) | Vocabulary far wider than the interpretation concepts this project links. |
  | Embedding-only concept detection | Not inspectable as a diff, and the registry exists so a link can be justified. |

- **Fit gap:** concept detection is lexical; paraphrase-only matches are a retrieval concern, not a terminology one.
- **Seam:** `src/graphgraph/concepts/registry.py`
- **Exit cost:** MEDIUM — term keys are embedded in concept node identifiers.
- **Cost model:** in-process memory; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** sparse linking is reported as sparse rather than silently used as strong evidence.
- **Open questions:** OW-Q04
