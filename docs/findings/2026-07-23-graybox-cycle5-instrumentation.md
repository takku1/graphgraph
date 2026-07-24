# Gray-Box Cycle 5 — The Honesty Instrumentation Cycle

**Date:** 2026-07-23 · **Method:** `/graybox` cycle 5, differential oracle (CLI-only; source never read)
**Fixtures:** express (JS), sd-scripts (Py), flask (Py), tuya-ble-scanner
**Framing:** Re-test cycle 4's three open items (paraphrase/embeddings, JS call edges, eval
exit) and sweep for new capability. Verdict up front: **this was a small, honest cycle** —
core capability barely moved, but the graph gained a real new sense of *self-knowledge*.

---

## The delta ledger

| Item | Cycle 4 | Cycle 5 | Verdict |
|---|---|---|---|
| **Unresolved-receiver diagnostics** | absent | **new: breakdown by shape + coverage/trust labels** | ✅ **NEW** |
| JS call resolution | 0/6278 | **143 resolved** | ⚠ tiny gain |
| Paraphrase recall | 0% (hash backend) | 0% (still `hash`) | ✗ unchanged |
| Eval exit code on garbage | descriptive error, exit 0 | descriptive error, **exit 0** | ✗ unchanged |
| Update O(Δ) scaling | 817ms lg / 386ms sm | 765ms lg | ⚠ marginal |
| Affected-tests recall | 1/8 (flask) | 1/8 | ✗ unchanged |

**1 new capability, 2 marginal gains, 3 still flat.** After cycle 4's six fixes, this is the
mopping-up-plus-instrumentation cycle.

---

## The headline: the graph now reports *why* it can't see

Cycle 3 asked (concept #11) for the graph to "measure its own vision and stamp it on output."
The honest half of that has partially landed. `status` and the member-call telemetry now emit:

```
Member calls: resolved=327 ... (external_resolved=1118 unmatched=112)
              scope=full_scan_snapshot  trust=high  coverage=partial
  !  WARNING: 855 member-call sites lack receiver evidence and are excluded from topology
  Unresolved receivers by shape: named_local=639  complex_expression=155
                                 short_local=26  call_result=20  field_chain=15
Concept linking: linked=351/1516 coverage=23.15% ... health=partial
  !  semantic links are usable but do not cover most eligible source nodes
```

This is a genuine advance in the tool's most valuable trait — self-honesty:
- **`trust=high coverage=partial`** — a two-axis quality label on the topology.
- **Unresolved-by-shape histogram** — the graph now tells you *what kind* of call it can't
  resolve (`named_local=639` dominates). That is a self-generated bug backlog: it names the
  639-case pattern that, if taught, would move resolution most.
- **Explicit exclusion warning** — "855 sites … excluded from topology" replaces silent
  absence with a stated caveat. A consumer now knows the call graph is a lower bound.

Per the graybox prime directive, a system that volunteers *where its own model is incomplete*
is doing the single most useful thing an instrument can do. This is the honest half of
concept #11 shipping — the depth score isn't per-*language* yet, but it is now per-*shape*
and per-*subsystem*, which is arguably more actionable.

---

## What's still open (the same three, now well-characterized)

### F-a · Paraphrase recall still 0% — the dominant remaining gap
`doctor` still reports `Backend: hash (offline lexical fallback — no paraphrase recall)`.
Literal `"definition of LoRAModule class"` → the lora class nodes; paraphrase `"where is the
class that implements LoRA modules declared"` → doc paragraphs, zero overlap. Unchanged across
all five cycles. **This is now conspicuously the one big lever nobody has pulled** — every
structural weakness has been improved while semantic recall sits behind an unset
`$GRAPHGRAPH_EMBED_URL`. A bundled default model remains the highest-leverage single change.

### F-b · JS call resolution: non-zero but still ~2%
0 → 143 resolved is progress (the wiring exists now), but 6,246 of ~6,400 JS member calls
are still `unknown_receiver`. The cycle-5 shape histogram explains why: JS is dominated by
`named_local` and `complex_expression` receivers that the resolver doesn't yet chase. The
symbols are all there (cycle 4 fixed that); the edges between them are ~2% populated.

### F-c · Eval still exits 0 — the stubborn one-liner
Three cycles running: the error *message* is excellent, the *exit code* is still 0. Any CI
gate wrapping `eval` still goes green on a malformed task file. This is the cheapest unshipped
fix in the whole tool.

### F-d · Affected-tests still 1/8
flask `add_url_rule` surfaces one test file vs 8 ground-truth. This is downstream of F-b/call
resolution reaching into test files — it will not clear until member-call coverage on test
harness code improves. The new `coverage=partial` label at least now makes the shortfall
*visible* rather than implied.

---

## Re-scored deltas (same 35-item scorecard)

| Section | Item | C4 | C5 | Δ |
|---|---|:--:|:--:|:--:|
| Extraction | JS call edges | 1 | 2 | +1 |
| Trust | Per-language/shape depth honesty | 2 | **5** | +3 |
| Trust | Telemetry uniformity | 5 | 6 | +1 |

Everything else unchanged from cycle 4.

### Section averages
```
Extraction        5.75 → 5.88   (JS call edges non-zero)
Retrieval         5.9  → 5.9     (flat)
Performance       5.83 → 5.83    (flat)
Trust/self-know   5.8  → 6.6     (shape diagnostics + coverage labels)
Platform/workflow 5.5  → 5.5     (flat)
────────────────────────────────
OVERALL           5.74 → 5.9
```

**Composite: 5.7 → 5.9 / 10.** A modest but real tick, concentrated entirely in the
self-knowledge dimension — which, given that untrustworthy output is the thing that forces
re-verification, punches above its raw weight.

---

## Trajectory across five cycles

```
Cycle 1   5.5   (baseline measure)
Cycle 3   5.0   (cross-language exposed the JS cliff → honest downgrade)
Cycle 4   5.7   (six fixes: JS symbols, Py callers, calibration, idempotence, memory, freshness)
Cycle 5   5.9   (self-knowledge instrumentation)
```

The shape of the progress is telling: cycle 4 fixed *capabilities*, cycle 5 fixed *honesty
about remaining capability gaps*. That's a healthy order — a tool that knows exactly what it
can't do is in a far better position than one that's silently wrong. The bimodal 1–3 cluster
is now almost gone; the remaining sub-4 items are **paraphrase (2), JS call edges (2),
federation (2), watch/serve (2)** — a short, named list.

## Where the next full point lives (unchanged from cycle 4 — because nobody pulled it yet)

1. **Bundle a default embedding model** (F-a) — paraphrase 2→7, blast radius 3→6, concept
   linking 5→7. Still the biggest single move on the board, ~+0.4 composite alone.
2. **Chase `named_local`/`complex_expression` receivers** (F-b) — the graph's own new
   histogram says this is where 80% of unresolved JS calls live.
3. **`eval` nonzero exit** (F-c) — one line, unships a CI footgun.

## Test artifacts

- Rebuilt `.graphgraph/` stores in express, sd-scripts, flask, tuya-ble-scanner.
- mtime bump on `sd-scripts/library/utils.py` (touch only). No file contents modified.

## Coverage

**Re-tested:** JS/Py call resolution, paraphrase, eval schema+exit, update scaling,
affected-tests, `status` telemetry, `compare` surface.
**Still untested:** `platform serve`/`watch`/`trace`/`federate` execution, conversational
`as-of`, `final` policy workflow, real embedding backend (would require setting EMBED_URL),
Go/Java/C/C++ strata, MCP path.
