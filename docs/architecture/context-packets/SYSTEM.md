# Context-Packet Encoding (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Serialize a selected subgraph into a mechanically validated, token-measured packet whose consumer is an LLM, not a person; does not own retrieval or persist the native store.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One `TargetSpec` catalog plus encoders, validators, and the calibrated estimator.

## 3. Interface Contracts

- **Inputs:** `task_subgraph`, `query_plan`
- **Outputs:** `context_packet`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF validation fails THEN THE SYSTEM SHALL NOT claim structural success, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF selecting a cheaper encoding THEN identity-safe semantics SHALL be preserved, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Token claims used to rank formats SHALL use the calibrated estimator gated by `components/context-packets/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** A public format SHALL generate and validate end-to-end or remain unadvertised.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-CP-001:** Format is chosen by measured token cost against a real tokenizer. Human readability is not a design constraint; the packet is the LLM-facing instruction stream.
- **ADR-CP-002:** The shipped estimator is a calibrated proxy; `tiktoken` is a measurement instrument, not a runtime dependency.
- **ADR-CP-003:** Target behavior is registered atomically in one cold-start-safe catalog.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/packet_targets.py`, `src/graphgraph/packets/__init__.py`, `src/graphgraph/packets/metrics.py`, `src/graphgraph/packets/renderers.py`, `src/graphgraph/packets/validation.py`
- **Test Surface Seam:** `tests/test_packets.py`, `tests/test_public_contracts.py`.

## 7. Measurement Seams

- **Primary Metric:** `packet_token_units` at fixed recall (`direction: lower`); estimator MAE `<=5%`, p95 `<=10%`
- **Evaluation Gate Path:** `components/context-packets/measure.sh`
- **Correctness Backpressure:** `components/context-packets/checks.sh`
- **Telemetry Surface:** target identity, token units, validation report, adaptive-minimization receipt.
- **Branching Policy:** isolated candidate; no format inversion; dead-format guard must stay green.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — cheapest representation an LLM can interpret is the research question; the encoding is the product. `tiktoken` 0.13.0 is adopted only as the measurement instrument under the `benchmark` extra.
- **Selected:** in-repo renderers and estimator on Python 3.10; tiktoken 0.13.0 for calibration only
- **Standard / protocol:** none — the packet is a prompt-boundary format, not a wire format
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | JSON / YAML | Verbose identifier-heavy baseline this project measures against. |
  | LLMLingua-family compressors | Graph-blind; they break topological references. |
  | Protobuf / MessagePack | Efficient on the wire, unreadable at the prompt boundary. |
  | Bundling a tokenizer at runtime | Adds a vendor dependency to every scan for a budgeting estimate. |

- **Fit gap:** the proxy is whitespace-blind, so layout decisions need a real tokenizer.
- **Seam:** `src/graphgraph/packets/metrics.py`
- **Exit cost:** MEDIUM — historical token figures are denominated in the estimator.
- **Cost model:** no runtime service spend; tiktoken is optional for gates.
- **Liability transferred:** tokenizer accuracy when the `benchmark` extra is present.
- **Operational owner:** us
- **Failure mode:** tiktoken absent means calibration gates cannot run; the runtime estimator still works.
- **Open questions:** OW-Q05
