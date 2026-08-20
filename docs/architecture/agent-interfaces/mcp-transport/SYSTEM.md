# MCP Transport (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Serve the shared instruction set from a long-lived process over the Model Context Protocol; does not own retrieval semantics, packet catalogs, or implicit graph rebuilds.

## 2. Sub-System Decomposition

- **[Protocol Session and Capability Identity](./protocol-session/SYSTEM.md)** — JSON-RPC framing, process residency, and the machine-readable capability record.
- **[Tool Schemas and Handlers](./tool-handlers/SYSTEM.md)** — the advertised tool catalog and the handlers behind it.

There is no MCP SDK in the inventory, so both children are custom code over the protocol; the split is a seam inside our own transport, not a procurement boundary.

## 3. Interface Contracts

- **Inputs:** `query_text`, `context_packet`, `control_receipt`
- **Outputs:** `transport_response`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a tool is read-only THEN it SHALL NOT trigger a silent full reindex.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-MCP-001:** Adopt MCP rather than a bespoke HTTP/RPC daemon so existing agent clients can register the server.
- **ADR-MCP-002:** Residency is a process-lifetime property, not a missing component.
- **ADR-MCP-003:** Decomposed at two independent failure modes: the session layer can break framing, residency, or the advertised identity while every handler still returns the right answer, and a handler can return the wrong answer while the session is perfectly well-formed. The warm-reuse and identity invariants land on the session; the read-only invariant lands on the handlers.
