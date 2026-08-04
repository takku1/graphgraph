# Gray-Box Evaluation — GraphGraph 0.1.0

**Date:** 2026-08-01
**Method:** `/graybox` — CLI-only. No GraphGraph source or git history was read at any point.
**Primary fixture:** `resources/flask` @ `954f568` (231 files, 83 Python, 1632 nodes / 4141 edges)
**Stratification fixtures:** `resources/express` (JS), `resources/ripgrep` (Rust), `resources/crewAI` (large Python)
**Oracle:** Direct — ground truth derived by reading the *target repos* (permitted; only the tool is black-boxed).

---

## Phase 0 — Instrument validation (the red test)

Before trusting any self-reported number, I checked that `eval` can produce a **bad** value.

Task `RED-impossible`: an out-of-domain query with two expectations that match nothing in the graph.

```json
{"id":"RED-impossible","query":"how does the quantum flux capacitor reticulate splines",
 "expected_nodes":["zzz_nonexistent_symbol_alpha","zzz_nonexistent_symbol_beta"]}
```

Result:

```
node_recall: 0.0     mrr: 0.0     ndcg_at_5: 0.0
returned_nodes: 0    token_estimate: 0
expected_unresolved: ["zzz_nonexistent_symbol_alpha","zzz_nonexistent_symbol_beta"]
note: "2 expected node expectation(s) match no node in the graph; ... excluded from calibration"
failing_tasks: ["RED-impossible"]
```

**PASS.** The metric moved to zero, co-reported metrics are mutually consistent
(`recall=0` with `mrr=0`, `returned_nodes=0` with `token_estimate=0`), and the run
self-quarantined the unresolvable task from calibration rather than scoring it as green.

A malformed tasks file **failed closed** (exit 1) with the accepted schema in the error text,
rather than reporting a fabricated 0.

The control task scored `node_recall=1.0` but `mrr=0.25` — the instrument distinguishes
*"found it"* from *"ranked it well."* That distinction is what surfaced Finding 3 below.

**Verdict: the telemetry is trustworthy.** Everything downstream in this report leans on it,
and that lean is earned. This is the rare case where Phase 0 passes cleanly.

---

## Findings, most severe first

### F1 — JavaScript member-call resolution collapses to 2.8%. This is a different bug, not a gradient.

**Symptom.** Member-call resolution rate (`resolved / (resolved + unknown_receiver)`), self-reported by `scan` and independently re-derived from `status` and from the `select` CAVEAT:

| Fixture | Language | resolved | unknown_receiver | **rate** | trust label |
|---|---|---:|---:|---:|---|
| flask | Python | 919 | 484 | **65.5%** | `high` |
| crewAI | Python | 6602 | 5004 | **56.9%** | `mixed` |
| ripgrep | Rust | 1225 | 2328 | **34.4%** | `mixed` |
| express | **JavaScript** | 180 | 6182 | **2.8%** | `high` |

**Evidence (direct oracle).** In express, `lib/application.js` methods `use`, `engine`, `param`,
`handle`, `init` — the entire public API — all report `callers=0`. Ground truth by grep over
`lib/`, `examples/`, `test/`:

```
.use(     : 655 call sites
.handle(  :  35 call sites
.param(   :  27 call sites
.engine(  :  15 call sites
```

`app.use` is the single most-invoked symbol in the repository. The graph reports zero callers.

**Inferred (marked as inference).** The unresolved-receiver shape histogram points at the cause:
express is `named_local=4260, call_result=1790` — i.e. `var app = express(); app.use(...)`. The
receiver is a local bound to a factory-call result. Python resolves far better because `self.`
and class-scoped methods give a typed receiver for free; JS idiom almost never does.

**Floor.** Local-variable type inference within a single file — bind `const x = require('./foo')`
and `const app = express()` to their definition sites — is a well-understood intra-procedural
dataflow pass. It should lift JS from 2.8% into the same 60–70% band as Python without any
cross-file type system.

**Gap.** ~23× below the Python stratum. This is the finding that caps every downstream capability.

**What if.** One intra-file receiver-binding pass for `const`/`let`/`var` assignments would
collapse this gap almost entirely, because 69% of express's unresolved receivers (4260/6182)
are the single `named_local` shape.

---

### F2 — `select production_callers = 0` has no discriminating power on JS (98.8% of symbols).

**Symptom.** The dead-code predicate is advertised in `select --help` ("*e.g. symbols with no
production caller*"). Measured hit rates:

| Fixture | zero-production-caller symbols | total symbols | **apparent dead rate** |
|---|---:|---:|---:|
| flask | 1203 | 1354 | 88.8% |
| ripgrep | 2059 | 2833 | 72.7% |
| express | 2915 | 2951 | **98.8%** |

**Evidence.** Direct consequence of F1, confirmed by the express sample above (`app.use` with 655
real call sites listed as dead). Also confirmed on Python, where resolution is *best*:
`BlueprintSetupState.add_url_rule` (`sansio/blueprints.py:87`) reports `callers=0`, but ground
truth shows two real call sites — `blueprints.py:324` (`state.add_url_rule(`) and `blueprints.py:434`
(`lambda s: s.add_url_rule(`). Both are the `named_local` shape.

**Credit where due.** The tool *tells you this*, unprompted, in a CAVEAT attached to every
`select` result:

> `CAVEAT: member-call resolution 2.8% (180/6362); 6182 call sites lack receiver evidence and
> produce no calls edge; 154 bare call sites named a symbol the graph defines but could not be
> bound to one definition, and were discarded, so zero-caller counts are an upper bound on dead
> code, not a proof`

This is exemplary. The tool's model of its own incompleteness is *accurate* — I followed the
caveat and it led me straight to the real defect. Most tools would have emitted `callers=0` with
no qualifier.

**Floor.** At 65% resolution the predicate is a useful triage filter. At 2.8% it is noise.
The feature should refuse to answer — or downgrade to `exists`-only — below a resolution threshold.

---

### F3 — Semantic equivalence is violated: two paraphrases of one question share **zero** results.

**Symptom.** Three paraphrases of the same question against flask:

| Query | nodes | `add_url_rule` present? | top-5 |
|---|---:|---|---|
| "where are url rules registered on the Flask app" | 11 | yes (rank 4) | `app_url_value_preprocessor, app_url_defaults, handle_url_build_error, add_url_rule, create_url_adapter` |
| "how does Flask register routes" | 30 | **no** | `register_error_handler, register_template_filter, register_template_global, register_template_test, routes_command` |
| "what code adds a URL rule to the application" | 47 | yes (ranks 1–4, all four defs) | `add_url_rule ×4, _get_exc_class_and_code` |

```
Jaccard(Q1, Q2) = 0.00
Jaccard(Q1, Q3) = 0.06
```

**Evidence (metamorphic relation violated).** Semantic equivalence requires paraphrases to
retrieve substantially the same set. Zero overlap between Q1 and Q2 falsifies it outright.
Q2 returned four `register_*` symbols — it matched the *token* "register", not the *concept*.

**This is retrieval, not extraction.** Extraction is complete: `select "label contains add_url_rule"`
returns all four definitions that ground-truth grep finds
(`sansio/app.py:605`, `blueprints.py:87`, `blueprints.py:413`, `scaffold.py:368`). The information
is in the graph; anchor selection fails to reach it.

**Inferred.** Anchor selection is dominated by lexical overlap with node labels. Q3 succeeds
because it literally contains the tokens "adds" + "url rule"; Q2 fails because Flask's registration
primitive is not lexically named "route-register."

**Partial mitigation exists but is off by default.** With `--source-mode all` the receipt shows
`semantic:+` and the packet does surface `Scaffold::route` (arguably a correct answer — `@app.route`
is the user-facing route registration API). But `add_url_rule` is *still* absent from a 48-node packet,
and the run self-reports `state=incomplete`.

**Floor.** A symbol-level embedding index built at scan time, queried alongside the lexical anchors,
should make paraphrase Jaccard > 0.6 for same-intent queries.

**What if.** Build the semantic index during `scan` instead of lazily on first `--source-mode all`
(see F6). The capability is present and works; it is simply never turned on.

---

### F4 — `update -d <dir>` ignores `--directory` when resolving the graph path. Hard failure.

**Symptom.** Reproducible, exit code 1:

```
$ graphgraph update -d C:\...\resources\flask --files src/flask/helpers.py
Error: [Errno 2] No such file or directory: '.graphgraph\graph.gg'
```

**Evidence.** `--output` defaults to `.graphgraph/graph.gg` relative to **cwd**, not to `--directory`.
`scan -d <dir>` and `status -d <dir>` both resolve correctly from any cwd; `update -d <dir>` does not.
Workaround confirmed working: pass `--output <dir>\.graphgraph\graph.gg` explicitly (exit 0, 0.29s).

**Why it matters more than it looks.** This breaks the exact edit-loop the tool is built for. An
agent or hook operating on a repo from a different working directory cannot call `update` at all
without knowing the workaround — and the error message (`No such file or directory`) points at a
missing graph rather than at the real cause, so the natural next move is a wasteful full `scan`.

**Floor.** One line: resolve the default `--output` against `--directory`, matching `scan`/`status`.
This is the cheapest high-value fix in the report.

---

### F5 — `relations` spends 90% of wall-clock on process start and graph load.

**Symptom.** The tool self-reports its internal work; I measured wall clock around it.

| Fixture | graph size | self-reported `ms` | wall clock | **overhead** |
|---|---:|---:|---:|---:|
| flask | 0.53 MB | **21.97 ms** | 203 ms | 9.2× |
| crewAI | 8.61 MB | (~22 ms) | 522 ms | ~24× |

Fixed process-start cost, measured independently via `graphgraph --version` × 4: **~120 ms**
(0.132, 0.129, 0.118, 0.119 s).

**Evidence.** Decomposition: `203ms = 120ms process start + ~60ms graph load + 22ms actual work`.
On crewAI the load term grows to ~400ms while the work term stays flat.

**Floor.** The 22 ms of real work is *already at the floor* — an in-memory adjacency lookup on a
1632-node graph should cost single-digit-to-low-double-digit milliseconds, and it does. The other
181 ms is pure plumbing.

**Gap.** 9× on a small repo, ~24× on a large one, and **diverging** with corpus size.

**What if.** A persistent daemon holding the graph in memory (`graphgraph serve` + a thin client,
or an MCP server that keeps the graph resident) makes every `relations` call ~22 ms **invariant to
corpus size**. This is the single change that most directly serves "whip through calls fast."

---

### F6 — `update` cost is invariant to Δ (excellent) but scales with corpus size (the real cost).

**Symptom.** The `update --help` text claims: *"No directory walk, no hashing of untouched files —
cost scales with `--files`, not repo size."* Tested both halves of that claim.

**Half one — TRUE, and at the floor.** On crewAI (20948 nodes, 8.61 MB), 3 runs each:

```
1 file  (src/crewai/crew.py)          mean 0.773 s   [0.782, 0.767, 0.769]
5 files (crew, agent, task, process, llm)  mean 0.770 s   [0.779, 0.775, 0.757]
```

5× the files costs **the same**. The marginal cost of Δ is effectively **zero**. The re-extract-and-
splice logic is genuinely excellent and should not be touched.

**Half two — FALSE.** Same 1-file update across corpus sizes:

| Fixture | nodes | graph | 1-file update | read-only (`relations`) | inferred persist |
|---|---:|---:|---:|---:|---:|
| flask | 1,632 | 0.53 MB | 0.29 s | 0.203 s | ~0.09 s |
| crewAI | 20,948 | 8.61 MB | 0.77 s | 0.522 s | ~0.25 s |

A 16× larger graph costs 2.6× more for an identical 1-file change. Since Δ-cost is provably ~0,
**100% of that growth is whole-graph load + whole-graph persist.**

**Floor.** Reparse one file with tree-sitter (~5–15 ms) + splice O(Δ) edges (~1 ms) + persist O(Δ)
bytes via an append-only delta log (~1 ms) ≈ **30 ms, invariant to corpus size**. With a resident
daemon (F5), ~20 ms.

**Gap.** ~25× above floor on crewAI, and diverging linearly with corpus size.

**What if.** Append-only delta journal with periodic compaction, instead of rewriting all 8.61 MB
on every single-file edit. Combined with F5's daemon, a 1-file update becomes ~20 ms on a repo of
any size.

---

### F7 — `trust=high` is reported at 2.8% resolution. The label tracks ambiguity, not coverage.

**Symptom.** From `status`:

- express — `resolution 2.8%`, `coverage=partial`, **`trust=high`**, `ambiguous=0`
- ripgrep — `resolution 34.4%`, `coverage=partial`, **`trust=mixed`**, `ambiguous=6`

`trust` is *non-monotone* in resolution rate: the worst-resolved fixture carries the best trust label.

**Inferred.** `trust` appears to be driven by the `ambiguous` count (0 → high, >0 → mixed), which is
a measure of *conflict among resolved edges*, not of *how much was resolved at all*.

**Why it matters.** `coverage=partial` and the CAVEAT are both accurate, but a reader scanning for a
one-word confidence signal lands on `trust=high` next to a graph where 97.2% of member calls are
missing. It is the one place in an otherwise scrupulously honest telemetry surface where the
headline label contradicts the detail.

**Floor.** Make `trust` a function of both terms — e.g. `low` below 40% resolution regardless of
ambiguity. This is a labeling fix, not an algorithmic one.

---

### F8 — The semantic index is never built unless you know to ask, and nothing tells you.

**Symptom.** `doctor` reports `Backend: fastembed:BAAI/bge-small-en-v1.5 (real embeddings active)`.
Default queries are nonetheless purely lexical (F3), because `--source-mode auto` "consumes only
current indexes with a ready backend and never builds," and `scan` does not build one.

First `--source-mode all` run: **26.6 s** (one-time index build). Subsequent: **2.26 s**, then
**0.43 s** cached.

**This is not a performance problem** — warm semantic retrieval is cheap. It is a discoverability
problem: a capability that is installed, working, and paid for sits dormant, and the tool reports it
as "active" when it is not being used by the default path.

**Floor / what if.** Build the index at the tail of `scan` (adds ~26 s one-time to a 2.4 s scan —
worth gating behind `--semantic` if that is unacceptable), or have `status` report
`semantic index: MISSING — run 'graphgraph <x>' to enable` alongside the existing coverage warnings.

---

## What is already at the floor — do not touch this

Reports that are only negative get discounted, and this one would badly misrepresent the tool if it
stopped at F1–F8. **The hard parts are done.** Specifically:

1. **Extraction completeness.** Every ground-truth check I ran found the symbol present in the graph.
   All four `add_url_rule` definitions, across three files and three classes, extracted correctly with
   accurate `path:line` and qualified names. Extraction bounds retrieval, and extraction is not the
   bottleneck.

2. **Δ-splice cost is exactly zero.** 1 file and 5 files cost the same to within noise (0.773 vs
   0.770 s). This is the algorithmically hard part of incremental graph maintenance and it is solved.

3. **Packet format efficiency.** The `#gg` format — relation legend, indexed node list with
   `path:line` + signature + qualified name, edges as index pairs — is close to information-theoretically
   minimal for what it conveys:

   | Payload | ~tokens | ratio |
   |---|---:|---:|
   | `#gg` packet answering the query | **336** | 1× |
   | `src/flask/sansio/app.py` (the one relevant file) | 10,127 | **30×** |
   | all of `src/flask/` | 89,358 | **266×** |

   A 30–266× compression ratio against the naive alternative, while still carrying exact jump targets.

4. **Abstention on out-of-domain input.** The negation/null relation holds cleanly:

   ```
   $ graphgraph query "how do I configure the kubernetes ingress controller for GPU scheduling"
   GraphGraph abstained: no matching graph anchors; automatic routing confidence is low (0.147).
   ```

   Most retrieval systems return top-k nearest neighbours regardless. Explicit abstention with a
   confidence number is the correct and rarer behavior.

5. **Ambiguity is surfaced, not guessed away.** `relations --direction callers add_url_rule` returns
   `"s":"ambiguous"` with all four candidate IDs and a `retry_candidate_id` action — it refuses to
   silently pick one. Correct.

6. **Per-call completeness receipts.** Every `relations` response carries:

   ```json
   "r":{"matched":2,"eligible":1,"returned":1,"omitted":0,"filtered":{"tests":1,"external":0},
        "graph_complete":true,"topology":"partial","answer_complete":false,
        "freshness":"unchecked","ms":21.97},
   "a":["sync_if_completeness_required","verify_absence_or_count"]
   ```

   `answer_complete:false` plus a suggested next action, in-band, on every call. This is better
   instrumentation than most commercial code-intelligence products ship.

7. **Metamorphic relations that hold.** Idempotence: byte-identical output across repeated runs.
   Monotonicity: results at `--max-nodes 10` are a strict subset of `--max-nodes 80` with nothing
   dropped, saturating honestly at 64.

8. **Honest truncation reporting.** crewAI hit the 5000-file cap (`selected=5000 matched=20217`) and
   `status` warns: *"file scan was truncated — only some of 20217 matching files were read."* No silent
   data loss. (Minor: `scan` itself prints the numbers without flagging them as a warning, and the
   `status` warning sits *below* `Structural validation: PASS`.)

9. **The `eval` harness.** Passed the red test, reports stratified metrics, calibration receipts with
   Brier/ECE, cold-vs-warm latency separation, and bootstrap comparison against a saved baseline.
   This is CI-grade measurement infrastructure that already exists.

**The shape of this system is: excellent design and modelling, with unoptimized plumbing.** That is a
far better position than the reverse. The expensive, subtle work — incremental splice, packet
encoding, abstention, completeness accounting — is done and correct. What remains is mostly mechanical.

---

## Scoring

Weighted by the layer that caps the others: you cannot retrieve what was never extracted, and you
cannot reason over edges that were never resolved.

| Layer | Today | Credible ceiling | Capped by |
|---|---:|---:|---|
| Extraction (symbols, defs, locations) | **9 / 10** | 9.5 | already near floor |
| Edge resolution (member calls) | **4 / 10** | 9 | F1 — 2.8% on JS, 65% on Python |
| Retrieval / ranking | **5 / 10** | 9 | F3 — lexical anchors, semantic off |
| Packet encoding | **9.5 / 10** | 10 | already near floor |
| Telemetry & honesty | **9 / 10** | 9.5 | F7 — one mislabeled `trust` |
| Latency / plumbing | **3 / 10** | 9.5 | F5, F6 — 90% overhead, O(corpus) persist |
| CLI ergonomics | **6 / 10** | 9 | F4 — `update -d` broken |
| **Overall** | **≈ 6 / 10** | **≈ 9.5 / 10** | edge resolution × plumbing |

The ceiling is high and reachable because none of the blocking issues are architectural. The score is
held down by two clusters — receiver typing and process/persist plumbing — that are independently
fixable and do not interact.

---

## The road to 11/10 — what would make an agent whip through calls

Ordered by (impact × agent-experience) ÷ effort.

**1. Resident graph daemon.** *The single highest-leverage change.* Currently 90% of every call is
process start + graph load (F5). A resident process makes `relations` ~22 ms and `update` ~20 ms,
**invariant to corpus size**. This is the difference between "a tool I call when I suspect I need it"
and "a tool I call reflexively instead of thinking." At 20 ms an agent can afford 50 graph calls in
the time one `Read` takes — which is the actual unlock.

**2. Intra-file receiver binding.** Bind `const app = express()` / `let x = new Foo()` / `x = Foo()`
to definition sites within a single file. Targets the `named_local` shape, which is 69% of express's
and 59% of flask's unresolved receivers. Lifts JS from 2.8% → ~60%+ and Python from 65% → ~85%,
which in turn makes F2's dead-code predicate real and blast-radius trustworthy.

**3. Batch query in one invocation.** `graphgraph relations --batch ids.txt` or accepting multiple
targets. Amortizes the 120 ms process start and graph load across N questions. Even without the
daemon this converts "10 calls = 2 s" into "10 calls = 0.35 s." Cheap to build, immediately useful.

**4. Append-only delta journal for persist.** Stop rewriting 8.61 MB per single-file edit (F6).
Compaction on a threshold. Makes update cost genuinely O(Δ) as the help text already claims.

**5. Semantic index built at scan time** (F8), with lexical + semantic anchors fused. Fixes the
paraphrase cliff. The components already exist and work; they just need wiring into the default path.

**6. Fix `update -d` output resolution** (F4). One line. Unblocks hook- and agent-driven edit loops.

**7. `trust` as a function of coverage, not just ambiguity** (F7). Labeling fix.

**8. Session-scoped anchor memory.** An agent asks 5 questions about the same subsystem; re-resolving
anchors from scratch each time is waste. Cache the resolved anchor set per session and let follow-ups
expand from it. This is what makes a graph feel like a *conversation* rather than a *lookup table* —
the qualitative jump from 10 to 11.

---

## Proposed CI gates

**Nominated single scalar: `member_call_resolution_rate`.**

It is one number, already computed and emitted by `scan`/`status`/`select`, cheap, comparable across
repos and languages, requires no contested assumptions, and moves the instant the underlying issue
improves. It directly caps caller/callee/blast-radius/dead-code truth. Gate on it per language.

```
# Correctness — per-language, catches F1
member_call_resolution_rate(python)     >= 0.65   # today 0.655 flask / 0.569 crewAI — hold the line
member_call_resolution_rate(rust)       >= 0.34   # today 0.344 — hold the line
member_call_resolution_rate(javascript) >= 0.40   # today 0.028 — FAILS, target for F1

# Retrieval — catches F3
paraphrase_jaccard(same-intent query pair) >= 0.50   # today 0.00 — FAILS

# Latency INVARIANCE — the most valuable gate; catches F5/F6
relations_wall_ms(crewAI) / relations_wall_ms(flask) <= 1.2   # today 2.6 — FAILS
update_1file_wall_ms(crewAI) / update_1file_wall_ms(flask) <= 1.2   # today 2.7 — FAILS

# Latency absolute
relations_wall_ms(any fixture)   < 60
update_1file_wall_ms(any fixture) < 300   # today 773 on crewAI — FAILS

# Δ-invariance — protects the part that is already at the floor
update_wall_ms(5 files) / update_wall_ms(1 file) <= 1.3   # today 1.00 — PASSES, keep it that way

# Regression guard on instrument integrity
eval red-test task must report node_recall == 0.0 and appear in failing_tasks
```

The invariance gates matter more than the absolute ones: asserting that the large fixture must match
the small one converts "scales acceptably" into "does not scale at all," which is the correct target
and the one that makes the daemon work visible.

---

## Coverage — what was NOT tested

Stated explicitly so silence is not read as a pass:

- `plan`, `render`, `final`, `context`, `snippets`, `validate`, `validate-graph` — not exercised
- `ingest`, `compare`, `remove`, `artifacts`, `install`, `platform` — not exercised
- `--packet` variants beyond default `gg` (sql, hybrid, semantic_arrow, svo, doc_summary) — untested
- `--representation hybrid` (flagged experimental by the tool) — untested
- `--query-class` overrides — only `auto` routing tested
- `--history` / git `fixes` edges — untested
- Doc/concept extraction quality — observed only via counts (flask 23.15% concept coverage,
  express 0.84%, ripgrep 8.64%; all self-reported `health=partial`/`sparse`), never ground-truthed
- MCP server path — all testing was CLI; MCP was not exercised
- Languages other than Python / JavaScript / Rust — 12 further grammars are declared ready and untested
- Multi-run statistical rigor — timings are means of 3 runs on one machine, not distributions

---

## Artifacts created in target repos

Testing wrote `.graphgraph/` caches into four repos. To remove:

```
resources/flask/.graphgraph      # REBUILT this session (see note)
resources/express/.graphgraph    # new
resources/ripgrep/.graphgraph    # new
resources/crewAI/.graphgraph     # new  (8.61 MB)
```

`graphgraph remove-graph-files` / manual delete both work. All four are untracked derived caches.

**Note on flask:** a pre-existing `.graphgraph/` was present at session start and was of unknown age.
It was **moved, not deleted**, to
`…\Temp\claude\C--Users-dcarn-aiprojects\b5cb1d17-…\scratchpad\gb\flask-preexisting-graphgraph`
and flask was rebuilt clean so all timings in this report are controlled. Restore from there if wanted;
otherwise that scratchpad directory is disposable.

---

## Methodology notes

- **Black-box discipline held.** No GraphGraph source file and no GraphGraph commit history was read.
  All internal claims in this report are labeled *inferred* and rest on CLI output plus ground truth
  derived from the target repos.
- **Every striking number was re-derived a second way.** The resolution rates were read independently
  from `scan` stderr, `status`, and the `select` CAVEAT, and agree to the digit.
- **No absence was concluded from truncated output.** `select` results that print `truncated` were
  cross-checked with `--mode count`; the `add_url_rule` absence claim was verified against the full
  packet, not a `head`.
- **One in-flight correction.** An early reading treated the 26.6 s `--source-mode all` run as the
  steady-state semantic cost. Re-running showed 2.26 s warm and 0.43 s cached — the 26.6 s is a
  one-time index build. F8 is written against the corrected numbers, and the finding changed from
  "semantic retrieval is slow" to "semantic retrieval is never enabled," which is a materially
  different and less severe claim.
