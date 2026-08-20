# Optional Analysis Providers (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Derive extra, clearly-provenanced views from graph IR on request — CPG evidence, rule inference, community hierarchy, repair grounding, cross-project federation, and portable export; does not register itself as default, persist its own results, or replace the scanner's extraction.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One provider shape — read graph IR, return derived evidence and a receipt — repeated per analysis.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `source_corpus`
- **Outputs:** `provider_analyses`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** The working `CpgEvidenceProvider` SHALL NOT be described as the scanner `cpg` frontend.
  - `EvidenceStage:` Observed
- **[Conditional]** IF scanner extraction already compiled an unchanged `SourceIR` revision THEN `CpgEvidenceProvider` SHALL reuse its `SyntaxIR`, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a grammar is unavailable for a source suffix THEN THE SYSTEM SHALL record the reason as a warning and skip that path rather than fail the collection.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Inference SHALL be bounded by an explicit edge budget and SHALL report truncation rather than run to exhaustion.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** An inferred edge SHALL carry `inferred` provenance and confidence no higher than the weakest premise it was derived from.
  - `EvidenceStage:` Observed
- **[Conditional]** IF an export format is not supported THEN THE SYSTEM SHALL raise rather than write a file in a guessed format.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Community detection SHALL be deterministic for a given graph, so a hierarchy is comparable across revisions.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-AP-001:** Inference is a bounded, Horn-style, budget-capped optional pass — off by default. An unbounded reasoner is the failure this leaf is shaped to avoid, not a feature it lacks.
- **ADR-AP-002:** Every derived edge is provenance-tagged (`inferred`, `structural_provider`, `python_ast_provider`, `runtime_trace`) so a consumer can separate observed structure from derived claims without asking this leaf.
- **ADR-AP-003:** Community detection uses in-repo deterministic label propagation rather than an optional graph library, because a nondeterministic partition makes revision-to-revision comparison meaningless and pulls a dependency for one function.
- **ADR-AP-004:** Providers degrade to "unavailable" per path. A missing grammar is an expected environment state on a multi-language corpus, not an error condition.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/cpg.py`, `src/graphgraph/platform/federation.py`, `src/graphgraph/platform/inference.py`, `src/graphgraph/platform/intelligence.py`, `src/graphgraph/platform/interop.py`, `src/graphgraph/platform/repair.py`
- **Test Surface Seam:** `tests/test_platform.py`, `tests/test_mcp_machine_contract.py`, `tests/test_module_boundaries.py`

## 7. Measurement Seams

- **Primary Metric:** `optional_pass_marginal_recall` (`direction: higher` vs the pass being off)
- **Correctness Backpressure:** `components/platform/checks.sh`
- **Telemetry Surface:** per-provider receipts (nodes/edges emitted, accepted, rejected, truncated), grammar-unavailable warnings, inference rule counts.
- **Branching Policy:** isolated candidate; a provider becomes default only on measured gain.
- **Known granularity gap:** this component has no evaluation probe script at all. `optional_pass_marginal_recall` is the leaf that most needs it — it is exactly a with-provider vs without-provider comparison — but the held-out panel and off-baseline to run it against are not fixed, so no value is claimed here.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Fatal fit gap — off-the-shelf CPG engines and reasoners bring a daemon or an unbounded solver into a cold-start local process, and the budget cap is the property this leaf exists to guarantee.
- **Selected:** in-repo providers on Python 3.10, reusing the scanner's tree-sitter frontends
- **Standard / protocol:** GraphML, Cypher, and JSON/JSONL on the export side only
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Joern | JVM-hosted second analysis platform alongside the one already running. |
  | General Datalog engine | Unbounded; the opposite of the explicit edge budget. |
  | `networkx` for community detection | A dependency for one function, and its defaults are not deterministic across runs. |
  | Graphiti / temporal graph DB | Database plus LLM and embedding services for a local-first tool. |

- **Fit gap:** none of these providers may become load-bearing without the promotion gate. FastEmbed and semantic indexing live under Semantic Retrieval, not here.
- **Seam:** `src/graphgraph/platform/cpg.py`
- **Exit cost:** LOW — optional by design; each provider can be removed without touching the catalog contract.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a provider that cannot run reports unavailable with a reason; the query proceeds without that evidence.
- **Open questions:** OW-Q08
