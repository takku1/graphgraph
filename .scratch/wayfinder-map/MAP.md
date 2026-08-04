# Wayfinder Map — GraphGraph

**Label:** `wayfinder:map`
**Status:** Active Execution Frontier

> Process incomplete work (not tickets): [docs/open-work.md](../../docs/open-work.md)
> Architecture the tickets target: [docs/architecture/SYSTEM.md](../../docs/architecture/SYSTEM.md)
> Evidence bar: [docs/guides/evidence-standards.md](../../docs/guides/evidence-standards.md)

## Destination

**Be the smallest, fastest context graph — and beat every comparable system on
every metric that matters: answer quality at full content coverage, retrieval
latency, and above all token cost.**

The design bet: the packet is **not** a human-readable artifact. It is a
compiled form targeting the model, and the target ISA is however the LLM
actually interprets tokens. Legibility to a person is not a constraint; it is a
cost we decline to pay. Every format decision is therefore an empirical
question about the consumer, not an aesthetic one — which is why format ranking
is denominated in measured tokens against a real tokenizer, and why a
calibration error of 47% cross-format spread was a project-level defect rather
than a rounding issue.

Two consequences for how work is gated here:

1. **A claim to be "better" is comparative or it is nothing.** Absolute numbers
   in isolation do not establish the destination. Head-to-head measurement
   against named alternatives is a first-class deliverable (T-B04), not a
   marketing step at the end.
2. **Token cost is the primary axis**, with latency and recall as constraints
   that must not regress. A representation that is cheaper but loses content,
   or cheaper but slower to produce, has not won.

## How execution works here

- **Type A** = implement against a spec node. **Type B** = research/measure a question first.
- Correctness backpressure: `components/<name>/checks.sh`
- Primary metric: `components/<name>/measure.sh` (JSON on stdout, `direction` declared)
- Gate: `python harness/hypothesis_runner.py <component> <branch> [--tolerance PCT]`
  — exit 0 keep, 1 revert, 2 harness error. Readings append to `.measure/<component>/log.jsonl`.
- A component with no `measure.sh` has no metric gate yet; that is a ticket below, not an oversight.

## Recorded baselines (2026-08-04, this machine)

| Component | Metric | Baseline | Note |
|-----------|--------|---------:|------|
| storage | `graph_load_warm_ms` | 0.1403 ms | cold load 213 ms reported alongside |
| information-retrieval | `retrieval_query_warm_ms` | 2017.7 ms | **see T-B01 — this is slow** |
| context-packets | `packet_token_units` | 1070.4 | two-query fixed workload |

Baselines are machine-local. Re-record on a new host before trusting a delta.

## Decisions so far

- **ADR-001 (revised 2026-08-04):** L1 subsystems each carry a `SYSTEM.md` with EARS invariants and an EvidenceStage — [docs/architecture/SYSTEM.md](../../docs/architecture/SYSTEM.md). The original decomposition named **ten**; the reconcile audit found **fourteen** packages in `src/`, so four subsystems were decomposed in the code and never in the tree (T-A06..T-A09). Ten was not a design choice, it was an omission.
- **ADR-002:** Resident MCP is the interactive transport; CLI is cold-start/scripting. Latency is reported per transport, never averaged.
- **ADR-003:** Native `.gg` store is embedded — no database server on the hot path.
- **ADR-004:** Optional platform passes stay off by default until they pass the promotion gate.

---

## Completion Rubric — what "10/10" means here

Scored per component, three axes. A component is **done** at 10/10 on axis 1+2
with axis 3 at or above its declared evidence bar. Audited 2026-08-04 by running
the reconcile-spec signals against source, not against the specs.

**Axis 1 — Spec completeness (7 pts):** §1 intent · §2 decomposition ·
§3 interface contracts · §4 EARS invariants each carrying an EvidenceStage ·
§5 ADRs · §6 test seam naming real files · §7+§8 measurement seam and technology
resolution.

**Axis 2 — Execution readiness (3 pts):** `checks.sh` green and covering the
component's real test surface · `measure.sh` emitting a genuine metric ·
a recorded baseline in `.measure/`.

**Axis 3 — Evidence maturity (%):** share of invariants at `Measured` or
`Observed` rather than `Sampled` or `Unknown`. This is deliberately *not* summed
into the score: a spec can be complete and still rest on weak evidence, and
hiding that in a total is how a project talks itself into believing it is done.

### Scorecard

| Component | Axis 1 | Axis 2 | Evidence | Missing |
|-----------|:------:|:------:|:--------:|---------|
| storage | 7/7 | 3/3 | 80% | — **10/10** |
| information-retrieval | 7/7 | 3/3 | 75% | — **10/10** |
| context-packets | 7/7 | 3/3 | 60% | — **10/10** |
| static-analysis | 7/7 | 1/3 | 80% | measure.sh + baseline |
| intermediate-representation | 7/7 | 1/3 | 75% | measure.sh + baseline |
| query-planning | 7/7 | 1/3 | 60% | measure.sh + baseline |
| application-services | 7/7 | 1/3 | 75% | measure.sh + baseline |
| platform | 7/7 | 1/3 | 66% | measure.sh + baseline |
| agent-interfaces | 7/7 | 1/3 | 60% | measure.sh + baseline |
| project-atlas | 7/7 | 1/3 | **33%** | measure.sh + baseline; weakest evidence |
| **acceptance** | **0/7** | **0/3** | — | **entire component** |
| **evaluation-analysis** | **0/7** | **0/3** | — | **entire component** |
| **research** | **0/7** | **0/3** | — | **entire component** |
| **representation** | **0/7** | **0/3** | — | **entire component** |

### What the audit found

**Signal A — un-specced code.** Four packages totalling ~7,050 LOC (13% of
`src/`) have no spec node. The architecture tree claims ten subsystems; the
source has fourteen.

| Package | LOC | What it is |
|---------|----:|------------|
| `acceptance/` | 3,735 | Black-box acceptance + live-validation harness, 21 modules |
| `analysis/` (less `navigation.py`) | ~1,600 | Calibration, document authority, eval protocol, metrics |
| `research/` | 957 | Attention field, claim registry, static cover |
| `representation/` | 508 | `hybrid.py` / `hybrid_reserve_v1` |

`acceptance/` is the sharpest gap. It is the qualification layer — the subsystem
that would substantiate the destination claim — and it is the least specified
thing in the repository. ADR-006 says superiority is head-to-head or withdrawn;
the harness that would run that comparison has no contract of its own.

**Signal B — spec bloat.** None. Largest spec is 94 lines against a ~150 threshold.

**Signal C — test seams.** 39 of 57 suites are now wired to a component gate,
up from 29. The remaining 18 map almost exactly onto the four missing
components, which is corroboration that the Signal A boundary is real and not
an artifact of how the packages happen to be named.

**Signal D — metric drift.** Three baselines recorded, no regressions yet.
`retrieval_query_warm_ms = 2017 ms` is the outstanding concern (T-B01).

**Stale reference fixed.** `acceptance/__init__.py` cited
`docs/bugs/2026-07-19-graphgraph-10-11-acceptance-spec.md`, deleted in `5860911`
long before this work. Repointed to the surviving
`docs/evaluation/acceptance-evaluation-harness.md`.

---

## Open Frontier Tickets (Claimable)

### Type B — research/measure first

- [ ] **[T-B01]** Warm `direct_lookup` costs **2.0 s** on the graphgraph graph
  - **Signal:** first harness baseline, stdev 41 ms across 9 runs — stable, so not noise.
  - **Why it matters:** [agent-interfaces/SYSTEM.md](../../docs/architecture/agent-interfaces/SYSTEM.md) advertises sub-ms resident retrieval against a Flask-scale graph. Either that figure does not generalize to a 7.5 MB graph, or this query misses the exact fast path and falls into ranked search. Find out which before optimizing.
  - **Target:** [information-retrieval/SYSTEM.md](../../docs/architecture/information-retrieval/SYSTEM.md)
  - **Blocked By:** none

- [ ] **[T-B02]** Build a paraphrase/conceptual labelled task set
  - **Why:** ADR-IR-001 — the current tasks are lexically easy, so no field-stage candidate can be evaluated at all. This blocks OW-AC-03 and any ranking work.
  - **Target:** [information-retrieval/SYSTEM.md](../../docs/architecture/information-retrieval/SYSTEM.md)
  - **Blocked By:** none

- [ ] **[T-B04]** Head-to-head benchmark against named alternatives — **the destination metric**
  - **Why:** "better than every other context graph" is currently asserted in
    prose and in a comparative matrix built from *their* published numbers, on
    *their* benchmarks. That is not a head-to-head. Until the same task set runs
    through both systems on one machine, the central claim is unmeasured.
  - **Axes, in priority order:** token cost at fixed answer quality → retrieval
    latency (cold and warm, reported separately) → content coverage/recall →
    update cost.
  - **Candidate comparands:** the systems already surveyed in
    [docs/research/comparisons/](../../docs/research/comparisons/) and the
    agent-memory frameworks cited in the manuscript. Pick ones that can be run
    locally; a system requiring a hosted service is a different product and
    should be stated as such rather than benchmarked unfairly.
  - **Rule:** report the axis where GraphGraph loses. A comparison that only
    shows wins is not evidence, and the evidence bar in this project already
    says so.
  - **Target:** [context-packets/SYSTEM.md](../../docs/architecture/context-packets/SYSTEM.md), [information-retrieval/SYSTEM.md](../../docs/architecture/information-retrieval/SYSTEM.md)
  - **Blocked By:** `T-B02` (needs a task set neither system was tuned on)

- [ ] **[T-B05]** Measure what the *model* actually costs, not what the proxy estimates
  - **Why:** the calibrated proxy is whitespace-blind and validated against
    `cl100k_base`/`o200k_base` only. If the packet is a compiled artifact
    targeting the model, the compiler's cost model must track the real
    consumer — including tokenizers the project has not fitted against.
  - **Scope:** score the shipped formats against current production tokenizers;
    re-run `benchmarks/context_graph/calibrate_token_proxy.py` and record drift.
  - **Target:** [context-packets/SYSTEM.md](../../docs/architecture/context-packets/SYSTEM.md)
  - **Blocked By:** none

- [ ] **[T-B03]** Define measurement seams for the seven unmetered components
  - **Scope:** static-analysis, intermediate-representation, query-planning, application-services, platform, agent-interfaces, project-atlas.
  - **Rule:** a real metric or none. Do not add a `measure.sh` that emits a placeholder — the gate treats a fabricated number as Measured evidence.
  - **Blocked By:** none

### Type A — implement

- [ ] **[T-A01]** Resident transport exact-query p95 gate — **OW-AC-01**
  - **Target:** [agent-interfaces/SYSTEM.md](../../docs/architecture/agent-interfaces/SYSTEM.md)
  - **Blocked By:** `T-B01`

- [ ] **[T-A02]** Active graph publication & freshness — **OW-AC-02**
  - **Target:** [application-services/SYSTEM.md](../../docs/architecture/application-services/SYSTEM.md)
  - **Blocked By:** none

- [ ] **[T-A03]** Abstention & confidence red controls — **OW-AC-04**
  - **Gate:** unanswerable ⇒ confidence ≤0.2 and ≤50 real tokens.
  - **Note:** the `incomplete` vs `unanswerable` distinction changed on 2026-08-04 (doc-only corpora now report `incomplete`); the red controls must be written against the new taxonomy.
  - **Target:** [information-retrieval/SYSTEM.md](../../docs/architecture/information-retrieval/SYSTEM.md)
  - **Blocked By:** none

- [ ] **[T-A04]** Cross-language call-graph topology — **OW-AC-05**
  - **Gate:** per-language volume plus independent precision ≥98%.
  - **Target:** [static-analysis/SYSTEM.md](../../docs/architecture/static-analysis/SYSTEM.md)
  - **Blocked By:** none

- [ ] **[T-A05]** Rotating held-out repository panel — **OW-AC-10**
  - **Gate:** ≥5 language/runtime strata.
  - **Blocked By:** `T-B02`

- [ ] **[T-A06]** Spec the `acceptance/` subsystem — **highest-value gap**
  - **Why first:** 3,735 LOC across 21 modules, and it is the qualification
    layer. ADR-006 makes head-to-head measurement the standard of proof; this is
    the harness that would carry it, and it currently has no interface contract,
    no invariants, and no gate of its own.
  - **Scope:** L1 `SYSTEM.md` under `docs/architecture/acceptance/`, plus
    `components/acceptance/checks.sh` wiring `test_acceptance.py`,
    `test_acceptance_exec.py`, `test_acceptance_quality.py`, `test_live_validation.py`.
  - **Candidate metric:** acceptance gate pass-rate at fixed corpus (`direction: higher`).
  - **Blocked By:** none

- [ ] **[T-A07]** Spec the `analysis/` evaluation subsystem
  - **Scope:** calibration, document authority, eval protocol, metrics (~1,600 LOC
    beyond the already-specced `navigation.py`). Suites: `test_calibration.py`,
    `test_document_authority.py`, `test_eval_harness.py`, `test_eval_protocol.py`.
  - **Note:** decide whether this is its own L1 or a child of an evaluation node;
    the two-child minimum and distinct-failure-mode guards both apply.
  - **Blocked By:** none

- [ ] **[T-A08]** Spec the `research/` subsystem
  - **Scope:** `attention_field.py`, `registry.py`, `static_cover.py`. The claim
    registry is already mechanically gated by `test_research_registry.py`, which
    is a stronger invariant than most of the tree carries — record it as `Proved`.
  - **Blocked By:** none

- [ ] **[T-A09]** Spec the `representation/` subsystem
  - **Scope:** `hybrid.py` / `hybrid_reserve_v1`. This is the live opt-in
    candidate from the global-attention line; the default stays flat. Its
    promotion status belongs in a spec, not in a benchmark script's comments.
  - **Blocked By:** none

### Housekeeping

- [ ] **[T-H01]** Three documented modules are uncommitted
  - `analysis/navigation.py`, `services/project_atlas.py`, `storage/sectioned.py` are described by [project-atlas/SYSTEM.md](../../docs/architecture/project-atlas/SYSTEM.md) and [storage/SYSTEM.md](../../docs/architecture/storage/SYSTEM.md) but exist only in a working tree, along with `retrieval/relations.py` changes and three test files.
  - **Consequence:** `components/project-atlas/checks.sh` and `components/storage/checks.sh` skip suites that do not exist on a fresh checkout, so their green is weaker than it looks.
  - **Owner:** the in-flight lane, not this one. Commit or discard before treating those specs as describing shipped code.
  - **Blocked By:** none
