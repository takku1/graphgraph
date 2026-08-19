# Packet Rendering (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Encode a selected subgraph into the text of a chosen target format, preserving identity-safe semantics when a cheaper encoding is selected; does not declare which formats exist, decide whether the result validates, or price it.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One encoder family sharing a relation ordering and a node-projection rule.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`, `target_spec`
- **Outputs:** `context_packet`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF selecting a cheaper encoding THEN identity-safe semantics SHALL be preserved, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A rendered packet SHALL reference only nodes and edges present in the source graph, so a compressed encoding cannot introduce a target that does not exist.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Section markers SHALL be emitted as standalone lines, because the validator distinguishes a section header from the same characters appearing inside a payload line.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-PR-001:** Format is chosen by measured token cost against a real tokenizer. Human readability is not a design constraint; the packet is the LLM-facing instruction stream.
- **ADR-PR-002:** Relation identifiers are interned per packet rather than spelled out per edge, which is where the compact formats' savings come from; the interning table is emitted first so the packet stays self-describing.
- **ADR-PR-003:** Facts per node are sized by the same shape recommendation the planner uses, so the renderer cannot quietly spend a budget the plan did not grant.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/packets/renderers.py`
- **Test Surface Seam:** `tests/test_packets.py`

## 7. Measurement Seams

- **Primary Metric:** `packet_token_units` (summed over the gate's query set at fixed recall, `direction: lower`)
- **Evaluation Gate Path:** `components/context-packets/measure.sh`
- **Correctness Backpressure:** `components/context-packets/checks.sh`
- **Telemetry Surface:** rendered format, node and edge counts, relation-interning table size, adaptive-minimization receipt.
- **Branching Policy:** isolated candidate; no format inversion — a change that makes a previously cheaper format more expensive than its rival is a revert, not a pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — the cheapest representation an LLM can still interpret is the project's research question, so the encoding is the product rather than a serialization detail.
- **Selected:** in-repo renderers on Python 3.10, stdlib only
- **Standard / protocol:** none — the packet is a prompt-boundary format, not a wire format
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | JSON / YAML | Verbose identifier-heavy baseline this project measures against. |
  | LLMLingua-family compressors | Graph-blind; they break topological references. |
  | Protobuf / MessagePack | Efficient on the wire, unreadable at the prompt boundary. |
  | A templating engine (Jinja) | A dependency and a second syntax for line assembly that is already a list append. |

- **Fit gap:** the renderers assume the subgraph is already selected; they do not trim to fit a budget.
- **Seam:** `src/graphgraph/packets/renderers.py`
- **Exit cost:** MEDIUM — recorded token comparisons are denominated in these formats.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a node or edge missing from the source graph is dropped from the packet rather than emitted as a dangling reference.
- **Open questions:** OW-Q05
