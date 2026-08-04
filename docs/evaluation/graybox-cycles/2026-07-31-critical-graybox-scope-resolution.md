# Critical gray-box run: GraphGraph scope resolution, scale, and fluidity

**Date:** 2026-07-31
**Version under test:** graphgraph 0.1.0 (CLI, `graphgraph-mcp` not restarted for this run)
**Predecessor:** `2026-07-31-critical-graybox-fix-delta.md`
**Method:** public CLI behavior, GraphGraph's own telemetry, hand-built frozen fixtures with by-construction oracles, metamorphic relations, and one differential control against `code-review-graph`. GraphGraph implementation source and version history were not inspected.

---

## Correction issued during this run

Early in the run I observed zero call edges for every JavaScript and TypeScript symbol in the polyglot fixture and was one step from recording "JS/TS call extraction is categorically broken." That would have been **wrong**. A minimal-variant probe (bare functions, CommonJS, ESM, arrow functions, `.ts`) resolved **6/6** correctly.

The real cause was unrelated to language. It is recorded below as Finding 1. The methodological lesson is the one the playbook already warns about: a clean 0% stratum is a gift *and* a trap — it localizes fast, but it must be re-derived independently before it is believed. The 0% here was real; my first explanation for it was not.

---

## Headline

The previous run closed the extraction gap and scored ~7.1/10. This run went after the layer underneath it and found that **the call-edge resolver discards a correct edge whenever the callee's name is not globally unique within its language — including when the call and the definition are in the same file.**

The sharpest statement of it is five lines of Python:

```python
# a.py                      # b.py
def Support():              def Support():
    return 1                    return 2
def Assist():
    return Support()        # <- this edge exists until b.py is added
```

With `a.py` alone: `Assist -> Support` is present. Add `b.py`, which only *defines* an unrelated `Support` and calls nothing, and the edge **inside `a.py` disappears.**

This is not a corner case. It has three properties that make it the top-priority defect:

1. **It deletes information that was already correct.** Adding a file reduced Flask's call graph by 19 edges (−9.6%).
2. **It is silent, and it is reported as complete.** `graphgraph select "production_callers = 0"` — the dead-code query — lists the live function as having zero callers, with `caller_evidence_complete: true`.
3. **It is not inherently hard.** `code-review-graph`, given byte-identical input, resolves the same edge at `confidence: 1, tier: EXTRACTED` by preferring file scope.

Revised score: **6.4/10 today** (down from the previous run's 7.1, not because anything regressed, but because this run measured a layer the previous board did not probe). Credible ceiling remains ~9.7.

---

## Phase 0 — instrument validation (the red test)

Before trusting any number GraphGraph reports about itself, I tried to make its metrics lie.

Fed a task file where expected nodes cannot exist (`zzz_nonexistent_symbol_qqq`):

| Probe | Result | Verdict |
|---|---|---|
| Impossible expected nodes | `node_recall 0.0`, `mrr 0.0`, `ndcg 0.0` | Metric moves. **Pass** |
| Unresolvable names | listed by name in `expected_unresolved` | **Pass** |
| Scoring hygiene | unresolvable tasks excluded from calibration, and it says so | **Pass** |
| Real expectation (`wsgi_app`) | `node_recall 1.0`, `mrr 1.0` | Discriminates. **Pass** |
| Out-of-domain query | `answerability_status: incomplete`, confidence `0.15` | **Pass** |
| Internal contradiction | none found (recall/MRR/nDCG mutually consistent) | **Pass** |

It also emits a full calibration decomposition — Brier, binned Brier, reliability, resolution, uncertainty, ECE, MCE, and reliability bins. That is real calibration science, not a dashboard.

**The instrument is trustworthy.** This is a genuine strength and it is why the rest of this report can lean on GraphGraph's own telemetry. It earns the right to be believed — which makes the one place it *does* overclaim (Finding 1c) worth fixing urgently rather than tolerating.

The scan telemetry is equally good. On the polyglot fixture it reported `member_calls=9/2/2/0 resolved/ambiguous/unknown-receiver/external-or-unmatched`. I derived the true member-call count by hand: 13. Resolved 9 = C#(4) + Java(4) + Python(1). Ambiguous 2 + unknown 2 = the four `e.Run()` sites in Go/Rust/JS/TS. **The telemetry matched hand-derived ground truth exactly.**

---

## Finding 1 — Same-file calls lose to global name ambiguity

### 1a. The mechanism

Frozen fixture: 7 languages (Python, JavaScript, TypeScript, Rust, Go, C#, Java), 22 files, **63 call edges true by construction**, plus a decoy `Middle()` in each helper file that nobody calls. Ground truth is enumerated in [the fixture oracle](fixtures/polyglot-scope-2026-07-31/ORACLE.md).

Controlled isolation:

| Configuration | Inbound call edges | Note |
|---|---:|---|
| `js/` alone | 6 | correct |
| `js/` + `py/` | 6 + 6 | correct — cross-**language** duplicates do not collide |
| `js/` + `ts/`, identical symbol names | **0** | total collapse |
| `js/` + `ts/`, TS symbols renamed | 6 + 6 | correct — renaming fixes it |
| two identical `helper.py` in different dirs | **0** | language-agnostic |
| two identical `helper.js` in different dirs | **0** | language-agnostic |

The trigger is **same-language duplicate symbol names across files**. Cross-language duplicates are correctly scoped. Go was an accidental control: I renamed its `Middle` to `CoreMiddle` to satisfy Go's single-package rule, making the name globally unique — and Go is the **only** language in the fixture where `Root -> Middle` survived.

### 1b. Imports resolve; same-file calls do not

The precise scope, from a three-file probe. Ground truth: `a.py::Support` has exactly two callers.

| Caller | Binding | Found? |
|---|---|---|
| `c.py::Imported` | `from a import Support` | **yes** (confidence 0.9) |
| `a.py::Assist` | same file, 3 lines below | **no** |

The resolver handles the harder case — cross-file import binding — correctly, and fails the trivial one. Same-file scope should be the *strongest* available binding; it is currently weaker than an import and weaker than nothing.

### 1c. It is reported as complete

This is the part that elevates severity. On the two-file repro:

```
graphgraph select "production_callers = 0"
  caller_evidence   : "no member-call telemetry on this graph"
  caller_evidence_complete : True
  -> Support (a.py)   listed as zero-caller
```

`Support` is called five lines below its own definition. The tool recommends it as dead code and marks the evidence **complete**.

GraphGraph has exactly the right caveat for this — *"zero-caller counts are an upper bound on dead code, not a proof"* — but it is emitted only when member-call telemetry exists. Collision-dropped edges do not set that flag, so the one case that most needs the caveat is the one case that does not get it.

To be fair to the tool: the `relations` receipt does report `answer_complete: false` and the natural-language path reports `state=incomplete, evidence:-`. It is not uniformly overconfident. But `select` is the documented dead-code surface, and there it is confidently wrong.

### 1d. Blast radius on real code

**Flask, controlled metamorphic test.** Copy `flask/helpers.py` to `copylib/helpers.py` — one added file, no other change:

| | Inbound call edges |
|---|---:|
| Baseline (406 symbols) | 197 |
| After adding 1 duplicate file | **178** |
| Edges contributed by the new copy | **0** |

All 19 lost edges were inside the untouched original tree. **Adding one file out of ~60 destroyed 9.6% of the repository's call graph and contributed nothing.**

**Exposure across real repositories** — fraction of plain functions whose name is duplicated within the same language:

| Repo | Plain functions | Duplicated name | Zero-caller (unique) | Zero-caller (dup) |
|---|---:|---:|---:|---:|
| Flask | 854 | 179 (21.0%) | 90.5% | **99.4%** |
| Sympy (core+solvers+physics, 355 files) | 4,843 | 313 (6.5%) | 79.5% | **95.5%** |

**A necessary honesty caveat on this table:** duplicated names in real Python are disproportionately closures (`wrapper`, `decorator`, `view`, `generate`) that are genuinely never called — so this stratum is contaminated and the gap is *not* purely attributable to the defect. I verified one candidate directly: `_make_timedelta` is duplicated across two Flask files and reports zero callers, but ground truth shows it is *referenced* (`get_converter=_make_timedelta`), not called — legitimately not a `calls` edge.

The clean evidence for this finding is the controlled Flask experiment (−19 edges) and the minimal repro, not the observational table. The table only bounds the exposed surface: **6–21% of plain functions sit in the at-risk set.**

### 1e. Where it does *not* bite

Merging `sympy/core` with `solvers` and `physics` **increased** core's inbound edges from 2,711 to 3,915 (+44.4%), because the added code genuinely calls into core. Normal repository growth is net-positive. The defect concentrates where duplicate names actually occur: vendored copies, forked modules, `v1/`/`v2/` API pairs, generated code, examples, and test fixtures that mirror production structure.

### 1f. Differential control

Same two-file input, `code-review-graph`:

```
callers_of("a.py::Support")
  -> a.py::Assist   kind=CALLS  confidence=1  tier=EXTRACTED
```

It returns `ambiguous` with candidates for the bare name `Support` — the same good behavior GraphGraph shows — and then resolves correctly once qualified, because it binds the edge to the file-local definition at construction time. **The problem is solved in a peer tool on identical input.**

---

## Finding 2 — Self-recursion is never recorded

`Fact(n)` calling `Fact(n-1)`, single file, globally unique name, no collision possible: `callers=1` (only the external caller), not 2.

Confirmed across **all 7 languages** in the fixture: every `Recurse -> Recurse` edge is absent, 0/7.

Independent of Finding 1. Consequences: recursion cannot be detected from the graph, cycle detection is incomplete, and a function called only by itself plus one caller undercounts. Lower severity than Finding 1, but it is a universal, deterministic miss.

---

## Finding 3 — Fixture oracle results

Against the frozen 7-language fixture (63 edges true by construction):

| Language | Edges found | Missing |
|---|---:|---|
| Python | 7/9 | `Root->Middle` (collision), `Recurse` |
| Go | 7/9 | `Root->Run` (member), `Recurse` |
| C# | 7/9 | `Root->Middle` (collision), `Recurse` |
| Java | 7/9 | `Root->Middle` (collision), `Recurse` |
| Rust | 6/9 | `Root->Middle`, `Root->Run`, `Recurse` |
| JavaScript | 0/9 (7/9 in isolation) | all — Finding 1 |
| TypeScript | 0/9 (7/9 in isolation) | all — Finding 1 |

**Recall 34/63 = 54%** as configured; **~48/63 = 76%** with the collision defect removed (JS/TS restored to their isolated behavior).

**Precision: 7/7 perfect.** Not one false edge was created into any of the seven uncalled decoys. GraphGraph's failure mode is to *drop* evidence, never to fabricate it. That is by far the better direction to fail in, and it should be preserved through any fix.

Two smaller observations:
- `Root -> Engine.Run` (member call on an instance) resolves in Python, C#, Java; not in Go, Rust, JS, TS. The telemetry predicts this exactly and does not hide it.
- `rs/core_test.rs` was classified `is_test: false` while Go's `core_test.go` was correctly detected. **Low confidence / likely my fixture's fault** — `*_test.rs` is not idiomatic Rust (real Rust uses `#[cfg(test)]` or `tests/`). Not counted against the tool.

---

## Finding 4 — Scan cost on large repositories

| Repo | Files | Nodes | Wall time |
|---|---:|---:|---:|
| Polyglot fixture | 22 | 112 | 0.5 s |
| Flask (with `--docs`) | 355 | 5,868 | **6.0 s** |
| sympy/solvers | 44 | 1,364 | 14.9 s |
| sympy/core | 86 | 3,904 | 20.2 s |
| sympy/physics | 225 | 4,558 | 34.3 s |
| sympy (full) | 2,073 | 40,857 | 714.6 s → **124.2 s** (see below) |

Cost tracks file *density*, not file count: Flask runs 17 ms/file, sympy 338 ms/file, because sympy's files are far larger and denser.

**Superlinearity, measured.** Scanning `core`+`solvers`+`physics` together took 101.7 s against 69.4 s for the sum of the three separately — **1.47× superlinear** on a 3-way merge. The merge produced 3,926 additional cross-directory edges, so the extra work is real; but it means whole-repo cost grows faster than corpus size.

**Correction — the full scan completes.** This section first recorded the full sympy
scan as ">65 min, did not complete," inferring a degradation or threshold effect.
A later cold run (`rm -rf .graphgraph && graphgraph scan --depth symbols`, background,
uncontended machine) **completed in 714.6 s** producing 40,857 nodes and 192,689
edges at `STRUCTURAL PASS`. The original observation was an artifact of a contended,
interrupted run, not a property of the tool, and the "threshold effect" inference
built on it was wrong.

The completed number also **retires the threshold hypothesis on its own arithmetic**:
714.6 s over 2,073 files is 345 ms/file against 195 ms/file for the three subsets
(69.4 s / 355 files) — a 1.8× per-file penalty at 5.8× the corpus. That is the same
mild superlinearity the 3-way merge already showed, extended smoothly to full scale.
Nothing falls off a cliff; the cost model that predicts ~12 minutes is the one that
was measured. **The defect is the constant, not the curve.**

**Crash safety is good:** killing the scan mid-flight left the pre-existing graph valid and intact (`STRUCTURAL PASS`). Atomic write is working.

**Floor:** tree-sitter parses ~1,500 Python files in well under 60 s single-threaded, and the work is embarrassingly parallel across files. A cold full scan of sympy should be **30–60 s**. Measured 714.6 s. Gap: **12–24×** — a real and large defect, but a bounded one, and roughly the same multiple as the 60–300× fluidity gap rather than the unbounded wall previously reported.

**Superseded by `2026-07-31-scan-hot-path-optimization.md`.** Profiling this path
found one accidentally quadratic dedup set and two layers of redundant Python
re-analysis (9,338 `ast.parse` calls for 86 files). Removing them took the same
cold CLI scan to **124.2 s — 5.75× faster — for a byte-identical graph**. The
gap to the 30–60 s floor is now **2–4×**, and gate 5 below passes. The cost was
never structural; it was three fixable defects sitting in the per-definition loop.

**Further reduced to 87.5 s** by
`2026-08-01-retrieval-and-shared-path-optimization.md`: deduping the
literal-blanking walk, then parallelising the Python type-snapshot phase with
worker→parent cache priming. Still byte-identical. Against the 30–60 s floor the
remaining gap is **1.5–3×**.

---

## Finding 5 — Latency structure and the fluidity ceiling

This is the section that speaks to the "snap your fingers" goal. Flask, 5,868-node graph, quiet machine:

| Operation | Wall (p50) | Internal (self-reported) | Overhead |
|---|---:|---:|---:|
| `graphgraph --version` | 131 ms | — | pure process start |
| `relations` (exact 1-hop) | **310 ms** | **83 ms** | 227 ms |
| `query` (natural, warm) | 520 ms | — | — |
| `query` (natural, cold) | 1,804 ms | — | — |
| `status` | 570 ms | — | — |
| 1-file `update`, fixture (112 nodes) | 290 ms | — | — |
| 1-file `update`, Flask (5,868 nodes) | 405 ms | — | — |

Three things follow.

**The incremental-update contract holds.** A 52× larger graph costs 1.4× more for a one-file update. The documented promise — *"cost scales with `--files`, not repo size"* — is substantially true. This is the hard part, and it is done. **Do not touch it.**

**Every invocation pays ~131 ms of Python interpreter start** before any work begins. On the tiny fixture, actual graph work was 1.9 ms against 300 ms wall — **0.6% efficiency, 99.4% overhead.** On Flask it is 83 ms against 310 ms — 27%.

**Floor:** an exact one-hop adjacency lookup on a resident, memory-mapped graph is microseconds of work; with IPC, **1–5 ms**. Current 310 ms is **~60–300× above floor**, and essentially all of the gap is process startup and graph load — not graph algorithms. A resident daemon collapses it. Nothing about the data structures needs to change.

Human "instant" is ~100 ms. Exact lookups at 310 ms are perceptibly slow; cold natural queries at 1.8 s are a visible stall. **The fluidity gap is entirely plumbing, not design.**

---

## Finding 6 — Token efficiency

Query: *"how does Flask dispatch a request from wsgi_app to the view function"*, `--query-class multi_hop_path`.

| | Size |
|---|---:|
| GraphGraph packet | 6,239 chars / **1,672 tokens** (self-reported) |
| `src/flask/app.py` alone | 67,048 chars (~17k tokens) |
| The 4–5 files actually spanning the answer | ~150k chars (~38k tokens) |

**~23× compression against the files an agent would otherwise read** — and the answer is *correct*. The packet contains the complete true dispatch chain: `wsgi_app -> full_dispatch_request -> {preprocess_request, dispatch_request, finalize_request, handle_user_exception}`, and `finalize_request -> process_response`. Verified against Flask source.

The control receipt is excellent and deserves calling out:

```
ggc1 op=multi_hop_path state=answerable next=answer anchor=ranked h=2 dir=both
budget=52 actual=52/143 packet=gg tokens=1672
gates=fresh:+,route:+,anchor:+,evidence:+,semantic:?,packet:+
```

One line, machine-readable, per-gate status, honest `?` on the semantic gate. This is close to the "compact guarantee" the previous report asked for.

**The remaining inefficiency is precision, not volume.** The packet returned 52 nodes where ~8 answer the question; it included `examples/tutorial/flaskr/__init__.py::create_app` and `tests/test_async.py::_async_app`. At 1,672 tokens that is cheap enough to ignore — but the ideal is ~300 tokens, so there is still ~5× of headroom in selectivity.

---

## Scorecard

Scored on this run's evidence. Categories not re-probed are marked and carried forward from the previous board rather than re-asserted.

| Category | Prev | **Now** | Ceiling | Limiter found in this run |
|---|---:|---:|---:|---|
| Instrument honesty / eval harness | — | **9.5** | 10.0 | Passes red test; full calibration decomposition. Only gap: `select` completeness flag |
| Call/dependency topology | 8.5 | **5.0** | 9.9 | Same-file calls lost to global name ambiguity; 54% fixture recall |
| Extraction precision | — | **10.0** | 10.0 | 7/7 decoys clean; drops rather than fabricates |
| Definition extraction & indexing | 8.5 | 8.5 | 10.0 | Not re-probed; all 7 languages indexed with correct lines |
| Exact lookup & packet core | 9.0 | 9.0 | 10.0 | Correct and ~2 ms internally; ambiguity returns candidates, not guesses |
| Natural-language retrieval | 6.5 | **7.5** | 9.9 | Flask multi-hop chain fully correct; packet precision ~15% |
| Incremental freshness | 8.0 | **9.0** | 10.0 | Scaling contract verified: 52× graph → 1.4× cost |
| Abstention & calibration | 7.5 | **7.5** | 9.8 | Good on queries; `caller_evidence_complete` blind spot |
| Build safety & validation | 8.0 | **8.5** | 9.9 | Survived mid-scan kill with graph intact |
| Determinism | — | **8.5** | 10.0 | "Content deterministic" was wrong: 9 edges varied with `PYTHONHASHSEED`, now fixed; 8-byte timestamp drift remains |
| Scan cost at scale | — | **8.0** | 9.5 | sympy full 714.6 s → 87.5 s after hot-path fixes and parallelised snapshots; 1.5–3× above floor, gate 5 passes |
| End-to-end latency / fluidity | 6.5 | **5.5** | 9.9 | 131 ms fixed process cost; 60–300× above floor |
| Token efficiency | 7.0 | **8.0** | 9.9 | 23× compression, correct answer; 5× headroom in selectivity |
| Recursion / cycle modeling | — | **2.0** | 9.5 | 0/7 languages record self-calls |
| Memory / temporal / federation | 4.0 | *not re-tested* | 9.8 | Carried forward, not re-verified |
| Format & transport contract | 9.5 | *not re-tested* | 10.0 | Carried forward; MCP not restarted |

**Weighted assessment: ~6.4/10 today.** Topology caps everything above it — a packet cannot carry an edge that resolution deleted — so the 5.0 in call topology bounds natural-language retrieval, blast radius, and affected-tests regardless of how good those layers are.

**What is already at or near the floor, and should not be touched:**
- Extraction precision (10.0) — never fabricates
- The eval/calibration harness (9.5) — better than most commercial tooling
- Incremental update scaling (9.0) — the genuinely hard part, and it is done
- Exact packet core and the `ggc1` control line

**The shape of this system is a strong design with two specific plumbing defects.** That is a far better position than the inverse, and the score understates it.

---

## Proposed CI gates

Thresholds that can fail, in priority order.

1. **Scope invariance (the single best scalar).** Scan fixture `F`; record total inbound call edges `E`. Add one file that only *defines* symbols already present. Re-scan. **Assert `E_after >= E_before`.** One number, cheap, no contested assumptions, moves the instant the defect is fixed. Currently fails: 197 → 178.
2. **Same-file binding.** In a repo where name `N` is defined in ≥2 files, a call to `N` in the same file as a definition must bind to that definition. Currently fails.
3. **Dead-code honesty.** `select "production_callers = 0"` must set `caller_evidence_complete: false` whenever any call site was dropped for ambiguity. Currently reports `true`.
4. **Self-recursion.** A directly self-recursive function must have itself among its callers, in every advertised language. Currently 0/7.
5. **Cold full scan.** 2,000-file Python repo must complete in **< 180 s**. **Passes:** 87.5 s (sympy, 2,073 files), down from 714.6 s.
6. **Exact-lookup latency.** `relations` p50 **< 50 ms** via a resident service (< 5 ms is the real floor). Currently 310 ms.
7. **Byte determinism.** Two scans of an unchanged tree must produce identical bytes. Currently differs by 8 bytes.

The fixture built for this run is frozen and reusable; gates 1–4 all run against it in under a second.

---

## What if there were virtually no bottlenecks?

The previous report framed this well and it still holds. This run sharpens *where* the remaining distance actually is — and the answer is encouraging: the intelligence is largely built, and the losses are in binding and plumbing.

What if:

- **scope were free.** Resolution never had to choose between "guess" and "discard," because every call site carried its lexical scope chain as a first-class fact — file, module, class, closure — so the nearest binding always won and ambiguity only ever survived when it was genuinely ambiguous in the language itself. Nothing correct would ever be deleted by the arrival of an unrelated file.
- **the graph were never stale, because it was never built.** Extraction happened at edit time, per keystroke-batch, so "scan" stopped existing as a user-visible verb. There is no cold start to optimize if there is no cold start.
- **the process boundary disappeared.** Context lived in a resident, memory-mapped service, so the first hop cost less than a syscall and the 131 ms interpreter tax was paid once per machine-lifetime rather than once per question. Every measured latency in this report collapses by two orders of magnitude without touching a single algorithm.
- **uncertainty were the only thing that cost tokens.** The packet shrank as confidence rose — 8 nodes when the answer is crisp, expanding only around genuine doubt — so being right made answers *smaller*, not longer.
- **completeness were structural rather than asserted.** Every receipt carried the count of evidence it *discarded*, not just what it kept, so "zero callers" and "zero callers found, 3 call sites unresolved" could never be confused. A completeness claim would be arithmetic, not optimism.
- **every named thing in a request became an obligation.** Ask about three repositories, two languages, and last Tuesday, and the answer either covers all six facets or names precisely which one it could not — making quiet omission structurally impossible.
- **one exact fact flowed everywhere it mattered.** Learning `TestRoot -> Root` would immediately improve affected-tests, blast radius, review scope, and the next suggested action, without a second query.
- **recall arrived unasked.** Decisions, dead ends, and unfinished threads surfaced at the moment they became relevant, rather than when someone remembered to search for them.
- **crossing a repository felt like crossing a file,** with provenance always visible and never load-bearing on the user.
- **asking about the past returned the past,** and refused when it could not — never a timestamped present wearing a historical label.
- **the tool left the user's mental model entirely.** No "let me get context first." Just research, judgment, implementation, verification, and forward motion — with the context already there.

The gap to that state is now unusually well-characterized, and it is *narrow in kind if not in effort*: one binding rule (lexical scope beats global name), one architectural move (resident service), one honesty rule (report what was discarded), and one scaling fix (parallel, bounded full scan). Precision, calibration, incremental splicing, and packet design — the parts that are genuinely hard to get right — are already there.

---

## Coverage — what this run did *not* test

Stated explicitly so that silence is not read as a pass:

- Memory, temporal, and federation continuity — **not re-tested**; prior score carried forward
- MCP transport parity — **not tested**; the configured server process was not restarted
- Packet format coverage (10 formats) — **not re-tested**; prior run found 10/10
- Documentation grounding and doc truncation — **not tested** (Flask reported 32 truncated docs; not investigated)
- Delete/rename splice equivalence — **not re-tested**
- Multi-repository queries — **not tested**
- Languages beyond the 7 in the fixture (Ruby, PHP, Kotlin, Scala, Swift, C, C++) — **not tested**
- `graphify` comparison — **not run**; `code-review-graph` was used as the differential control instead

---

## Artifacts created by this run

To remove:

- `<scratchpad>/fx`, `jsprobe`, `p_js`, `p_jssub`, `p_jspy`, `p_jsts`, `c_rename`, `c_jsjs`, `c_pypy`, `c_min`, `c_rec`, `c_scope`, `diffctl`, `flasksrc`, `scale_core`, `scale_solvers`, `scale_physics`, `scale_combined` — all under the session scratchpad, safe to delete wholesale.
- `resources/flask/.graphgraph/` — **regenerated** by this run (a fresh full scan). Previously present.
- `resources/sympy/.graphgraph/` — **untouched**; the interrupted scan did not overwrite it (verified `STRUCTURAL PASS`, 53,483 nodes, mtime 07/21).
- `<scratchpad>/diffctl/.code-review-graph/` — created by the differential control.

The 22-file polyglot fixture is worth promoting into `docs/evaluation/graybox-cycles/fixtures/` as a permanent regression suite: it exercises 7 languages, 9 edge classes, a precision decoy, and gates 1–4 above in under a second.

---

## Recommended next run

1. Fix scope binding; re-run gate 1 and the fixture oracle. Expect 34/63 → ~48/63 immediately.
2. Add self-recursion edges; expect ~55/63.
3. Re-run the Flask `copylib` metamorphic test; assert monotonic.
4. Restart the MCP process and re-verify transport parity against the current build.
5. Re-probe memory, temporal, and federation, which this run deliberately did not touch.
