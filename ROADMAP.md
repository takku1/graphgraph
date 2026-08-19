# GraphGraph roadmap

This is the only Recurspec incomplete-work registry. Historical narrative and
receipts stay in [docs/open-work.md](docs/open-work.md); status for routing lives
here.

Statuses: `ready`, `blocked`, `research`, `deferred`, `done`.

## Recurspec adoption

Recurspec 0.2.0 defaults `--source-root` to `src/recurspec`. Structure and
reconcile commands against this repository must pass
`--source-root src/graphgraph`. There is no project-level override yet.

| ID | Outcome | Status | Contract |
|---|---|---|---|
| R-000 | Replace architecture prose with a valid Recurspec Contract Tree and this ROADMAP | done | [GraphGraph](docs/architecture/SYSTEM.md) |
| R-001 | Declare public package surface in §6 so `structure check --source-root src/graphgraph` is usable | done | [GraphGraph](docs/architecture/SYSTEM.md) — `Implementation Files` labels match the Structure Gate; `recurspec structure check --source-root src/graphgraph` PASS |
| R-002 | Per-leaf measurement granularity: split leaves currently share one component-level gate | ready | Contract nodes carrying a `Known granularity gap` line in §7. A real per-leaf metric or none — do not add a `measure.sh` emitting a placeholder |
| R-003 | Abstention cannot prove absence for a query built only of short or definition-shaped words | ready | [Request Feasibility](docs/architecture/information-retrieval/structural-retrieval/request-feasibility/SYSTEM.md) — `facet_is_provably_absent` returns False when both distinctive and content term sets are empty; no red control exercises this. Raised by the OW-AC-03 checker 2026-08-18 |
| R-004 | Facet reservations are seated in arrival order, so a recovered answer can land at the bottom of the packet | ready | [Facet Obligation](docs/architecture/information-retrieval/structural-retrieval/facet-obligation/SYSTEM.md) — ordering by facet evidence strength is untried; locus C03 recovered at MRR 0.091 (rank 11 of 12) |
| R-005 | Conceptual fixture disjointness is weaker than claimed | done | Fixed 2026-08-19. Queries rewritten as true paraphrases; the guard now compares query tokens (stemmed, stopword-free) against the whole **file** that answers them — label, docstring, and path — not just the identifier. On the corrected fixture, structural-only recall is **0.000**, confirming the previous 0.80 was an artifact of docstrings restating their queries |

## Agent-cycle product gaps

Indexed from `docs/open-work.md` section A.

| ID | Outcome | Status | Blocked by | Contract |
|---|---|---|---|---|
| OW-AC-01 | Resident exact-query p95 gated; tools visible in an agent session | ready | — | [MCP Transport](docs/architecture/agent-interfaces/mcp-transport/SYSTEM.md) — warm MCP `query_relations` p95 92.6 ms vs 250 ms SLO; initialize+tools/list exposes 24 tools; NEED_CHECKER |
| OW-AC-02 | Discovery selects a validated build; empty delta means fresh | ready | — | [Application Services](docs/architecture/application-services/SYSTEM.md) — `active_build` is validated/stale/invalid/absent; empty-delta incremental scan is a no-op; NEED_CHECKER |
| OW-AC-03 | ≥80% full recall on conceptual / lexically disjoint tasks with no exact-task regression | ready | — | [Structural Retrieval](docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md) — **re-measured 2026-08-19 on a corrected fixture (R-005)**. Structural-only: **0.000**. With a current semantic index: **0.800 (4/5)**, FIX-C01 the remaining miss, red control abstaining in both. The gate is met only where a semantic index exists and is current; this repo's own index is stale, and building one runs at ~42 nodes/s (>10 min for 14,547 nodes), so "current index" is not yet the default condition — see RF-02. Held-out locus panel not re-run against the corrected guard. NEED_CHECKER |
| OW-AC-04 | Unanswerable queries abstain (conf ≤0.2, ≤50 real tokens) instead of emitting large empty packets | ready | — | [Information Retrieval](docs/architecture/information-retrieval/SYSTEM.md) — RED compiled packet 21 tokens, conf 0.15; local conceptual misses abstain; scoped `doc_summary` no longer emptied; NEED_CHECKER |
| OW-AC-05 | Per-language resolved member-call precision ≥98% with volume tables | ready | — | [Name Resolution](docs/architecture/static-analysis/name-resolution/SYSTEM.md) — held-out TS/C#/Python/Go precision 1.0 (4/4); Go embedding promotes methods; polyglot volume table; NEED_CHECKER |
| OW-AC-06 | Machine response ≤1.15× evidence-packet tokens | done | — | [Agent Interfaces](docs/architecture/agent-interfaces/SYSTEM.md) |
| OW-AC-07 | Token estimator MAE ≤5%, p95 ≤10% | done | — | [Context-Packet Encoding](docs/architecture/context-packets/SYSTEM.md) |
| OW-AC-08 | Packed exact relation latency with graph-size strata | ready | — | [Agent Interfaces](docs/architecture/agent-interfaces/SYSTEM.md) — baseline in `components/agent-interfaces/relation_latency_baseline.json`; NEED_CHECKER |
| OW-AC-09 | Machine-readable capability identity on CLI and MCP | ready | — | [CLI Transport](docs/architecture/agent-interfaces/cli-transport/SYSTEM.md) — CLI and MCP `project_status` share `advertised_capability()`; NEED_CHECKER |
| OW-AC-10 | Rotating held-out panel, ≥5 language/runtime strata, with orientation success scored | ready | — | [Project Atlas](docs/architecture/project-atlas/SYSTEM.md) |

## Defect follow-ups

| ID | Outcome | Status | Contract |
|---|---|---|---|
| OW-D-01 | Runtime coverage on a real Express test run | ready | [Name Resolution](docs/architecture/static-analysis/name-resolution/SYSTEM.md) — Istanbul/V8 Express fixtures emit `observed_calls` with `runtime_trace` provenance; NEED_CHECKER |
| OW-D-02 | Held-out receiver precision/recall oracles beyond the synthetic 7-language fixture | ready | [Name Resolution](docs/architecture/static-analysis/name-resolution/SYSTEM.md) — TS/C#/Python/Go multi-file panel; NEED_CHECKER |
| OW-D-03 | Stale external client skill installs | deferred | [Agent Interfaces](docs/architecture/agent-interfaces/SYSTEM.md) |
| OW-SH-01 | Shell-native `callers`/`callees` and rg-like exit codes | ready | [CLI Transport](docs/architecture/agent-interfaces/cli-transport/SYSTEM.md) — NEED_CHECKER |
| OW-D-04 | JSON clamp keeps routing keys | ready | [Application Services](docs/architecture/application-services/SYSTEM.md) — compact envelope keeps `control`/`anchors`/`retrieval`; NEED_CHECKER |

## Execution queue

Q-series rows that are still open. Completed Q09 A–F stay in `docs/open-work.md` history.

| ID | Outcome | Status | Blocked by | Contract |
|---|---|---|---|---|
| OW-Q02 | Typed facts through multi-language receivers, then held-out verify | ready | — | [Name Resolution](docs/architecture/static-analysis/name-resolution/SYSTEM.md) — Go/Rust/C++ field changes promote consumers; NEED_CHECKER |
| OW-Q03 | Routing, facets, and abstention | ready | — | [Query Planning](docs/architecture/query-planning/SYSTEM.md) — blockers OW-Q02/OW-AC-03 have landed increments; abstention is OW-AC-04 |
| OW-Q04 | Ranking inventory and tournament | blocked | OW-Q03 | [Structural Retrieval](docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md) |
| OW-Q05 | Packet formats and constrained selection | ready | — | [Context-Packet Encoding](docs/architecture/context-packets/SYSTEM.md) — SVO now carries the same `@path:line` provenance as `gg`; NEED_CHECKER |
| OW-Q06 | Cost surfaces and resource controller | blocked | OW-Q05 | [Query Planning](docs/architecture/query-planning/SYSTEM.md) |
| OW-Q07 | No-op incremental scan and build telemetry | ready | — | [Persistent Storage](docs/architecture/storage/SYSTEM.md) — empty dirty+removal set returns the previous graph and skips the store rewrite; NEED_CHECKER |
| OW-Q08 | Correctness / completeness / freshness; affected-test | ready | — | [Application Services](docs/architecture/application-services/SYSTEM.md) — OW-Q07 no-op landed |
| OW-Q10 | Adjacent optimizations with no baseline thrash | deferred | active batch | [Research Laboratory](docs/architecture/research/SYSTEM.md) |

## Accuracy and IR calibration

| ID | Outcome | Status | Contract |
|---|---|---|---|
| OW-P0-01 | Multi-model live factual scoring | research | [Acceptance and Qualification](docs/architecture/acceptance/SYSTEM.md) |
| OW-P0-02 | Cross-document section ranking plus embedding fallback | ready | [Semantic Retrieval](docs/architecture/information-retrieval/semantic-retrieval/SYSTEM.md) |
| OW-P0-03 | Adversarial ambiguity suite expansion | ready | [Information Retrieval](docs/architecture/information-retrieval/SYSTEM.md) — added owner-qualified `save`, file-local `send` shadow, and scoped document-absent cases; NEED_CHECKER |
| OW-P0-04 | Report completeness separately from minimum-evidence | ready | [Information Retrieval](docs/architecture/information-retrieval/SYSTEM.md) — `answerability.minimum_evidence` vs `neighborhood_complete`; NEED_CHECKER |
| OW-P1 | Ranking fit, token surfaces, RRF, PPR Pareto, Rust THIR tier | research | [Research Laboratory](docs/architecture/research/SYSTEM.md) |

## Measured claim boundaries (2026-08-16)

These numbers were produced by `tests/test_proof_lanes.py` and
`graphgraph eval --tasks eval/graphgraph-self.json`. They are Sampled/Measured,
not a superiority study.

| Claim | Result | Does not license |
|---|---|---|
| Exact reverse-lookup on this repo | 4/4 tasks `node_recall=1.0` | Other repositories |
| Eval harness can fail | RED task `node_recall=0.0` | Other repositories |
| Dirty-miss abstention (this repo) | RED compiled packet **21 tokens**, conf 0.15; two local conceptual misses unanswerable at 0 subgraph tokens | Held-out conceptual-v1 red controls (corpora absent) |
| Better than lexical search for callers | `select_symbols` production callers are `cmd_select`, `handle_select_symbols`, `execute_query`; the defining file is a mention, not a caller | Better than rg for string search |
| Conceptual / lexically disjoint (local) | mean recall **1.0** (3/3) on 3 local probes | OW-AC-03 held-out panel (corpora absent) |
| In-repo conceptual fixture | mean recall **0.80** (4/5); FIX-C03 a measured miss; red control abstains. Reproduced 3× deterministically by an independent checker 2026-08-18 | Paraphrase retrieval — the fixture's docstrings restate their queries (R-005) |
| OW-AC-03 ≥0.80 full recall | **met on this-repo probes, exactly at the gate**; held-out suite not run | Any “better than other graph tools” outcome claim; the margin is one task wide |

## Research frontiers

Unresolved technology or measurement questions. A DEFER leaf or an unclosed
promotion gate lives here until it resolves.

| ID | Uncertainty | Status | Contract |
|---|---|---|---|
| RF-01 | Whether hybrid representation buys answer quality at its 2.6–3.7× token cost | research | [Project Representation](docs/architecture/representation/SYSTEM.md) |
| RF-02 | Whether exact NumPy semantic scoring misses its SLO on large repositories | research | [Semantic Store](docs/architecture/information-retrieval/semantic-retrieval/semantic-store/SYSTEM.md) — **query** scoring is not the binding constraint; **index build** is. Measured 2026-08-19: this repo's own 14,547-node index build timed out past 10 min, which is why the dogfood index is stale, and a stale index silently costs the whole conceptual gate (0.800 → 0.000). Length-sorted batching (ADR-EB-003) took embedding 51 → 140 nodes/s (2.7x) with bit-identical vectors, so a full rebuild is now minutes rather than tens of minutes. Still open: whether that is enough at 100k+ nodes, and whether incremental per-node index updates should replace whole-graph rebuilds |
| RF-03 | Whether a compiler-grade Rust THIR tier is justified over tree-sitter | research | [Language Frontends](docs/architecture/static-analysis/language-frontends/SYSTEM.md) |
| RF-04 | Whether stating retrieval as Connected Budgeted Maximum Coverage / Group Steiner Tree and adopting an approximation algorithm beats three unguaranteed greedy stages | research | [Structural Retrieval](docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md) ADR-SRT-007 — facets are groups, nodes are covering sets, tokens are costs, the dependence cone is the connectivity constraint. Both documented inter-stage defects were symptoms of having no single objective. Ranking-affecting, so gated on the eval harness |
| RF-05 | Whether the calibration gate should move off binned ECE to a consistent measure | research | [Calibration and Derived Signals](docs/architecture/evaluation-analysis/calibration-scoring/SYSTEM.md) ADR-CS-004 — binned ECE is biased and bin-count-dependent, read here at ~2.6 samples/bin. smECE (arXiv:2309.12236, ICLR 2024) or jackknife-debiased ECE (Roelofs et al., AISTATS 2022). Adopting it re-denominates every recorded ECE reading |
| RF-06 | Whether Forward-Push + Monte Carlo PPR with a stated error bound beats the current localized approximation | research | [Anchor Discovery](docs/architecture/information-retrieval/structural-retrieval/anchor-discovery/SYSTEM.md) — FORA (VLDB 2017) / TopPPR (SIGMOD 2018) give sublinear cost with controllable error; the shipped approximation states no error guarantee. Incremental PPR index maintenance (SIGMOD 2023) also fits the incremental-splice model |
| RF-07 | Whether conformal prediction should replace fitted MAE/p95 as the token estimator's guarantee | research | [Token Estimation](docs/architecture/context-packets/token-estimation/SYSTEM.md) — split conformal wraps the existing estimator and yields distribution-free finite-sample coverage instead of a panel-fitted average, without changing the estimator |
