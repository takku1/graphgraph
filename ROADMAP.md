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

## Corpus coverage and index freshness (2026-08-19)

Dogfooding this repository found two silent-truncation defects. Both are fixed;
both are recorded here because "the packet looked complete" was true in each case.

| Defect | Before | After |
|---|---|---|
| `target*` prefix pruning dropped source directories | `docs/architecture/context-packets/target-catalog/` absent from the graph | exact match only; `--include target` now reachable |
| 12-paragraph section cap | **40.6%** of repo documents truncated, incl. every terminal contract's §8 tail | **0.6%** (1 of 175) at a cap of 48 |
| Graph size / paragraphs | 14,547 nodes / 7,480 paragraphs | **17,144 nodes / 8,002 paragraphs** |
| Semantic index build | timed out past 10 min, index stale | **188 s (91 nodes/s)**, state `current` |

## External benchmark: HotpotQA (2026-08-19)

First measurement on a public corpus this project did not build, choose, or
oracle. 300 questions from the `distractor` validation split (all `hard`),
scoring supporting-paragraph retrieval at k=2 against an Okapi BM25 arm over
the same 10 paragraphs. Harness: `benchmarks/external/hotpotqa.py`.

| Metric | GraphGraph | BM25 |
|---|---|---|
| Supporting EM | **0.5533** | 0.2533 |
| Supporting F1 | **0.7633** | 0.5767 |
| p50 / p95 latency | 865 / 1292 ms | — |

Paired outcomes: 48 both correct, **118 GraphGraph-only**, 28 BM25-only, 106
both wrong. McNemar exact two-sided **p = 2.4e-14**, so the difference is not
sampling noise on this sample.

Where it wins and where it does not:

| Question type | n | GraphGraph EM | BM25 EM |
|---|---:|---:|---:|
| comparison (both entities named) | 68 | **0.926** | 0.250 |
| bridge (second entity must be inferred) | 232 | **0.444** | 0.254 |

The failure mode is one defect, not a spread: of the 134 questions that missed
EM, **126 (94%) retrieved exactly one of the two gold paragraphs**. Only 8 of
300 retrieved neither. That is the second hop failing, and it is the measured
form of ADR-SRT-008 — expansion cannot influence ranking, so a document
reachable only by traversal never becomes a top anchor.

Does not license: an answer-quality claim (this scores retrieval, not
generation), a latency claim (the BM25 arm is in-process and untimed), or any
statement about the `fullwiki` setting.

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
| RF-04 | Whether stating retrieval as Connected Budgeted Maximum Coverage / Group Steiner Tree and adopting an approximation algorithm beats three unguaranteed greedy stages | **ready** | [Structural Retrieval](docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md) ADR-SRT-007 — facets are groups, nodes are covering sets, tokens are costs, the dependence cone is the connectivity constraint. Both documented inter-stage defects were symptoms of having no single objective. Ranking-affecting, so gated on the eval harness. **Now measured externally (2026-08-19):** HotpotQA bridge questions score 0.444 EM against 0.926 on comparison questions, and 94% of all misses retrieve exactly one of two gold paragraphs — the second hop, quantified. ADR-SRT-008 names the mechanism: `starts` is final before expansion runs, so connectivity cannot influence ranking. **First fix REFUTED 2026-08-19** (`candidate/rf-04-connectivity-rank`, commit 83b0626): promoting graph-connected candidates above lexical siblings scores EM 0.42 against a 0.57 baseline on the same 100 questions. Cause: boolean document connectivity admits 7 of 10 documents on a HotpotQA corpus — concept bridges like `best seller` join nearly everything, so promotion elevates distractors over a signal that discriminates. **Second fix also REFUTED** (`candidate/rf-04-selective-bridge`, commit 90b53f5): weighting bridges by selectivity (`John Boyne`→2 docs vs `Patrick Rothfuss`→6) recovers most of the loss but never the baseline — EM 0.54/0.56/0.56 at share 0.34/0.25/0.20, rising toward 0.57 exactly as promotion fires less often. A parameter whose optimum is *never act* is not a parameter. **What both refutations share:** they use connectivity as a *precedence* rule that preempts the ranker, and even a selective bridge is weaker evidence than the combined lexical+semantic score. A working version must **combine** connectivity with the existing score under one objective — which is exactly the CBC framing this row opened with — not add another overriding stage. **Two further formulations also refuted** (`candidate/rf-04-score-blend`, commit 72fdb28): connectivity blended into the ranked score EM 0.41; one slot reserved for the most specifically bridged document EM 0.49. **Four attempts, one cause.** Instrumenting the blend shows the ranked pool arrives with its top six candidates *tied at 59.7* while the correct second-hop document scores ~15 — no bounded corroborating signal closes a four-fold gap, and an unbounded one destroys the queries that already work. **Ruled out:** every variant of correcting the second hop by reordering, reweighting, or reserving within a single ranked pool. **Points to:** the second hop is not a ranking problem but a second *query* — issue a new retrieval seeded from what hop one said, then merge (iterative retrieval), which is where the CBC framing lands from theory. That is an architectural change to the compile path and needs its own contract and gate |
| RF-05 | Whether the calibration gate should move off binned ECE to a consistent measure | research | [Calibration and Derived Signals](docs/architecture/evaluation-analysis/calibration-scoring/SYSTEM.md) ADR-CS-004 — binned ECE is biased and bin-count-dependent, read here at ~2.6 samples/bin. smECE (arXiv:2309.12236, ICLR 2024) or jackknife-debiased ECE (Roelofs et al., AISTATS 2022). Adopting it re-denominates every recorded ECE reading |
| RF-06 | Whether Forward-Push + Monte Carlo PPR with a stated error bound beats the current localized approximation | research | [Anchor Discovery](docs/architecture/information-retrieval/structural-retrieval/anchor-discovery/SYSTEM.md) — FORA (VLDB 2017) / TopPPR (SIGMOD 2018) give sublinear cost with controllable error; the shipped approximation states no error guarantee. Incremental PPR index maintenance (SIGMOD 2023) also fits the incremental-splice model |
| RF-07 | Whether conformal prediction should replace fitted MAE/p95 as the token estimator's guarantee | research | [Token Estimation](docs/architecture/context-packets/token-estimation/SYSTEM.md) — split conformal wraps the existing estimator and yields distribution-free finite-sample coverage instead of a panel-fitted average, without changing the estimator |
