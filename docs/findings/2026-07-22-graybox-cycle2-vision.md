# Gray-Box Cycle 2 — The Zero-Friction Vision

**Date:** 2026-07-22 · **Method:** `/graybox` cycle 2 (CLI-only; source never read)
**Fixture:** `resources/flask` (83 py, 115 docs → 5,868 nodes, 3.5s build)
**Framing:** Cycle 1 measured *what is*. This cycle asks *what would have to be true*
for a developer to work through a project at lightning speed with zero friction.
Every concept below is anchored to a friction moment actually observed while
simulating a real task ("understand and safely modify Flask route registration").
Concepts are deliberately fantastical — implementation is the next agent's problem.

---

## The observed friction ledger (ground truth for the dreaming)

Simulated task, 8 invocations, ~15 minutes wall including thinking:

| Step | Command | Wall | Outcome |
|---|---|---|---|
| Orient | `query "how does route registration work"` | 1.2s | ★ Excellent — full Scaffold→App→Flask hierarchy in one packet |
| Blast radius | `query --query-class blast_radius` | 1.4s | Mediocre — returned class *siblings* (`jinja_loader`, `static_folder`), not dependents |
| Affected tests | `query --query-class affected_tests` | 1.4s | **2 test nodes vs 8 test files ground truth** — can't skip the suite |
| Get source | `snippets --labels` | 0.3s | Failed — flag is `--starts`, help said "labels" |
| Get source (retry) | `snippets --starts` | 0.4s | ★ All definitions, clean excerpts |
| Stack trace → context | `platform repair "<traceback>"` | 0.4s | ★ Correctly anchored the frame |

Recurring taxes: ~0.3–0.5s process spawn per question; every question is a
*pull* the dev must think to ask; trust is unknowable per-packet, so everything
gets re-verified by grep anyway — **the verification tax is the real time sink,
not the query latency.**

---

## The Ten Concepts

### 1. The graph as a nervous system, not a database
**We have:** a graph you *query* — spawn a process, phrase a question, wait ~1s.
**If it were:** a resident organism that is always warm, always current
(`platform watch` already stubs this), and **pushes** context — the moment a file
is opened or an edit lands, the relevant subgraph packet is *already materialized*
beside it. Questions get answered before they are asked.
**Then:** query latency stops mattering because querying stops being an event.
The dev never leaves flow to "go ask the graph." This is the single concept the
others hang off.

### 2. The runtime truth stream
**We have:** static call edges that miss most of reality (2/8 test files found;
cycle 1: 0/4 callers). Syntax guessing has a ceiling.
**If it were:** every test run, every dev-server request, every REPL session
feeds real call events back into the graph as typed evidence (`platform trace`
already accepts trace files — imagine it *ambient*). Static edges are hypotheses;
runtime events are confirmations.
**Then:** blast radius and affected-tests become **empirical, not inferred** —
the graph doesn't guess who calls `add_url_rule`, it has *watched* them do it.
The correctness ceiling of the whole product lifts at once.

### 3. Error → briefed engineer, in one paste
**We have:** `platform repair` anchoring a traceback to the right method in 432ms.
Genuinely impressive seed.
**If it were:** paste any error and receive the *minimal causal slice*: the
upstream values that could have produced it, the most recent graph-diff that
touched those nodes (episodes exist), the memory of why that code changed, and
the one test that would have caught it.
**Then:** debugging inverts — instead of a dev reconstructing context around an
error, the error *arrives pre-contextualized*. Ten-minute investigations become
one paste.

### 4. Time travel with narration
**We have:** `platform as-of` and `episode` stubs — snapshots at timestamps.
**If it were:** "what changed in routing since Tuesday, and what could it have
broken?" answered as a *narrated causal diff* — not a list of edges, but a story:
this signature changed → these three dependents adapted → this one didn't.
**Then:** code review, regression hunting, and onboarding-to-a-change collapse
into one question. The graph becomes the project's autobiography.

### 5. The project as a saved game
**We have:** `platform memory` (scoped agent/project memory) sitting unused.
**If it were:** every query asked, node touched, decision made, and dead end hit
auto-annotates the graph. Opening the project tomorrow yields a *frontier packet*:
here's where you were, here's what was unresolved, here are the questions you
asked but never answered.
**Then:** session-restart cost → zero. For agents this is transformative: a new
agent instance resumes mid-campaign instead of re-deriving the world.

### 6. Speculative edits — see the shatter-map before touching the file
**We have:** blast radius as *structural adjacency* (it showed me `add_url_rule`'s
classmates, not its dependents).
**If it were:** "if I change this signature to X, show me the future" — the graph
applies the edit *virtually*, propagates the contract change along edges, and
returns the shatter-map: what breaks, what adapts silently, what tests fire.
**Then:** the edit-verify loop reverses into verify-then-edit. You never make a
change whose consequences you haven't already seen. This is the "lightning speed"
concept in its purest form.

### 7. One language: intent, no vocabulary
**We have:** a failed invocation because help said "labels" and the flag was
`--starts`; ten packet types; eleven query classes to know about.
**If it were:** a single intent surface — you say what you want in your own words
and the router (query_router_v4 already exists and routed everything correctly
this cycle) owns *all* dispatch, across every subcommand.
**Then:** the tool's entire flag vocabulary becomes internal. Nothing to learn,
nothing to mis-remember, no failed invocations. Friction from knowledge → zero.

### 8. The federated hive
**We have:** `platform federate` / `register` / cross-repo stubs; a workspace with
25+ cloned repos sitting next to each other, each an island.
**If it were:** the whole workspace one namespaced graph — "who has solved
retry-with-backoff well?" hops from your project into flask, requests, redis,
and returns the best exemplar *with its tests*.
**Then:** every repo you've ever cloned becomes retrievable experience. The
graph stops describing one project and starts describing *everything you know*.

### 9. Trust as currency
**We have:** an answerability gate that was wrong in both directions (cycle 1),
so every packet gets re-verified by grep — the biggest hidden time cost observed.
**If it were:** every packet stamped with calibrated, evidence-backed confidence
("these 4 edges runtime-confirmed 212 times; these 2 are static guesses"), so a
consumer knows *exactly when verification is needed*.
**Then:** agents stop double-checking what's already certain. Half the tool calls
in an agent session simply disappear. Trust is the multiplier on every other
concept — an untrusted oracle is just a suggestion engine.

### 10. The test oracle inversion
**We have:** affected-tests recall so low (2 vs 8 files) that the answer is
decorative — you run the whole suite anyway.
**If it were:** empirically-grounded test selection (via concept #2's runtime
stream) — "this edit needs exactly these 4 tests, 2.1s" — with the graph *running
them* and splicing results back as evidence.
**Then:** CI collapses from minutes to seconds, and green becomes a property the
graph continuously maintains rather than an event you wait for.

---

## The composite fantasy — one working day, zero friction

> Open the project. The graph is already warm and current (1). It hands you your
> frontier from yesterday (5). You ask, in plain words, what you want to change
> (7); the answer arrives with runtime-confirmed edges (2) and a confidence stamp
> you can bank on (9). Before editing, you preview the shatter-map (6). You edit;
> the graph re-splices in milliseconds and fires exactly the four affected tests
> (10). One fails with a traceback; you paste it and receive the causal slice
> (3). You fix it, and the episode — what changed, why, what it touched — is
> recorded into the project's autobiography (4), across every repo you own (8).

Each concept alone is an incremental gain. Chained, they are multiplicative:
the dev's loop loses its *wait states* — and a loop with no wait states is not
"faster," it is a different kind of work.

## Why this is credible, not just fantasy

The striking discovery of this cycle: **almost every concept already has a stub
in the CLI.** watch, trace, repair, as-of, episode, memory, federate, serve,
hooks — the skeleton of the nervous system is scaffolded. Repair and snippets
already run in ~400ms and give correct answers. What's missing is not vision —
the vision is demonstrably already in the architecture — it's (a) the runtime
evidence stream to make edges true, (b) the resident/push execution model, and
(c) calibrated trust. Those three unlock the other seven.

## Priority order for the implementing agent

1. **#2 Runtime truth stream** — fixes cycle 1's biggest correctness gap *and* enables #6, #9, #10.
2. **#1 Resident nervous system** — kills the per-question tax; `watch` + `serve` stubs exist.
3. **#9 Trust as currency** — converts everything else from "interesting" to "load-bearing."
4. **#3/#5** — repair and memory are the ripest stubs (already fast, already correct anchoring).
5. **#6/#4/#10/#8** — build on the foundations above.

## Test artifacts

- `resources/flask/.graphgraph/` created (delete to clean).
- No file contents modified.

## Coverage note

Probed this cycle (new vs cycle 1): `context`-adjacent orientation flow, `snippets`,
`platform repair`, and help surfaces of `select`, `platform` (watch/trace/memory/
episode/as-of/federate). Still untested: `plan`/`render`/`final`, `platform serve`,
actual `trace`/`memory`/`as-of` execution with real data, federation, MCP path.

---

## Implementation review — 2026-07-22

This addendum preserves the black-box observations above while correcting the
implementation inference made from the CLI surface. The named platform
capabilities are not empty stubs: runtime trace ingestion, temporal projection,
memory projection, federation, repair context, source watching, HTTP service,
and hooks have implementation and automated coverage. A focused run of
`tests/test_platform.py` passed all 37 tests. The source planner also projects
semantic, memory, temporal, federation, and runtime-trace evidence into the
normal query path; these are not merely isolated commands.

The vision still identifies real product gaps, but the boundary is different:

| Vision claim | Verified current state | Remaining gap |
|---|---|---|
| Runtime truth stream | Trace JSON/JSONL becomes `observed_calls` edges and is consumed by query source planning. | Automatic test/dev-server collection, run/coverage identity, edge aggregation, and safe retention. |
| Time travel, memory, federation | Implemented and covered for projection, scoping/namespacing, and cross-repository links. | Product-quality narratives, lifecycle policy, discovery, and real multi-project acceptance data. |
| Error to context | Repair anchoring works and returns related tests. | Causal/data-flow slices and diff/episode correlation. |
| Resident nervous system | Watch and service machinery exist. | A proven editor/event push protocol and measured end-to-end latency benefit. |
| Trust as currency | `answerability.confidence`, status, provenance, and caller-quality caveats exist. | Calibration against labeled completeness outcomes and a consumer policy with measured verification savings. |

Runtime evidence must not be treated as a complete label oracle. An observed
call is strong positive evidence; a call absent from one trace may simply be an
unexecuted path. Therefore trace non-observation cannot be labeled `false`
without a coverage model or a separately declared ground-truth set.

The first grounded calibration slice now pairs `answerability.confidence` with
the existing eval suite's declared node/edge expectations. On the five-task
self-eval, four real tasks reached full node recall at confidence `0.7`; the red
control reached zero recall at confidence `0.2617`. The resulting five-bin
receipt was Brier `0.085697`, ECE `0.29234`, and MCE `0.3`. This is useful proof
that the instrument can discriminate the current examples, not a deployable
calibration curve: `n=5`, one repository, and only two occupied confidence
regions are far too small.

The initial isotonic implementation also needed two corrections before it was
safe to use: tied confidence values made the fit input-order-dependent, and a
documented step fit was applied with linear interpolation. Regression tests now
group ties before PAV and apply the fitted step thresholds exactly.

### Revised implementation order

1. Expand hand-labeled query outcomes across query classes and repositories;
   keep red controls and record which node/edge dimensions define completeness.
2. Measure the unmodified confidence signal by class and evidence provenance.
   Require minimum sample counts and a held-out evaluation split.
3. Add automatic runtime collection as positive evidence, with run identity and
   coverage receipts; do not infer negatives from non-observation.
4. Fit per-stratum recalibration only where the sample is sufficient, then gate
   it on held-out Brier/reliability improvement and unchanged recall/abstention.
5. Pursue push UX, speculative edits, and automatic affected-test execution only
   after the evidence and trust receipts are reliable enough to carry them.
