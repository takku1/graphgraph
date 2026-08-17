# Information Retrieval (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Produce a task-local subgraph under token and latency budgets from a query and graph IR; does not own packet encoding, query-class policy, or implicit model installation.

## 2. Sub-System Decomposition

- **[Structural Retrieval](./structural-retrieval/SYSTEM.md)** — anchors, expansion, facets, and budgeted selection.
- **[Semantic Retrieval](./semantic-retrieval/SYSTEM.md)** — meaning-based evidence when lexical identity is insufficient.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `query_text`, `query_plan`
- **Outputs:** `task_subgraph`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF confidence is below policy THEN THE SYSTEM SHALL abstain rather than emit a large low-value packet, as checked by `tests/test_abstention_red_controls.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Minimum-evidence success SHALL be reported separately from full raw-neighborhood completeness.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Structural constraints SHALL be hard filters, not score terms.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-IR-001:** Lexical matching carries the current labelled task set; paraphrase recall is a separate gate (OW-AC-03).
- **ADR-IR-002:** Semantic embeddings are opt-in. The offline hash fallback is lexical in disguise.
- **ADR-IR-003:** Semantic evidence enriches the canonical graph; it never becomes a parallel answer store.
