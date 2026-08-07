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
| OW-AC-08 | Latency & scale invariance | ready | Transport-specific absolute + invariance gates |
| OW-AC-09 | Contract & telemetry consistency | ready | Machine-readable capability identity |
| OW-AC-10 | Rotating held-out repository panel | active | ≥5 language/runtime strata |

Receipts: [archive findings agent-cycle tracker](evaluation/graybox-cycles/2026-08-02-agent-cycle-efficiency-quality-tracker.md).

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
| OW-Q09-A | Orchestration decomposition | ready | Q08-B |
| OW-Q10 | Adjacent optimizations (no baseline thrash) | deferred | active batch |

Q-series batch detail was carried in the pre-redesign `planned-work.md`; the
incomplete rows are reproduced above and the superseded plan remains in git history.

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
