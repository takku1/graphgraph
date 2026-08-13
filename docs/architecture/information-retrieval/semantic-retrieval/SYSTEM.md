# Semantic Retrieval (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Supply meaning-based code and documentation evidence to the existing structural retriever when lexical identity is insufficient; does not own structural expansion, final packet selection, confidence policy, or implicit model installation.

## 2. Sub-System Decomposition

- **[Embedding Backend](./embedding-backend/SYSTEM.md)** — turns text into a versioned query vector through an optional local model.
- **[Semantic Store](./semantic-store/SYSTEM.md)** — publishes and queries graph-bound vector generations with balanced code/prose results.

## 3. Interface Contracts

- **Inputs:** graph snapshot, semantic manifest, query text, source mode, and backend configuration.
- **Outputs:** balanced semantic candidates plus backend identity, store state, and load/embed/score receipts.

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a compatible current semantic generation exists and the query is non-exact THEN THE SYSTEM SHALL make meaning-based evidence available without requiring lexical weakness or a warm process.
  - `EvidenceStage:` Refuted
- **[Conditional]** IF semantic state is missing, stale, legacy, or incompatible THEN THE SYSTEM SHALL avoid an implicit build and report an actionable state.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN semantic candidates are returned THE SYSTEM SHALL preserve graph node identity and expose enough provenance to attribute latency and evidence category.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-SR-001:** Semantic evidence enriches the canonical Evidence Graph; it never becomes a parallel answer store.
- **ADR-SR-002:** The dependency-free lexical/hash behavior remains available when the optional local model is absent, but it cannot substantiate paraphrase-recall claims.
- **ADR-SR-003:** Query policy consumes one deep semantic-retrieval Interface; storage layout and category balancing remain hidden Implementation details.
