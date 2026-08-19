# Context-Packet Encoding (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Serialize a selected subgraph into a mechanically validated, token-measured packet whose consumer is an LLM, not a person; does not own retrieval or persist the native store.

## 2. Sub-System Decomposition

- **[Packet Target Catalog](./target-catalog/SYSTEM.md)** — declare every advertised format once, cold-start safe, with its renderer, validator, and cost model behind lazy references.
- **[Packet Rendering](./packet-rendering/SYSTEM.md)** — encode a subgraph into a chosen target's text without inventing nodes or edges.
- **[Packet Validation](./packet-validation/SYSTEM.md)** — decide mechanically whether rendered text is a well-formed instance of the format it claims.
- **[Token Estimation](./token-estimation/SYSTEM.md)** — price packet text in calibrated token units without a runtime tokenizer.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`, `query_plan`
- **Outputs:** `context_packet`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A public format SHALL generate and validate end-to-end or remain unadvertised.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CP-001:** Format is chosen by measured token cost against a real tokenizer. Human readability is not a design constraint; the packet is the LLM-facing instruction stream.
- **ADR-CP-002:** The shipped estimator is a calibrated proxy; `tiktoken` is a measurement instrument, not a runtime dependency.
- **ADR-CP-003:** Target behavior is registered atomically in one cold-start-safe catalog.
- **ADR-CP-004:** Decomposed at the four responsibilities the pre-split leaf named in its own decomposition line, each of which fails in a way the others cannot detect. A catalog failure advertises a format nothing can render; a renderer failure emits text no consumer can use; a validator failure is the dangerous one, because a validator that accepts everything reports success on a broken packet; an estimator failure leaves every packet correct and only the ranking between formats wrong. The estimator is the only child with an accuracy gate of its own (OW-AC-07), which is itself evidence that the four are measured separately.
