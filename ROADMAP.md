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

## Agent-cycle product gaps

Indexed from `docs/open-work.md` section A.

| ID | Outcome | Status | Blocked by | Contract |
|---|---|---|---|---|
| OW-AC-01 | Resident exact-query p95 gated; tools visible in an agent session | ready | — | [MCP Transport](docs/architecture/agent-interfaces/mcp-transport/SYSTEM.md) — warm MCP `query_relations` p95 92.6 ms vs 250 ms SLO; initialize+tools/list exposes 24 tools; NEED_CHECKER |
| OW-AC-02 | Discovery selects a validated build; empty delta means fresh | ready | — | [Application Services](docs/architecture/application-services/SYSTEM.md) — `active_build` is validated/stale/invalid/absent; empty-delta incremental scan is a no-op; NEED_CHECKER |
| OW-AC-03 | ≥80% full recall on conceptual / lexically disjoint tasks with no exact-task regression | ready | — | [Structural Retrieval](docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md) — local conceptual mean recall 1.0 (3/3); held-out corpora not on disk; NEED_CHECKER |
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
| OW-AC-03 ≥0.80 full recall | **met on this-repo probes**; held-out suite not run | Any “better than other graph tools” outcome claim |

## Research frontiers

Unresolved technology or measurement questions. A DEFER leaf or an unclosed
promotion gate lives here until it resolves.

| ID | Uncertainty | Status | Contract |
|---|---|---|---|
| RF-01 | Whether hybrid representation buys answer quality at its 2.6–3.7× token cost | research | [Project Representation](docs/architecture/representation/SYSTEM.md) |
| RF-02 | Whether exact NumPy semantic scoring misses its SLO on large repositories | research | [Semantic Store](docs/architecture/information-retrieval/semantic-retrieval/semantic-store/SYSTEM.md) |
| RF-03 | Whether a compiler-grade Rust THIR tier is justified over tree-sitter | research | [Language Frontends](docs/architecture/static-analysis/language-frontends/SYSTEM.md) |
