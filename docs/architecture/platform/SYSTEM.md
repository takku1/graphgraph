# Platform and Evidence (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Supply optional CPG, inference, and compiler-pass evidence into the same graph IR; does not become default behavior without a measured promotion, and is not the unimplemented scanner `cpg` mode.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Optional providers behind one pass catalog.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `source_corpus`
- **Outputs:** `optional_evidence`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Optional passes SHALL NOT be advertised as default behavior without measurement.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a semantic sidecar mismatches active graph topology THEN THE SYSTEM SHALL reject it as stale, as checked by `tests/test_cycle5_regressions.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** The working `CpgEvidenceProvider` SHALL NOT be described as the scanner `cpg` frontend.
  - `EvidenceStage:` Observed
- **[Conditional]** IF scanner extraction already compiled an unchanged `SourceIR` revision THEN `CpgEvidenceProvider` SHALL reuse its `SyntaxIR`, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN a required artifact revision or content digest changes THEN a cached analysis SHALL be invalidated, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-PL-001:** Inference is a bounded, Horn-style, budget-capped optional pass — off by default.
- **ADR-PL-002:** SQLite is acceptable for the evidence store because it is embedded stdlib.
- **ADR-PL-003:** Platform capabilities are research-sensitive until they pass the promotion gate.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/__init__.py`, `src/graphgraph/platform/artifacts.py`, `src/graphgraph/platform/benchmarking.py`, `src/graphgraph/platform/change.py`, `src/graphgraph/platform/compiler.py`, `src/graphgraph/platform/contracts.py`, `src/graphgraph/platform/cpg.py`, `src/graphgraph/platform/evaluation.py`, `src/graphgraph/platform/evidence_store.py`, `src/graphgraph/platform/federation.py`, `src/graphgraph/platform/inference.py`, `src/graphgraph/platform/intelligence.py`, `src/graphgraph/platform/interop.py`, `src/graphgraph/platform/memory.py`, `src/graphgraph/platform/persistence.py`, `src/graphgraph/platform/repair.py`, `src/graphgraph/platform/server.py`, `src/graphgraph/platform/temporal.py`, `src/graphgraph/platform/tracing.py`
- **Test Surface Seam:** `tests/test_platform.py`, `tests/test_research_registry.py`, `tests/test_runtime_coverage.py`.

## 7. Measurement Seams

- **Primary Metric:** `optional_pass_marginal_recall` (`direction: higher` vs the pass being off)
- **Correctness Backpressure:** `components/platform/checks.sh`
- **Telemetry Surface:** artifacts compiled vs reused, pass catalog, invalidation receipts.
- **Branching Policy:** isolated candidate; an optional pass becomes default only on measured gain.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Fatal fit gap — off-the-shelf CPG engines and reasoners bring a daemon or unbounded solver into a cold-start local process.
- **Selected:** in-repo providers; Python 3.10 `sqlite3` for the evidence store
- **Standard / protocol:** SQL for the evidence store
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Joern | JVM-hosted second analysis platform. |
  | General Datalog engine | Unbounded; opposite of the budget cap. |
  | Hosted embedding APIs | Network and per-token cost inside a local-first tool. |
  | Graphiti / temporal graph DB | Database plus LLM/embedding services. |

- **Fit gap:** none of these passes may become load-bearing without the promotion gate. FastEmbed lives under Semantic Retrieval, not here.
- **Seam:** `src/graphgraph/platform/compiler.py`
- **Exit cost:** LOW — optional by design.
- **Cost model:** local CPU and a stdlib SQLite file; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a provider that cannot run reports unavailable; the query proceeds without that evidence.
- **Open questions:** OW-Q08
