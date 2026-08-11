# Open Work

**Single incomplete-work registry.** Do not reintroduce parallel checklists in research essays or archived findings.

**Statuses:** `ready` · `active` · `blocked` · `deferred` · `research` · `done`  
**History:** gray-box evidence → [evaluation/graybox-cycles/](evaluation/graybox-cycles/README.md); superseded pre-redesign plans live in git history  
**Evidence bar:** [guides/evidence-standards.md](guides/evidence-standards.md)

---

## A. Agent-cycle workstreams

| ID | Workstream | Status | Exit gate (summary) |
|----|------------|--------|---------------------|
| OW-AC-01 | Resident process transport (MCP vs cold CLI) | active | Resident exact-query p95; tools exposed in agent session |
| OW-AC-02 | Active graph publication & freshness | active | Discovery selects validated build; empty delta ⇒ fresh |
| OW-AC-03 | Conceptual / lexically disjoint retrieval | active | ≥80% full recall on conceptual tasks. 0.00 (2026-08-04) → 0.357 (doc capture) → 0.500 (T-B07 preflight fix) → **0.643 (2026-08-06, T-B08 facet-reservation seating)**; cross-repo held-out recall 0.841 → 0.886. Remaining gap is downstream ranking, not the veto |
| OW-AC-04 | Abstention & confidence calibration | active | Red controls: unanswerable, conf ≤0.2, ≤50 real tokens. **5 of 7 conceptual misses emitted 546–1,609 tokens instead of abstaining** |
| OW-AC-05 | Cross-language call-graph topology | active | Per-language volume + independent precision ≥98% |
| OW-AC-06 | Machine-response token surface | ready | Response ≤1.15× evidence-packet tokens |
| OW-AC-07 | Token estimator calibration | done | MAE ≤5%, p95 ≤10% |
| OW-AC-08 | Latency & scale invariance | active | Packed exact relation 57.08 → 3.81 ms p50 in-process (2026-08-08); add graph-size strata and remaining phase gates |
| OW-AC-09 | Contract & telemetry consistency | ready | Machine-readable capability identity |
| OW-AC-10 | Rotating held-out repository panel | active | ≥5 language/runtime strata |

Receipts: [consolidated agent-cycle measurement](evaluation/graybox-cycles/README.md#instrument-and-representation-measurements).

**Sequencing (2026-08-04).** Claimable tickets and their dependency order live on
the execution frontier: [`.scratch/wayfinder-map/MAP.md`](../.scratch/wayfinder-map/MAP.md).
The critical path is `T-H01 → T-B02 → {T-B04, T-A05, T-A03} → remaining
measurement seams`. **OW-AC-03's task set (T-B02) is the keystone** — four
tickets, the representation promotion gate, and one component's metric are all
waiting on it, which makes it the highest-leverage item on the board despite not
being the most visible.

Component-level completion status (spec, gate, metric per subsystem) is tracked
in the same map rather than duplicated here.

---

## B. Defect follow-ups

| ID | Item | Status |
|----|------|--------|
| OW-D-01 | Runtime coverage on real Express test run | ready |
| OW-D-02 | Held-out receiver precision/recall oracles | active |
| OW-D-03 | Stale external client skill installs | deferred |

Resolved OS/Git defects: [evaluation/defect-ledger.md](evaluation/defect-ledger.md).

---

## C. Execution queue (Q-series)

| ID | Batch | Status | Depends |
|----|-------|--------|---------|
| OW-Q02-A…D | Typed facts → multi-language receivers | active / verify | lattice → held-out |
| OW-Q03-A…C | Routing, facets, abstention | ready | Q02-D |
| OW-Q04-A…B | Ranking inventory & tournament | ready / research | Q03-C |
| OW-Q05-A…B | Packet formats & constrained selection | ready | Q04-B |
| OW-Q06-A…B | Cost surfaces & resource controller | ready | Q05-B |
| OW-Q07-A…B | No-op incremental & build telemetry | ready | Q06-B |
| OW-Q08-A…B | Correctness/completeness/freshness; affected-test | ready | Q07-B |
| OW-Q09-A…F | Context compiler convergence | active | Ordered migration below; deep-Module/pass design recorded in [extensible-context-compiler.md](research/extensible-context-compiler.md) |
| OW-Q10 | Adjacent optimizations (no baseline thrash) | deferred | active batch |

Q-series batch detail was carried in the pre-redesign `planned-work.md`; the
incomplete rows are reproduced above and the superseded plan remains in git history.

### OW-Q09 context compiler convergence

These stages execute in order. A later stage may be researched while an earlier
stage is active, but it cannot change production authority until its dependency
gate passes. This is the only checklist for the migration.

| ID | Stage | Status | Depends | Exit gate |
|----|-------|--------|---------|-----------|
| OW-Q09-A | Compiler driver authority | done | — | CLI, MCP, HTTP, and Python callers cross one `CompilerDriver` Interface; graph lifecycle, whole-response caching, timings, validation, and workflow receipts have one implementation; superseded orchestration is deleted rather than wrapped |
| OW-Q09-B | Canonical `SourceIR` | done | Q09-A | One versioned source artifact is reused by scanner extraction and evidence passes; CPG providers do not reparse an unchanged source revision; provenance and fallback receipts remain exact |
| OW-Q09-C | Atomic `TargetSpec` catalog | done | Q09-B | Each packet target registers identity, capabilities, encoder, validator, priority policy, and cost model atomically; parallel format registries and advertised-name copies are deleted |
| OW-Q09-D | Artifact preservation and invalidation | done | Q09-C | Pass specifications declare requirements, products, preservation, determinism, cache scope, and cost; cache keys bind graph revision plus artifact hashes; mutation tests prove precise invalidation |
| OW-Q09-E | Evaluation promotion and scratch retirement | done | Q09-D | Durable findings are represented by architecture, contracts, benchmarks, or tests; superseded `docs/evaluation` scratch artifacts are removed; authority/link tests pass |
| OW-Q09-F | Terminology and filename audit | active | Q09-E | Remaining generic names are retained only when they name a coherent mathematical/domain abstraction; ambiguous names and aliases are removed; cold-start, token, accuracy, and full-suite gates do not regress |

Every stage uses the same acceptance sequence: focused interface tests, public
contract parity, Ruff, full pytest, cold-start/token measurements when its hot
path changes, and an exact-path GraphGraph refresh used only as a secondary
orientation index.

**OW-Q09-A progress (2026-08-08):** introduced
`CompilerDriver.compile(DriverRequest)` as the native project-compilation
Interface; migrated CLI, MCP, acceptance, and direct native tests; deleted
`services/native_context.py` and the `render_native_context` function without
an alias. Receipt: Ruff clean; `1176 passed, 201 subtests passed`. Remaining A
gate: move whole-response cache/control implementation out of `context.py`,
then delete its superseded internal orchestration code.

**OW-Q09-A progress (2026-08-09):** removed the public
`render_query_context` Interface and lazy export; migrated Python query,
benchmarks, live validation, and all interface tests to `CompilerDriver`;
added `resident_status` so fused refresh/query execution preserves its
zero-reload graph path. The renamed calibration corpus remains source-grounded
and passes at ECE `0.096708` without changing the confidence formula or
`ECE < 0.10` gate. Receipt: Ruff clean; `1176 passed, 201 subtests passed`.

**OW-Q09-A completion (2026-08-09):** moved query compilation,
whole-response caching, control IR, and actionable evidence assembly into
`services/compiler_driver.py`; `services/context.py` now owns only stable,
full, and known-anchor final packets. Extracted deterministic shared cache
identity into `services/cache_identity.py` with explicit
`worktree_signature`, `packet_dependency_paths`, `file_signature`, and
`is_generated_artifact` operations. Superseded query orchestration and stale
test interception points were deleted. Receipt: Ruff clean, `git diff
--check` clean, focused service/transport tests pass, and full pytest passes.

**OW-Q09-B completion (2026-08-09):** replaced `SourceFile` with the
versioned immutable `SourceIR` contract and a bounded content-addressed
`SyntaxIR` cache. Tree-sitter extraction and CPG evidence now consume the same
syntax artifact for an unchanged source revision, including Python; the
Python-only CPG reparse branch and the old name were deleted. Capability
receipts report `artifacts_compiled` and `artifacts_reused`, and focused tests
prove CPG does not invoke its parser after scanner extraction while preserving
concrete grammar-failure warnings. Receipt: Ruff clean, `git diff --check`
clean, 230 widened scanner/platform tests pass, and full pytest passes.

**OW-Q09-C completion (2026-08-09):** replaced the parallel format,
renderer, validator, cost, and transport-name registries with the immutable
cold-start-safe `packet_targets.py` catalog. Each `TargetSpec` now owns lazy
encoder and validator references, capabilities, calibrated or explicitly proxy
cost, priority behavior, detection grammar, endpoint identity, and adaptive
selection alternatives. Compiler `gg` to `svo` minimization is catalog-driven;
the SVO label projection is rejected when it is non-injective. The former
`packets/formats.py`, renderer dispatch dictionaries, validator sniff branches,
and `surface.py` packet-name copy were deleted. Receipt: Ruff clean and 218
widened packet/compiler/CLI/MCP/platform tests pass; full pytest and `git diff
--check` pass. The fresh-process benchmark measures `import graphgraph` at
51.6 ms median and `graphgraph --help` at 92.2 ms median (a small improvement
from the 93.17 ms pre-change reference). Exact Git-path graph refresh updated
17 paths, removed the superseded format module, and returned a valid, fresh
secondary index; its broad ticket query remained incomplete, so source and
tests—not that retrieval packet—remain the acceptance authority.

**OW-Q09-D completion (2026-08-09):** expanded `CompilerPassSpec` into one
atomic pass contract covering version, required/product/preserved artifacts,
capabilities, determinism, cache scope, request parameters, and static cost.
Added bounded compiler-local artifact indexing and analysis reuse keyed by
component revision plus BLAKE2 content digest. Cache hits materialize private
graph snapshots and rebase current preserved components, preventing public
result mutation from poisoning reuse. Catalog construction rejects unknown
requirements, invalid scopes, nondeterministic caching, and undeclared graph
outputs. CLI platform capabilities expose the serializable pass catalog.
Mutation tests prove an edge change reuses and rebases a node-only analysis,
while a required-node change invalidates it. Receipt: 151 widened
platform/compiler/transport tests pass; Ruff, `git diff --check`, and full
pytest pass.

**OW-Q09-E completion (2026-08-09):** promoted the terminal findings from 24
tracked gray-box run narratives into one 6 KB measurement ledger linked to
current architecture ADRs, executable tests/benchmarks, the defect ledger, and
the research registry. Retired 6,491 lines of superseded narrative while
preserving every executable JSON/source corpus and leaving the two newest
untracked raw receipts untouched. Added a rolling-window contract: at most two
raw dated receipts may coexist and each must be indexed before another is
added. All live links and seven registry evidence references now resolve to the
consolidated authority. Retired tracked files remain recoverable from Git
history. Receipt: 37 focused authority/link/registry/scanner-document tests,
Ruff, `git diff --check`, and full pytest pass.

---

## D. Accuracy & IR calibration

| ID | Item | Status |
|----|------|--------|
| OW-P0-01 | Multi-model live factual scoring | research |
| OW-P0-02 | Cross-document section ranking + embedding fallback | ready |
| OW-P0-03 | Adversarial ambiguity suite expansion | ready |
| OW-P0-04 | Completeness ≠ minimum-evidence (report separately) | ready |
| OW-P1-01…08 | Ranking fit, token surfaces, RRF, PPR Pareto, Rust THIR tier | mixed — see [research/optimization-research-agenda.md](research/optimization-research-agenda.md) |

---

## E. Documentation

| ID | Item | Status |
|----|------|--------|
| OW-DOC-01 | Academic tree under architecture/evaluation/research/guides | done |
| OW-DOC-02 | Gray-box records promoted to `evaluation/graybox-cycles/`; scratch retired | done |
| OW-DOC-03 | Root stubs cleared | done |
| OW-DOC-04 | Fix external links (README/eval fixtures/tests) outside docs/ | done |
| OW-DOC-05 | Pre-redesign archive removed; living tree is self-sufficient | done |
| OW-DOC-06 | Ground manuscript & roadmap citations against primary sources | done |

**OW-DOC-01…05 receipt (2026-08-04):** `pytest tests/test_docs_contract.py
tests/test_document_authority.py tests/test_scanner_docs.py
tests/test_public_contracts.py tests/test_research_registry.py` — 0 orphans,
all local links resolve, archive deleted.

**OW-DOC-06 receipt (2026-08-04) — citation grounding.** All ten works cited by
`research/manuscript-graphgraph-2.md` and `research/publication-roadmap.md` were
resolved against the arXiv API; both documents now carry inline `[n]` markers and
a rendered `## Sources` section with arXiv URLs.

Corrected:

| Was cited as | Actually | arXiv |
|--------------|----------|-------|
| Repoformer, "Aneja et al., 2023" | Di Wu et al., 2024 | 2403.10059 |
| RepoBench, "Zhang et al., 2023" | Tianyang Liu et al., 2023 | 2306.03091 |
| CodeXEmbed, grouped under RepoBench's credit | Ye Liu et al., 2024 — a separate paper | 2411.12644 |

Confirmed correct and left as-is: RepoCoder (Zhang et al., 2023, 2303.12570),
LLMLingua (Jiang et al., 2023, 2310.05736), GraphRAG (Edge et al., 2024,
2404.16130), ContextSniper (Luk et al., 2026, 2607.01916), KGCompass (Yang et
al., 2025, 2503.21710), Mem0 (Chhikara et al., 2025, 2504.19413), Zep/Graphiti
(Rasmussen et al., 2025, 2501.13956).

**A quantitative claim was also wrong.** Both documents asserted competitor p95
latencies of "200ms for Mem0; 632ms for Graphiti". Against the Mem0 paper's
LOCOMO latency table, `632` does not appear anywhere: Zep's search p95 is
**0.778 s**, not 632 ms. Mem0's 200 ms is its *search* p95, not its response p95
(1.440 s), so calling those figures "multi-second" was also inconsistent. Both
documents now state search p95 0.200 s (Mem0) / 0.778 s (Zep) and response p95
1.440 s / 2.926 s, cited to the Mem0 paper. Verbatim table rows are attached as
evidence in the citation ledger.

Residual: `Zep` and `Graphiti` are used interchangeably in places. Graphiti is
Zep's engine; note also that an unrelated 2025 arXiv paper is titled *Graphiti*
(a graph/relational query system, 2504.03182) — do not cite that one.

---

## How to update

1. Change status here when work completes; one-line receipt (date + command).  
2. Long write-ups go to `evaluation/` or `research/`, never a second checklist.  
3. Prefer expanding `architecture/**/SYSTEM.md` when a concept becomes a stable subsystem.
