# Gray-Box Cycle 4 — Differential Re-Test After Updates

**Date:** 2026-07-23 · **Method:** `/graybox` cycle 4, differential oracle (CLI-only; source never read)
**Fixtures:** express (JS), sd-scripts (Py), ripgrep (Rust), flask, tuya-ble-scanner
**Framing:** Re-run every failing probe from cycles 1–3 against the updated build and
measure the delta. Version string is still `0.1.0` and the subcommand list is byte-identical
to cycle 1 — so per graybox discipline, behavior is the only oracle. It moved a lot.

---

## The delta ledger — headline

| Prior finding | Cycle 1–3 | Cycle 4 | Verdict |
|---|---|---|---|
| JS symbol extraction | 86 nodes; `res.send` **invisible** | **2,946 nodes**; `res.send` found @lib/response.js:126 | ✅ **FIXED** |
| Python caller resolution | 0/4 files; 586 resolved | **3/4 files**; 1,770 resolved | ✅ **FIXED** |
| Answerability calibration | wrongly abstained on a full answer | LoRAModule → correctly `answerable` | ✅ **FIXED** |
| Incremental idempotence | rescan #2 = full 13.7s re-extract | rescan #2 = **1.3s**, dirty=0 | ✅ **FIXED** |
| Memory anchoring | `related_nodes: []` | anchored to **4 real symbols** | ✅ **FIXED** |
| Freshness stamp | control gate stuck at `fresh:?` | resolves to **`fresh:+`** | ✅ **FIXED** |
| Eval garbage handling | silent `[]`, exit 0 | **descriptive schema error**, exit 0 | ⚠ **HALF** |
| Update O(Δ) scaling | 1065ms lg vs 396ms sm (2.7×) | 817ms lg vs 386ms sm (2.1×) | ⚠ **IMPROVED** |
| Paraphrase recall | 0% overlap | 0% overlap (still `hash` backend) | ✗ **UNCHANGED** |
| JS call resolution | 0/165 | 0/6278 | ✗ **UNCHANGED** |
| Affected-tests recall | 2/8 files (flask) | 1/8 files | ✗ **STILL POOR** |

**6 outright fixes, 2 partial, 3 still open.** This is the most productive delta of any cycle.

---

## What got fixed (with evidence)

### JS extraction — from cliff to functional
Cycle 3's worst finding. Express: `scan` went from **86 → 2,946 symbol nodes** (2,861
functions, 85 methods). The oracle that was invisible — `res.send = function send(body)` —
is now a first-class node returned by a plain definition query. Property-assignment and
prototype-style method syntax is being captured. The single largest stratum of real-world
code (JS at 0%) is no longer a black hole.

### Python call resolution — tripled
sd-scripts member calls: **586 → 1,770 resolved** (edge count 23,834 → 25,008). The
cycle-1 caller oracle (`load_metadata_from_safetensors`, ground truth 4 files) went from
**0 → 3** of the 4 caller files surfaced (`flux_merge_lora`, `merge_lora`, `sdxl_merge_lora`;
only `svd_merge_lora` still missing). This was cycle 1's single biggest correctness gap —
now mostly closed.

### Answerability calibration — the both-directions bug is gone
Cycle 1's most dangerous instrument defect: the gate said `abstained` over a fully-answered
LoRAModule query and `answerable` over a 0-recall caller query. Now: LoRAModule definition →
`status: answerable, abstained: false` (correct), and the caller query → `status: incomplete,
conf 0.34` (honest, because it found 3 of 4). The gate now tracks recall in the right
direction. This upgrades every downstream number from "must re-verify" toward "bankable."

### Idempotence — no more three-run convergence
Cycle 1: cold scan → immediate rescan re-extracted everything (13.7s), converging only on
run 3. Now rescan #1 and #2 are **both 1.3s with dirty=0**. The hash manifest persists on
first write. The verification-tax of "did my rescan actually no-op?" is gone.

### Memory grew roots — concept #13 partially realized
Cycle 3 flagged `related_nodes: []` on every memory. Now adding *"…search_path refactor must
preserve the Matcher generic; PCRE2 path is risky"* auto-anchors to
`['crates_core_flags_defs_rs__PCRE2', 'crates_core_search_rs__SearchWorker__search_path',
'crates_core_search_rs__search_path', 'crates_searcher_src_searcher_mod_rs__Searcher__search_path']`.
Memory is now *in* the graph, not beside it. This is the spatial-memory concept from cycle 3
shipping — the boldest of the fixes because it's a new capability, not a bug repair.

### Freshness — the gate answers its own question
Cycle 3's `fresh:?` (telemetry that knew it didn't know) now resolves to `fresh:+` on a live
query. The scariest failure mode of a context tool — silently serving a stale world — now has
a working sensor. Concept #12's honest half is in.

---

## What's still open

### F-a · Paraphrase recall still 0% — the one big miss
`"definition of LoRAModule class"` → the lora class nodes. `"where is the class that
implements LoRA modules declared"` → five doc paragraphs, **zero overlap**. Unchanged
because `doctor` still reports `Backend: hash (offline lexical fallback)`. This is now the
**single highest-leverage remaining gap**: everything structural improved, but semantic
recall is still gated behind an unset `$GRAPHGRAPH_EMBED_URL`. A bundled default embedding
model would move this from 2 → 7 in one change.

### F-b · JS call resolution still 0% — symbols without wires
JS symbol extraction is fixed, but member-call resolution is still **0/6278** on express.
The nodes exist now; the edges between them don't. This is the natural next step after the
symbol fix — and exactly the Python fix (which tripled) applied to the JS frontend.

### F-c · Eval still exits 0 on bad input — half a fix
Now prints a genuinely helpful schema error ("expected a JSON list of {\"query\":…}") instead
of a silent `[]`. But **exit code is still 0**. A CI harness wiring `eval` into a gate will
still go green on a malformed task file. One line from done.

### F-d · Update scaling improved but not yet invariant
Large-repo 1-file update 1065 → 817ms; small still 386ms. The ratio narrowed 2.7× → 2.1× but
the documented contract ("cost scales with --files, not repo size") still isn't met. Partial
progress; the O(corpus) load/persist path still dominates.

### F-e · Affected-tests recall still decorative
flask `add_url_rule`: 1 test file surfaced vs 8 ground-truth. This rides on call resolution
reaching into test files, which Python member-call improvements haven't fully propagated to.
Until this clears ~80%, the answer can't replace running the suite.

---

## Re-scored granular scorecard (same 35 items as last rating)

| Section | Item | C3 | C4 | Δ |
|---|---|:--:|:--:|:--:|
| **Extract** | Python symbols | 7 | 7 | |
| | Rust symbols | 8 | 8 | |
| | JS symbols | 1 | **7** | +6 |
| | Python call edges | 3 | **6** | +3 |
| | Rust call edges | 6 | 6 | |
| | JS call edges | 1 | 1 | |
| | Doc extraction | 6 | 6 | |
| | Concept linking | 5 | 5 | |
| **Retrieve** | Literal queries | 8 | 8 | |
| | Paraphrase | 2 | 2 | |
| | Query routing | 8 | 8 | |
| | Blast radius | 3 | 3 | |
| | Affected tests | 2 | 2 | |
| | Null/abstention | 8 | 8 | |
| | Budget monotonicity | 9 | 9 | |
| | Scope/packet controls | 7 | 7 | |
| **Perf** | Cold scan | 7 | 7 | |
| | Incremental rescan | 4 | **8** | +4 |
| | 1-file update | 4 | **5** | +1 |
| | Query latency cold | 5 | 5 | |
| | Query latency cached | 6 | 6 | |
| | Process spawn | 4 | 4 | |
| **Trust** | Answerability calibration | 3 | **6** | +3 |
| | Freshness awareness | 2 | **7** | +5 |
| | Per-language depth honesty | 2 | 2 | |
| | Self-reported telemetry | 9 | 9 | |
| | Telemetry uniformity | 4 | **5** | +1 |
| **Platform** | repair | 8 | 8 | |
| | snippets | 8 | 8 | |
| | memory | 5 | **8** | +3 |
| | time travel | 3 | 3 | |
| | federation | 2 | 2 | |
| | watch/serve | 2 | 2 | |
| | CLI vocabulary | 5 | 5 | |
| | safety guards | 8 | 8 | |

### Section averages
```
Extraction        4.6 → 5.75   (JS symbols + Py calls)
Retrieval         5.9 → 5.9    (flat — the paraphrase/test gaps)
Performance       5.0 → 5.83   (idempotence fixed)
Trust/self-know   4.0 → 5.8    (freshness + calibration)
Platform/workflow 5.1 → 5.5    (memory anchoring)
────────────────────────────────
OVERALL           5.0 → 5.74
```

**Composite: 5.0 → 5.7 / 10.** The bimodal distribution is collapsing inward — items that
were at 1–3 are now clustering at 5–8. The remaining sub-4 items are concentrated and named:
JS call edges (1), paraphrase (2), per-language honesty (2), federation (2), watch/serve (2),
time travel (3), blast radius (3), affected tests (2).

---

## Where the next +1.0 composite comes from

1. **Bundle a default embedding model** (F-a): paraphrase 2→7, blast radius 3→6, semantic
   linking 5→7. Biggest single move — roughly +0.4 composite alone.
2. **JS call resolution** (F-b): apply the Python member-call fix to the JS frontend; JS
   call edges 1→6, affected-tests lifts with it.
3. **Eval exit code + per-language depth stamp** (F-c, concept #11): both cheap, both
   convert "half-honest" into "fully honest."

## Test artifacts

- Rebuilt `.graphgraph/` stores in express, sd-scripts, ripgrep, flask, tuya-ble-scanner.
- One project-scope memory added in ripgrep's store (now correctly anchored).
- mtime bumps on `sd-scripts/library/utils.py`, `tuya-ble-scanner/analyze.py` (touch only).
- No file contents modified.

## Coverage

**Re-tested (differential):** JS/Py/Rust extraction, caller resolution, answerability
calibration, idempotence, update scaling, eval schema handling, memory anchoring, freshness,
paraphrase, affected-tests.
**Still untested:** `platform serve`/`watch`/`trace`/`federate` execution, conversational
`as-of`, `final` policy workflow, Go/Java/C/C++ strata, MCP path.
