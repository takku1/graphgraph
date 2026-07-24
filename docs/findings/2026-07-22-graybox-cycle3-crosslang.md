# Gray-Box Cycle 3 — Cross-Language Truth & The Graph That Knows Itself

**Date:** 2026-07-22 · **Method:** `/graybox` cycle 3 (CLI-only; source never read)
**Fixtures:** `resources/express` (JavaScript, 141 js files) · `resources/ripgrep` (Rust, 101 rs files)
**Framing:** Cycle 1 measured, cycle 2 dreamed. Cycle 3 crosses the language border —
the 15-language claim was never tested — and *executes* the platform stubs cycle 2
only help-probed. Same rule as before: every fantastical concept must be anchored
to an observed friction.

---

## The friction ledger

| Step | Command | Wall | Outcome |
|---|---|---|---|
| Build (express, JS) | `scan` | 1.1s (forced full) | ⚠ 141 files → **86 functions, 0 resolved calls** |
| Build (ripgrep, Rust) | `scan` | 5.8s | ★ 3,939 symbol nodes, 1,210 resolved calls (34% — best seen yet) |
| Oracle: `res.send` definition | `query` | ~1s | **✗ Invisible.** Returned test files matching the *filename* lexically; the real definition (`lib/response.js:126`) absent |
| Oracle: `Searcher::search_path` callers | `query` | ~1s | ★ All 3 definitions + correct caller cluster |
| Memory add | `platform memory add --text …` | — | ✗ Failed — `text` is positional, not a flag |
| Memory search | `platform memory search …` | — | ✗ Failed — verb is `query`, not `search` |
| Memory round-trip (retry) | add → paraphrase `query` | 312ms | ★ Works — but `related_nodes: []` (see F3) |
| Red test on thin graph | semantic question vs JS graph | ~1s | ★ Abstained (conf 0.22), still surfaced the right file |
| First express scan | `scan` | 0.6s | ⚠ Silently restored a **pre-existing stale store** (`dirty=0 restored=213`) with zero staleness indication |

Running tally across all 3 cycles: **5 failed invocations purely from flag vocabulary.**

---

## Findings

### F1 · Extraction quality is a language lottery — the clean-0% stratum
- **Observed:** per-language member-call resolution: Rust **34%** (1210/3542) ·
  Python **~20%** (586/2522, cycle 1) · JavaScript **0%** (0/165 — and only 165
  candidates detected across 141 files).
- **Oracle:** `res.send = function send(body)` — arguably the most-used symbol in
  the JS ecosystem — does not exist in the graph. Express's idioms
  (property-assignment methods, prototype extension, callback functions) are
  invisible; only bare `function` declarations were captured.
- This is not a gradient, it's a cliff: a JS user gets a confidently thin world
  with nothing telling them the world is thin. Rust users get a genuinely good one.
- **Gate:** per-language extraction fixture: express's `res.send`, a prototype
  method, and an `it()` callback must all be nodes.

### F2 · The stale-store trap — freshness is invisible
- **Observed:** first express scan silently restored a pre-existing `.graphgraph/`
  store from some earlier session (`dirty=0 restored=213`, 0.6s) — reported
  results as if current, with **no indication of graph age**. Only forcing
  `--no-incremental` revealed the truth. Notably, the control receipt already
  admits this: the freshness gate prints `fresh:?` — the telemetry *knows it
  doesn't know*.
- **Gate:** every packet carries graph age + source-tree drift check; `fresh:?`
  is never an acceptable steady state.

### F3 · Memory works but has no roots
- **Observed:** memory add → paraphrase recall round-trip in 312ms. But the
  stored record shows `related_nodes: []` despite the text naming `search_path`
  and `PCRE2` — both symbols present in the graph. Memory is a functional notes
  app bolted *beside* the graph, not *into* it.

### F4 · The honesty machinery generalizes — credit
- **Observed:** on the near-empty JS graph, a semantic question abstained with
  low confidence (routing 0.147) instead of hallucinating — and still surfaced
  `lib/response.js` as the right neighborhood. Degradation is graceful.
  Abstention correlating with extraction thinness is exactly the behavior a
  calibrated system should show; here it worked.

### F5 · Time travel is batch, not conversational
- **Observed:** `platform as-of` requires `--output` — it materializes a snapshot
  *file*. You cannot simply ask a question about the past.

---

## The Concepts (extending cycle 2's ten — no repeats)

### 11. Every language a first-class citizen — or at least an honest one
**We have:** a language lottery (34% / 20% / 0%) that the user cannot see.
**If it were:** two things. First, idiom-aware extraction profiles per language —
JS property-assignment and prototype methods are *the* method syntax of that
world, not an edge case. Second — and more fantastical — **the graph measures its
own vision per language** and stamps it on every packet: *"this answer comes from
a language I see at 8% depth — trust accordingly."* Extraction depth as a
self-reported, per-stratum score in `status` and in every control receipt.
**Then:** even before JS extraction is fixed, no one is silently misled — and the
depth score becomes the roadmap that prioritizes which idioms to teach it next.
Exponential effect: the graph starts *requesting its own improvements*.

### 12. The graph knows its own age
**We have:** a store that silently answered from a stale snapshot, and a
freshness gate that honestly prints `?`.
**If it were:** freshness as a *live sense* — every query touches the repo pulse
(HEAD, mtimes) in microseconds, self-invalidates what drifted, and answers carry
a staleness stamp: *"current as of your edit 4 seconds ago."* Combined with
cycle 2's resident nervous system, `fresh:?` becomes `fresh:✓` permanently.
**Then:** the single scariest failure mode of any context tool — confidently
serving yesterday's world — becomes structurally impossible. Trust compounds.

### 13. Memories with roots — spatial memory
**We have:** memories that recall by text match but float free (`related_nodes: []`).
**If it were:** every memory auto-anchors to the symbols it mentions, becoming a
node *in* the graph with edges to `search_path` and `PCRE2`. Then recall becomes
**spatial**: standing at any function, ask *"what did I ever decide near here?"*
and the graph walks 2 hops and hands you the decisions, the regrets, the
dead ends — attached to the terrain, not to a search box.
**Then:** the codebase becomes a memory palace in the literal ancient sense.
Combined with cycle 2's saved-game concept, returning to code you touched months
ago means the code itself remembers you.

### 14. Conversational time travel
**We have:** `as-of` as a batch export to a file.
**If it were:** time as a query dimension — *"who called this last March?"*,
*"show me this subsystem before the refactor"* — answered inline, with the
temporal diff as part of the packet.
**Then:** merged with cycle 2's narrated diffs (#4), the graph stops being a
snapshot and becomes a *timeline you stand inside*.

### 15. The single verb
**We have:** 5 failed invocations across 3 cycles from guessing flags
(`--labels`/`--starts`, `--text`/positional, `search`/`query`).
**If it were:** `graphgraph do "<anything>"` — one verb, the router (which has
been flawless at query classification all 3 cycles) owns the entire surface,
including platform subcommands. The 27-subcommand CLI remains for scripts;
humans and agents get one word.
**Then:** the last knowledge-friction disappears. Nobody ever reads `--help`
again — which, given this tool's help is actually *good*, is the highest
compliment a CLI can earn.

---

## The composite fantasy, cycle 3 edition

Cycle 2's throughline was *zero wait states*. Cycle 3's is **calibrated
self-knowledge**: a graph that knows how well it sees each language (11), knows
how old its knowledge is (12), knows what you decided and *where* (13), knows
what the code used to be (14), and needs one word to be asked anything (15).

> The lightning-speed loop only stays lightning when you never have to wonder
> whether the graph is wrong. Cycle 2 removed the waiting; cycle 3 removes the
> doubting. A tool you neither wait for nor doubt is not a tool anymore —
> it's a sense.

## Rating deltas from cycle 1's scorecard

- **Call-graph extraction 3/10 → split by stratum:** Rust 6, Python 3, JS 1.
  Composite unchanged (~3) but now correctly attributed — the fix is per-language
  idiom work, not one global algorithm.
- **Instrument honesty 8/10 → 8.5:** graceful abstention on the thin graph (F4)
  and the honest `fresh:?` gate deserve credit even while F2's silent staleness
  costs it a point.
- **New unrated axis surfaced: self-knowledge** (extraction depth, freshness,
  memory anchoring) — today ~2/10, and it is the axis concepts 11–13 live on.

## Priority handoff to the implementing agent

1. **JS idiom extraction** (F1) — largest single stratum of real-world code at 0%.
2. **Per-language depth score in receipts** (concept 11's honest half) — cheap,
   uses existing member-call accounting, kills the silent-thinness trap.
3. **Freshness stamp** (concept 12) — the `fresh:?` gate already exists; make it
   answer its own question.
4. **Memory auto-anchoring** (concept 13) — symbol names are already in the graph;
   the join at `memory add` time is small, the payoff is a new product.

## Test artifacts

- `resources/ripgrep/.graphgraph/` created; `resources/express/.graphgraph/`
  rebuilt (a stale store pre-existed this session).
- One project-scope memory record added (id `ede72fede62d35e7`) in ripgrep's
  store — remove via the memory store if unwanted.
- No file contents modified.

## Coverage

**Newly exercised:** JS + Rust extraction, cross-language oracles, `platform
memory` (add/query round-trip), thin-graph red test, stale-store behavior,
`plan`/`final` help surfaces.
**Still untested:** `platform serve`/`watch`/`trace`/`federate` execution,
`as-of` with real timestamps, `final` policy workflow, Go/Java/C/C++ strata,
the MCP path.

---

## Implementation follow-through — 2026-07-23

The observations above remain the immutable gray-box snapshot; the following
records what changed after the report:

- The four-item priority handoff is implemented and regression-tested:
  JavaScript assignment/prototype/callback definitions (including exact
  `res.send`), per-language receiver telemetry, source-root/hash/time freshness,
  and bounded memory auto-anchoring with `remembers` edges.
- The next cross-language receiver slice is also implemented: C++ class/struct
  specifiers now create owner nodes, inline methods are owned, and nominal
  class-depth fields resolve bare/`this->` receivers. The former
  `Repo repo_; run() -> repo_.save()` blocker is now a positive call-edge test.
- Broad architecture questions now receive a deterministic path+PageRank
  subsystem map in structured retrieval metadata. This is intentionally
  optimized for an agent consumer; no model-generated narrative enters the hot
  path.
- Incremental validated update/remove now use the measured append-delta store
  when its cost gate wins, with source-location edge identity, metadata replay,
  cache invalidation, compaction/full-rewrite fallback, and composed-update
  tests.

Repository-wide tests and Ruff pass after these changes. Real repository-scale
Java/C#/C++ and embedding-backed Flask measurements remain input-gated; the
synthetic receiver fixtures prove the extraction contracts, not ecosystem-wide
recall.
