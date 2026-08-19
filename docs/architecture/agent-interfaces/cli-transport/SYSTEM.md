# CLI Transport (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Expose the shared instruction set as a one-shot process for scripting, scan, and diagnostics; does not own retrieval algorithms or claim CLI latency as core retrieval latency.

## 2. Sub-System Decomposition

- **[Cold Command Surface](./cold-surface/SYSTEM.md)** — the import-light entry point, shared serialization, and static description commands.
- **[Query and Planning Commands](./query-commands/SYSTEM.md)** — retrieval, planning, evaluation, and platform compilation commands.
- **[Graph Lifecycle Commands](./lifecycle-commands/SYSTEM.md)** — scan, splice, removal, saved-graph IO, and packet cache.
- **[Environment and Installation Commands](./environment-commands/SYSTEM.md)** — diagnose the environment and install distribution artifacts.

## 3. Interface Contracts

- **Inputs:** `query_text`, `context_packet`, `control_receipt`
- **Outputs:** `transport_response`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN an exact lookup target is missing or `select --mode exists` is false THE SYSTEM SHALL exit 1, as checked by `tests/test_cli_mcp.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-CLI-001:** Parser construction stays import-light; runtime catalogs project from cold contracts.
- **ADR-CLI-002:** `graphgraph doctor` is the authority on environment capability, not documentation.
- **ADR-CLI-003:** Decomposed at four independent failure modes: the cold entry point can regain import weight without any command changing behavior; a query command can answer wrongly while the parser stays light; a lifecycle command can corrupt or refuse a saved graph without touching retrieval; and an environment or install command can misreport capability while every other command is correct. Each pre-split invariant lands in exactly one child.
