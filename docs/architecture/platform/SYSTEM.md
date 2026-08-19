# Platform and Evidence (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Supply optional CPG, inference, and compiler-pass evidence into the same graph IR; does not become default behavior without a measured promotion, and is not the unimplemented scanner `cpg` mode.

## 2. Sub-System Decomposition

- **[Compiler Pass Catalog](./pass-catalog/SYSTEM.md)** — register the passes and providers, schedule the requested ones, and fingerprint what may be reused.
- **[Evidence Persistence](./evidence-persistence/SYSTEM.md)** — cache provider IR across runs and refuse a batch that no longer matches its source.
- **[Optional Analysis Providers](./analysis-providers/SYSTEM.md)** — the individual on-demand analyses and exports that run only when asked.
- **[Observability and Local Surfaces](./observability-surfaces/SYSTEM.md)** — record what happened over time, measure it, and serve it on a local host.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `source_corpus`
- **Outputs:** `optional_evidence`

## 4. Invariants (EARS + Epistemic Stage)

- **[Event-driven]** WHEN a required artifact revision or content digest changes THEN a cached analysis SHALL be invalidated, as checked by `tests/test_platform.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-PL-001:** Inference is a bounded, Horn-style, budget-capped optional pass — off by default.
- **ADR-PL-002:** SQLite is acceptable for the evidence store because it is embedded stdlib.
- **ADR-PL-003:** Platform capabilities are research-sensitive until they pass the promotion gate.
- **ADR-PL-004:** Decomposed at the four failure modes the pre-split leaf already carried in one invariant list — a pass or provider being advertised and scheduled wrongly, a persisted analysis outliving the source it was computed from, one individual analysis being unavailable or wrong, and a longitudinal record or local surface failing to ingest or serve. Each pre-split invariant lands in exactly one child; the children are separable because three of them can be entirely absent and the compile path still answers, which is the definition of "optional" this parent claims.
