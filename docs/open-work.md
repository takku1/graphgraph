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
| OW-AC-03 | Conceptual / lexically disjoint retrieval | active | ≥80% full recall on conceptual tasks; no exact-task regression |
| OW-AC-04 | Abstention & confidence calibration | active | Red controls: unanswerable, conf ≤0.2, ≤50 real tokens |
| OW-AC-05 | Cross-language call-graph topology | active | Per-language volume + independent precision ≥98% |
| OW-AC-06 | Machine-response token surface | ready | Response ≤1.15× evidence-packet tokens |
| OW-AC-07 | Token estimator calibration | done | MAE ≤5%, p95 ≤10% |
| OW-AC-08 | Latency & scale invariance | ready | Transport-specific absolute + invariance gates |
| OW-AC-09 | Contract & telemetry consistency | ready | Machine-readable capability identity |
| OW-AC-10 | Rotating held-out repository panel | active | ≥5 language/runtime strata |

Receipts: [archive findings agent-cycle tracker](evaluation/graybox-cycles/2026-08-02-agent-cycle-efficiency-quality-tracker.md).

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
| OW-DOC-01 | Academic tree under architecture/evaluation/research/guides | active |
| OW-DOC-02 | Live findings/notes removed; archive only | done |
| OW-DOC-03 | Root stubs cleared | done |
| OW-DOC-04 | Fix external links (README/skills/tests) outside docs/ | blocked (out of docs scope) |

---

## How to update

1. Change status here when work completes; one-line receipt (date + command).  
2. Long write-ups go to `evaluation/` or `research/`, never a second checklist.  
3. Prefer expanding `architecture/**/SYSTEM.md` when a concept becomes a stable subsystem.
