# GraphGraph (L0)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Compile a local codebase query into the cheapest mechanically validated context packet whose target is LLM interpretation, not a human reader; does not own hosted model scoring, a general-purpose compiler, or a second graph product beside the native IR.

## 2. Sub-System Decomposition

- **[Static Analysis](./static-analysis/SYSTEM.md)** — deterministic corpus extraction into IR emissions.
- **[Intermediate Representation](./intermediate-representation/SYSTEM.md)** — canonical in-memory graph model.
- **[Persistent Storage](./storage/SYSTEM.md)** — native `.gg` persistence and incremental splice.
- **[Query Planning](./query-planning/SYSTEM.md)** — class, budget, and packet-choice routing.
- **[Information Retrieval](./information-retrieval/SYSTEM.md)** — task-local subgraph under those budgets.
- **[Context-Packet Encoding](./context-packets/SYSTEM.md)** — model-facing serialization and validation.
- **[Application Services](./application-services/SYSTEM.md)** — compile, cache, freshness, and control receipts.
- **[Agent Interfaces](./agent-interfaces/SYSTEM.md)** — CLI and resident MCP transports over one instruction set.
- **[Platform and Evidence](./platform/SYSTEM.md)** — optional CPG, inference, and compiler-pass evidence.
- **[Project Atlas](./project-atlas/SYSTEM.md)** — derived orientation artifact.
- **[Acceptance and Qualification](./acceptance/SYSTEM.md)** — black-box ship verdict.
- **[Evaluation Analysis](./evaluation-analysis/SYSTEM.md)** — whether a measurement means what it claims.
- **[Research Laboratory](./research/SYSTEM.md)** — unpromoted candidates with an executable claim registry.
- **[Project Representation](./representation/SYSTEM.md)** — opt-in project shaping before render.
- **[Maintainability Convergence](./maintainability/SYSTEM.md)** — structural ratchets and behavior-preserving decomposition.

## 3. Interface Contracts

- **Inputs:** `source_corpus`, `query_text`
- **Outputs:** `context_packet`, `control_receipt`, `native_store`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** The system SHALL treat the in-memory graph IR as the logical model and the native `.gg` store as the default persistent form.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a packet fails mechanical validation THEN THE SYSTEM SHALL NOT present it as a successful structural answer, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a claim is about external model answer quality THEN THE SYSTEM SHALL require explicit live scoring rather than retrieval shape alone.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN transport is a one-shot CLI process THE SYSTEM SHALL report cold-start latency separately from resident retrieval latency, as checked by `components/agent-interfaces/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Incomplete product and research work SHALL be tracked only in `ROADMAP.md`.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-001:** Prefer deterministic extraction; score any LLM extraction separately.
- **ADR-002:** Resident MCP is the interactive transport; CLI is cold-start and scripting.
- **ADR-003:** The packet is an LLM instruction stream. Human legibility is a cost the system declines to pay. If machine code is the native form for a CPU, the native form here is whatever token sequence the model actually consumes; `.gg` persistence and compact packet encodings exist for that target, not for a person reading a dump.
- **ADR-004:** Custom artifacts (native store, IR, packet ISA) are justified when a general database or document format is farther from that LLM target. A custom `.gg` store is the right persistence when the access pattern is whole-section materialization into that ISA, not when it looks nicer to a human.
- **ADR-005:** Format and store choice require a real-tokenizer measurement. Aesthetics and human readability are not evidence.
- **ADR-006:** Superiority claims are head-to-head on one machine or withdrawn.
- **ADR-007:** Expand a subsystem only when its decision class or failure mode is no longer uniform.

## 6. Leaf Execution & Test Seam

The public package surface is owned here. Domain implementations stay on child
nodes. `src/graphgraph/__init__.py` is the only file this node implements.

- **Implementation Files:** `src/graphgraph/__init__.py`, `src/graphgraph/__main__.py`, `src/graphgraph/distribution.py`, `src/graphgraph/version.py`
- **Test Surface Seam:** `tests/conftest.py`, `tests/test_public_contracts.py`
