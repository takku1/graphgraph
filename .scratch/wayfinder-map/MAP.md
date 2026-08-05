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
| storage | `graph_load_warm_ms` | 0.1403 ms | cold load 213 ms alongside |
| information-retrieval | `retrieval_query_warm_ms` | 1125.7 ms | was 2017.7; T-B01 removed 44% |
| context-packets | `packet_token_units` | 1070.4 | two-query fixed workload |
| static-analysis | `scan_fixture_ms` | 125.8 ms | bounded corpus (`concepts/`) |
| intermediate-representation | `expand_context_ms` | 1.673 ms | 2-hop, 25 starts |
| query-planning | `plan_latency_us` | 9.8 us | 600 samples |
| application-services | `context_compile_warm_ms` | 654.4 ms | end-to-end render |
| agent-interfaces | `cli_cold_start_ms` | 56.3 ms | interpreter + import only |
| research | `registry_dangling_sources` | 0 | zero-tolerance invariant |
| representation | `hybrid_vs_flat_token_ratio` | **2.6505** | **hybrid is 2.65x more expensive — see below** |

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
| static-analysis | 7/7 | 3/3 | 80% | measure.sh + baseline |
| intermediate-representation | 7/7 | 3/3 | 75% | measure.sh + baseline |
| query-planning | 7/7 | 3/3 | 60% | measure.sh + baseline |
| application-services | 7/7 | 3/3 | 75% | measure.sh + baseline |
| platform | 7/7 | 2/3 | 66% | measure.sh blocked: needs experiment design |
| agent-interfaces | 7/7 | 3/3 | 60% | measure.sh + baseline |
| project-atlas | 7/7 | 2/3 | **33%** | measure.sh blocked: needs held-out panel (T-A05) |
| acceptance | 7/7 | 2/3 | 60% | measure.sh blocked: needs external corpus |
| evaluation-analysis | 7/7 | 2/3 | 60% | measure.sh blocked: needs labelled set |
| research | 7/7 | 3/3 | **100%** | measure.sh + baseline; registry invariant is `Proved` |
| representation | 7/7 | 3/3 | 50% | measure.sh + baseline; promotion gate unmeasured |

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

**Signal C — test seams.** 51 of 57 suites are wired to a component gate, up
from 29 at the start of the audit. The 18 orphans that remained after widening
the existing gates mapped almost exactly onto the four missing components —
corroboration that the Signal A boundary was real and not an artifact of package
naming. Speccing those four took orphans to 6, all genuinely cross-cutting:
`test_docs_contract`, `test_module_boundaries`, `test_surface_constants`,
`test_distribution_artifacts`, `test_benchmark`, `test_cycle5_regressions`.
Those belong to repo-wide contracts rather than to any one subsystem.

**Signal D — metric drift.** Three baselines recorded, no regressions yet.
`retrieval_query_warm_ms = 2017 ms` is the outstanding concern (T-B01).

**Stale reference fixed.** `acceptance/__init__.py` cited
`docs/bugs/2026-07-19-graphgraph-10-11-acceptance-spec.md`, deleted in `5860911`
long before this work. Repointed to the surviving
`docs/evaluation/acceptance-evaluation-harness.md`.


### Finding: the multiresolution candidate is more expensive, not less

`hybrid_vs_flat_token_ratio` was implemented as a real two-arm render and
immediately produced the sharpest result of the audit: hybrid costs **2.65x**
(subsystem_summary), **3.65x** (direct_lookup) and **3.75x** (blast_radius) the
tokens of flat, on this project's own graph.

Hybrid emits a project-wide coarse map *plus* local detail, so more tokens is
expected by construction — the arms do not deliver the same thing. Whether the
extra 2.6–3.7x buys proportionally more answer quality is unmeasured, and that
is exactly what T-B02's task set would settle. What can be said now: the
promotion gate is a long way from passing, and any claim that the
multiresolution representation is *cheaper* is contradicted by the only
measurement that exists.

---

## Execution Order

Sequenced by dependency first, then by distance to the destination. Two rules
decide ties: **token cost outranks latency** (it is the primary axis), and
**anything that unblocks two or more tickets outranks anything that unblocks
none**.

**Critical path:** `T-H01 → T-B02 → {T-B04, T-A05, T-A03} → T-B03-rest`.
T-B02 is the keystone — four separate tickets and the representation promotion
gate are all waiting on one labelled task set that does not exist.

### Wave 0 — clear the ground (no dependencies, both cheap)

| # | Ticket | Why now |
|---|--------|---------|
| 1 | **T-H01** Commit or discard the in-flight modules | Two component gates are greener than they look; a false green at the base of a measurement programme poisons everything above it. Cheapest item on the board. |
| 2 | **T-B02** Paraphrase/conceptual task set | The keystone. Unblocks T-B04, T-A05, T-A03's red controls, the representation promotion gate, and evaluation-analysis's metric. Nothing else on this list unblocks more than one thing. |

### Wave 1 — the destination axis (token cost)

| # | Ticket | Why here |
|---|--------|----------|
| 3 | **T-B05** Score formats against current production tokenizers | Independent of T-B02, so it runs in parallel. Token cost is the primary axis and the proxy is fitted against only two tokenizers; if it has drifted, every format decision above it is mis-ranked. |
| 4 | **T-B04** Head-to-head against named alternatives | The destination metric. Needs T-B02 so neither system is measured on a task set it was tuned against. |
| 5 | **Representation promotion measurement** | Settles the 2.65–3.75x finding: is the coarse map buying proportional quality, or is the candidate simply more expensive? Needs T-B02 to score both arms at fixed recall. |

### Wave 2 — latency (the constraint that must not regress)

| # | Ticket | Why here |
|---|--------|----------|
| 6 | **T-B06** `search_nodes` runs 6x and PPR 2x per query | The remaining 1.1 s after T-B01. Structural rather than a missing cache, so it needs a design decision, not a patch. |
| 7 | **T-A01** Resident exact-query p95 gate (OW-AC-01) | Unblocked now that T-B01 has landed. Best done after T-B06 so the gate is set against the intended architecture, not a number about to move. |

### Wave 3 — answer quality gates

| # | Ticket | Why here |
|---|--------|----------|
| 8 | **T-A03** Abstention & confidence red controls (OW-AC-04) | Needs T-B02's unanswerable cases. Note the taxonomy changed on 2026-08-04: doc-only corpora now report `incomplete`, so the controls must be written against the new contract. |
| 9 | **T-A04** Cross-language call-graph topology (OW-AC-05) | Independent; ≥98% precision per language with volume reported. |
| 10 | **T-A02** Active graph publication & freshness (OW-AC-02) | Independent; correctness-of-answer rather than quality-of-answer. |

### Wave 4 — close the coverage gap

| # | Ticket | Unblocked by |
|---|--------|--------------|
| 11 | **T-A05** Rotating held-out panel (OW-AC-10) | T-B02 |
| 12 | **T-B03-rest** the four blocked measurement seams | one asset each: acceptance ← external corpus · evaluation-analysis ← T-B02 · project-atlas ← T-A05 · platform ← an experiment design |

### Not scheduled

- **SWE-bench protocol** — a different question (end-to-end patch success) from the one this project measures (representation cost). Keep as a separate protocol, not a wave.
- **Further influence-field tuning** — refuted; see ADR-RE-003. Do not reopen without a task set that could detect a field contribution at all.


### Finding: conceptual retrieval scores zero on held-out tasks

T-B02 built `eval/retrieval-v1/locus.json` — 7 conceptual/lexically-disjoint
tasks plus a red control, oracled by source inspection against a held-out Rust
corpus (766 files, pinned commit). Held-out conceptual coverage went from 2
tasks to 10.

Running it: **0.00 recall and 0.00 facet completeness on all seven.** The gate
(OW-AC-03) is ≥0.80.

A differential control isolates the cause — same graph, same system, only the
phrasing differs. Querying `EvidenceStage`, `Advisor` and `strassen_recursive`
by name hits every time; querying the same concepts in lexically-disjoint
English misses every time. All nine expected symbols are in the graph at the
paths the oracle cites, so the task set is sound and the failure is retrieval's.

Five of the seven are worse than a miss: they returned 14–48 nodes and
546–1,609 tokens containing none of the expected symbols. That is confident
wrong context, and it means the abstention path (OW-AC-04) does not fire on a
conceptual miss — it fires only when retrieval finds nothing at all.

This is the single largest gap between the project's destination and its
measured behavior. A context graph that answers only when the query already
contains the answer's name is a lexical index with extra steps.


### Finding: doc capture moved conceptual recall 0.000 -> 0.357, and found the next blocker

Embedding a symbol's own doc comment (commit c27751a) raised held-out
conceptual facet completeness from **0.000 to 0.357**, with two of seven tasks
now perfect (C05, C06) and one partial (C07). The OW-AC-03 gate is 0.80.

The four that still score zero split cleanly, and the split is the diagnosis:

- **C01, C03 return zero nodes.** They are vetoed by the *lexical* facet
  feasibility preflight in `retrieval/context.py`, which reports "no code or
  structural graph evidence covers any required query facet" and returns a
  zero-packet reject **before semantic retrieval is ever consulted**. The
  doc-enriched index ranks `EvidenceStage` first for C01 in isolation -- the
  answer is right there, and the preflight refuses to look.
- **C02, C04 return 24-48 nodes** with none of the expected symbols: retrieval
  ran and picked wrong.

C05 differs from C01 only in that its query words lexically overlap the docs, so
it survives the preflight and then succeeds. That is the controlled comparison:
same pipeline, same index, and lexical overlap decides whether the semantic
stage gets a turn at all.

- [ ] **[T-B07]** The lexical facet preflight vetoes conceptual queries
  - **Fix direction:** the preflight exists to skip ranked search for entities
    that exist nowhere. That reasoning does not hold when a semantic backend
    could still answer, so it must either consult semantic evidence before
    declaring a total miss, or decline to veto when a current semantic index is
    available. Note the same branch already had to be corrected once for
    doc-only corpora.
  - **Blocked By:** none. This is the highest-value retrieval fix on the board.

---

## Open Frontier Tickets (Claimable)

### Type B — research/measure first

- [x] **[T-B01]** Warm `direct_lookup` costs **2.0 s** on the graphgraph graph
  - **Signal:** first harness baseline, stdev 41 ms across 9 runs — stable, so not noise.
  - **Why it matters:** [agent-interfaces/SYSTEM.md](../../docs/architecture/agent-interfaces/SYSTEM.md) advertises sub-ms resident retrieval against a Flask-scale graph. Either that figure does not generalize to a 7.5 MB graph, or this query misses the exact fast path and falls into ranked search. Find out which before optimizing.
  - **Target:** [information-retrieval/SYSTEM.md](../../docs/architecture/information-retrieval/SYSTEM.md)
  - **Blocked By:** none

- [x] **[T-B02]** Build a paraphrase/conceptual labelled task set
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

- [ ] **[T-B06]** `search_nodes` runs six times and PPR twice per query
  - **Signal:** after T-B01 removed 44%, the residual 1.1 s is dominated by six
    `search_nodes` calls (2.12 s cumulative under profiler) and two
    `personalized_pagerank` calls (0.85 s) for a single query.
  - **Question:** is six searches per query intended (facet preflight, anchors,
    expansion each searching independently) or accidental duplication? The
    answer decides whether this is a caching fix or a pipeline restructure.
  - **Target:** [information-retrieval/SYSTEM.md](../../docs/architecture/information-retrieval/SYSTEM.md)
  - **Blocked By:** none

- [~] **[T-B03]** Define measurement seams for the seven unmetered components
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

- [x] **[T-A06]** Spec the `acceptance/` subsystem — **highest-value gap**
  - **Why first:** 3,735 LOC across 21 modules, and it is the qualification
    layer. ADR-006 makes head-to-head measurement the standard of proof; this is
    the harness that would carry it, and it currently has no interface contract,
    no invariants, and no gate of its own.
  - **Scope:** L1 `SYSTEM.md` under `docs/architecture/acceptance/`, plus
    `components/acceptance/checks.sh` wiring `test_acceptance.py`,
    `test_acceptance_exec.py`, `test_acceptance_quality.py`, `test_live_validation.py`.
  - **Candidate metric:** acceptance gate pass-rate at fixed corpus (`direction: higher`).
  - **Blocked By:** none

- [x] **[T-A07]** Spec the `analysis/` evaluation subsystem
  - **Scope:** calibration, document authority, eval protocol, metrics (~1,600 LOC
    beyond the already-specced `navigation.py`). Suites: `test_calibration.py`,
    `test_document_authority.py`, `test_eval_harness.py`, `test_eval_protocol.py`.
  - **Note:** decide whether this is its own L1 or a child of an evaluation node;
    the two-child minimum and distinct-failure-mode guards both apply.
  - **Blocked By:** none

- [x] **[T-A08]** Spec the `research/` subsystem
  - **Scope:** `attention_field.py`, `registry.py`, `static_cover.py`. The claim
    registry is already mechanically gated by `test_research_registry.py`, which
    is a stronger invariant than most of the tree carries — record it as `Proved`.
  - **Blocked By:** none

- [x] **[T-A09]** Spec the `representation/` subsystem
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
