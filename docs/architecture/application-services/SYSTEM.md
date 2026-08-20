# Application Services (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Orchestrate compile, cache, freshness, and control receipts above retrieval and planning; does not re-implement ranking or packet encoding.

## 2. Sub-System Decomposition

- **[Compile Request Path](./compile-request-path/SYSTEM.md)** — the one `CompilerDriver` schedule from request to control receipt and response envelope.
- **[Graph Lifecycle and Cache Identity](./graph-lifecycle/SYSTEM.md)** — build, refresh, and validate the saved graph, and decide what a cached answer is keyed on.
- **[Project Status and Freshness](./status-and-freshness/SYSTEM.md)** — report whether the active build can be trusted and what the project looks like.

## 3. Interface Contracts

- **Inputs:** `query_text`, `native_store`, `task_subgraph`
- **Outputs:** `control_receipt`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Transport adapters SHALL NOT reproduce the compiler-driver schedule.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-AS-001:** Services orchestrate; they do not re-implement retrieval or planning.
- **ADR-AS-002:** `CompilerDriver.compile(DriverRequest)` is the single external compile seam.
- **ADR-AS-003:** Anchor discovery is the service's job, not the caller's.
- **ADR-AS-004:** Decomposed at the three failure modes the pre-split leaf already carried in its own invariant list — a request answered with the wrong schedule or an over-budget envelope, a saved graph built or keyed wrongly, and a build reported as trustworthy when it is not. Each pre-split invariant lands in exactly one child. The seam is real rather than a file-tree rename because the lifecycle and status children serve callers that never compile a packet at all (`scan`, `status`), while the request path consumes their outputs without owning them.
