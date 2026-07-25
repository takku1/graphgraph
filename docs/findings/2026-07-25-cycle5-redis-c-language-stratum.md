# Cycle 5 — Bigger Cycle: redis (C) as a New Language Stratum

**Date:** 2026-07-25
**Target:** `redis` — chosen fresh (not a prior fixture) to add **C** to the language strata
(previously Python / JavaScript / Rust) and to test whether every finding generalizes to a large,
unfamiliar systems codebase. C stresses extraction differently: free functions, heavy macros, no
methods or classes, and a mixed repo (redis ships Python test modules).
**Method:** Gray-box. Clean cold fixture (1811 files, `.git`/`.graphgraph` excluded) so all timings
and extraction telemetry are uncontaminated. GraphGraph source and git history never read. Ground
truth derived by reading redis source.
**Build:** 325 source files → **7,406 nodes / 24,862 edges in 12.8 s** (`graphgraph 0.1.0`).

---

## Headline: C is the tool's *strongest* language for call extraction

The single most important result of this cycle. Adding C completes a four-language picture that
tells a clear causal story — and inverts the JavaScript finding from earlier cycles.

| Language | `calls_per_symbol` (CI scalar) | member-call resolution | eval recall | mean MRR |
|---|---|---|---|---|
| **C (redis)** | **2.06** | n/a (direct calls) | **7/8** | **0.578** |
| Python (requests) | 0.90 | 46.8% | 6/6 | 0.889 |
| Rust (ripgrep) | 0.74 | 34.2% | 2/6 | **0.022** |
| JavaScript (express) | **0.10** | 2.2% | 4/6 | 0.389 |

C posts the **highest `calls_per_symbol` of any language measured** (2.06, with 12,920 `calls`
edges on 6,272 symbol nodes). The reason is structural: C calls are direct, textual function-name
references with no receiver and no method dispatch, so there is nothing for the extractor to fail to
resolve. The `member_calls` metric (96 resolved / 0 ambiguous / 26 unknown-receiver / 848
external) barely applies — C simply doesn't have the receiver-binding problem that sinks JavaScript.

**The floor scalar works as a language-health gauge.** `calls_per_symbol ≥ 0.5` — the CI gate I
nominated in cycle 2 — correctly passes C (2.06), Python (0.90), Rust (0.74) and correctly fails JS
(0.10). One free number, emitted by `graphgraph profile`, now validated across four languages.

---

## The refined causal model: extraction and ranking are *separate* failures

The four-language spread finally separates two things that looked like one problem in earlier
cycles. **Extraction quality does not fully predict ranking quality:**

- **JavaScript** fails at *extraction* (0.10). No ranking fix can help — the call edges don't exist.
- **Rust** extracts *fine* (0.74, better than Python's… no, comparable to Python) yet ranks
  *catastrophically* (MRR 0.022). Here the edges exist; anchoring/ranking simply doesn't surface
  them. This is a pure ranking failure, unrelated to extraction.
- **C and Python** get both right and score well.

```
              extraction good?      ranking good?      result
   C              YES (2.06)           YES              7/8, MRR 0.578
   Python         YES (0.90)           YES              6/6, MRR 0.889
   Rust           YES (0.74)           NO               2/6, MRR 0.022  ← ranking-only failure
   JS             NO  (0.10)           n/a              4/6, MRR 0.389  ← extraction failure
```

**Consequence for the roadmap:** fixing extraction (JS) and fixing ranking (Rust) are *independent*
work items with *different* root causes. Rust is the cleanest possible test case for the ranking
subsystem in isolation, because its extraction is not the bottleneck. If a ranking improvement lands,
**Rust MRR is the number to watch** — it has the most headroom (0.022 against a ~0.5 floor) with no
extraction confound.

---

## C retrieved 7/8 on *pure lexical* — semantics were never invoked

A surprising and clarifying result. redis built **no persistent semantic index** (`.graphgraph/`
contains only `graph.gg`, its manifest, and `kv_cache.json` — no `semantic.json`), and the query
receipt confirms semantics contributed nothing:

```
retrieval.sources: mode=auto  sources=<empty>  semantic_seeds=0  semantic_rebuilt=False
                   lexical_strength=12.21
```

Yet recall was 7/8. **C's distinctive identifiers (`rdbSave`, `aeProcessEvents`, `dictAdd`) make
lexical retrieval sufficient on their own.** This reframes the per-language differences: some of the
gap between languages is really a gap in how well *lexical* matching works per language, independent
of the semantic layer. It also means the semantic index — which costs 10–13× the graph size when it
does build (measured in earlier cycles) — may be low-value for identifier-rich languages like C.

### But the `semantic` gate lied about it (silent degradation, 2nd repo)

Despite `semantic_seeds=0`, an empty `sources`, and no index on disk, the control receipt reported:

```
gates=fresh:+,route:-,anchor:+,evidence:-,semantic:+,packet:+
```

`semantic:+` while semantic retrieval demonstrably did not run. This confirms the Gate-5 finding
(silent semantic degradation) on a **second** repo — earlier it was sympy (40k nodes, no index,
`semantic:+`); now redis independently reproduces it. The `semantic` gate is decorative: it does not
report whether the semantic path actually contributed.

### Credit: the `fresh` gate *does* work

Worth stating plainly, because most gate news is negative: `fresh:+` appeared here on the
just-built redis graph, versus `fresh:-` on my stale frozen graphs in prior cycles. So **one gate
varies correctly with reality.** The machinery for meaningful gates exists; it's `semantic`,
`evidence`, `route`, and `anchor` that are stuck, not the whole system.

---

## What generalized to a fresh, unfamiliar repo (all confirmed)

Everything tested on redis reproduced the cross-cycle findings — these are not fixture artifacts:

| Finding | On redis |
|---|---|
| Trust signals constant | `abstained=True`, `actionable.status=incomplete`, `routing.confidence=0.147` — identical to the other three repos |
| Loop-closure stubbed | `actionable.tests.commands` count = **0** (empty) |
| ID chaining works | `query → change_point id (src_rdb_c__backgroundSaveDoneHandlerDisk) → snippets --starts` resolved to `src/rdb.c:4527`, no re-search |
| `--max-nodes` fix holds | `--max-nodes 30 → budget 30`, `200 → 200` (monotone) |
| `update` size-invariance | 1-file update on redis = **300 ms** (in-band with requests 303 / sympy 288) |
| Instrument (`eval`) honest | red test passed: nonsense → recall 0 + `unanswerable` + 0 nodes; real path → recall 1 |

---

## A false alarm I caught before reporting it

Cold-scan telemetry showed `method=211  class=53` among the top kinds — anomalous for pure C, which
has neither. Before writing it up as a misclassification bug, I checked:

```
select kind=class  → VectorData  (class) modules/vector-sets/test.py:40
select kind=method → find_k_nearest (method) modules/vector-sets/test.py:44
```

They are **real Python classes/methods** from redis's `modules/vector-sets/` test suite. The
extractor correctly handled a mixed-language repo and classified the C as functions/structs and the
Python as classes/methods. **Not a bug** — and a reminder that a striking number deserves a second,
independent derivation before it becomes a finding (Phase 4 discipline; it would have been a false
finding otherwise).

---

## Residual gaps visible even in the strong-C case

C's good aggregate hides two failures that match the tool's known ranking weakness:

- **`expire.c` miss (recall 0).** `"how are keys expired when their TTL passes"` returned 0 relevant
  nodes. Verified real, not a path artifact: `select "path contains src/expire.c" --mode count` = 25
  nodes exist; none reached the 33-node packet. Anchor-selection miss.
- **Sorted-set ranked-out (MRR 0.026).** `"how are sorted set operations implemented"` had recall 1
  but the `t_zset.c` answer sat at ~rank 38 of 48. Same ranking failure mode as Rust, milder.

So even on the tool's best language, ~2 of 8 queries hit the anchoring/ranking wall. Ranking is the
universal ceiling — it caps every language, just least severely where lexical matching is strong.

---

## Performance on a larger fresh build (no regressions)

| metric | redis (C, 7406 nodes) | note |
|---|---|---|
| Cold scan | 12.8 s / 325 src files | ~39 ms/file — ~3× slower/file than Python (requests ~12 ms/file); C header parsing is heavier |
| Query latency (warm) | 737 ms | higher than requests' 371 ms; larger graph, lexical scan over 6.3k symbols |
| 1-file `update` | 300 ms | at the floor, size-invariant — unchanged |
| `--max-nodes` monotonicity | holds | fix from cycle 2 stable on new repo |

Cold scan cost scales with source-file count and C parse weight, as expected. Nothing regressed.

---

## Where this leaves the score: still 7/10

This cycle added a language and a sharper model but did not move the caps:

- **Extraction** is now known to be excellent for C, good for Python/Rust, broken for JS — a
  language-shaped problem, not a global one. The one broken language still caps that layer at ~2.
- **Ranking** is proven (via Rust) to be a *separate* failure from extraction, and it caps every
  language — including C, where it still cost 2/8 queries.
- **Trust signals** are confirmed constant on a fourth repo; `semantic:+` confirmed decorative on a
  second. An agent still cannot triage output and must re-verify.
- **The floor holds everywhere** — `update` invariance, ID chaining, honest `eval`, the `--max-nodes`
  fix, and now a demonstrably-working `fresh` gate.

The tool remains a **brilliant foundation with unfinished retrieval and unusable trust signals.**
C being its strongest language is genuinely good news: it shows the extraction→ranking→trust pipeline
produces excellent results *when extraction and ranking both land*. The work is to make that the
common case, not the C-and-Python case.

---

## Nominated gates after cycle 5 (updated)

1. `calls_per_symbol ≥ 0.5` per language — **now validated across 4 languages** (fails only JS).
2. mean MRR ≥ 0.4 per language — **use Rust as the isolated ranking testbed** (0.022, extraction not
   a confound).
3. `semantic` gate must report `-` when `semantic_seeds = 0` — fails today on redis and sympy.
4. `eval --calibration` resolution > 0.10 — still 0.022 (unchanged).

## Coverage / artifacts
Exercised on redis: cold scan, `profile`, `eval` (+red test), `query --json` (sources/actionable/
routing/answerability), `select`, `snippets --starts`, `update`, `--show-stats`, `--max-nodes`.
Not exercised: `plan/render/final`, memory, federation, MCP surface, `graph_at_time`, `platform`,
`--history`. Single machine, Windows 11, Python 3.12, n=3 timings, warm except cold scan.
**Artifacts created:** clean redis fixture at `scratchpad/fx/redis` (~25 MB) + its `.graphgraph`
(no semantic index) — session-scoped, safe to delete. `resources/flask/.graphgraph/semantic.json`
(22.8 MB) from an earlier cycle still present. No `resources/` source modified.
