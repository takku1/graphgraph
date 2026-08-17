# Agent Interfaces (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Expose one retrieval instruction set through a resident MCP server and a cold-start CLI; does not own ranking, storage, or a second product API.

## 2. Sub-System Decomposition

- **[MCP Transport](./mcp-transport/SYSTEM.md)** — long-lived agent session over the Model Context Protocol.
- **[CLI Transport](./cli-transport/SYSTEM.md)** — one-shot scripting and diagnostics.

## 3. Interface Contracts

- **Inputs:** `query_text`, `context_packet`, `control_receipt`
- **Outputs:** `transport_response`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Benchmarks that time repeated CLI calls SHALL label cold-start; they are not core retrieval latency, as checked by `components/agent-interfaces/measure.sh`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Packed exact-relation latency SHALL be published with small/medium/large graph-size strata, as checked by `tests/test_relation_latency.py` and `components/agent-interfaces/relation_latency_baseline.json`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** Read-only query tools SHALL NOT imply mutation or a silent full reindex.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A capability exposed on one transport SHALL be exposed on the other, per ADR-AI-002 and `tests/test_mcp_machine_contract.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-AI-001:** Resident MCP is the interactive transport; CLI is cold-start and scripting.
- **ADR-AI-002:** Both transports sit over one instruction set. A one-sided capability is a defect.
