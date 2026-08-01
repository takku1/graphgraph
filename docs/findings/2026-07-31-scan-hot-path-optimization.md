# The scan hot path: one quadratic, two redundancies, and a determinism bug

**Date:** 2026-07-31
**Method:** `cProfile` over `graphgraph scan --depth symbols`, with every change
gated on a canonical, timestamp-free dump of the resulting graph (sorted nodes
and edges, including confidence, provenance, source location and evidence).
Byte-identical output was the acceptance condition, not a nice-to-have.
**Companion:** `2026-07-31-critical-graybox-scope-resolution.md`, whose Finding 4
recorded scan cost as the largest open defect.

---

## Result

| Corpus | Files | Before | After | Speedup |
|---|---:|---:|---:|---:|
| sympy (full) | 2,073 | 714.6 s | **124.2 s** | **5.75×** |
| sympy/core | 86 | 19.43 s | **8.23 s** | 2.36× |
| graphgraph `src` | 183 | 9.63 s | **5.83 s** | 1.65× |
| polyglot fixture | 22 | 0.17 s | **0.12 s** | 1.4× |

The sympy figures are the same `graphgraph scan --depth symbols` CLI path on the
same tree, both cold (`rm -rf .graphgraph`), so serialization is included on both
sides; an in-process scan measured 123.6 s, confirming that writing the 19.5 MB
graph is not where the time goes.

That scan produced **40,857 nodes and 192,689 edges, identical to the
pre-optimization run**, with identical member-call telemetry
(`resolved=13196 ambiguous=12 unknown_receiver=23116`). 1,583 Python files
resolved to exactly the same graph — the strongest correctness evidence
available at scale.

This clears gate 5 of the predecessor report ("a 2,000-file Python repo must
complete in **< 180 s**"), which that report recorded as failing.

Node and edge counts are unchanged on every corpus, and the sympy/core graph is
**byte-identical** before and after the two caching changes. Peak memory fell as
well: 607 MB to 573 MB on a 692-file tree, because the cache that was worth
enlarging is not the one that holds memory.

---

## What was actually wrong

**A quadratic dedup set.** `_add_tree_sitter_calls` rebuilt
`{(e.source, e.target, e.type) for e in edges}` once per definition, over a list
that grows throughout the scan: 2,252 rebuilds against 12,000+ edges on
sympy/core, 11% of total scan time. It is now maintained incrementally.

The subtlety is who appends. Edges arrive from three sites in that function and
from `_resolve_member_call` in another module, so a set updated at known append
sites would silently drift. Instead the set catches up on whatever arrived since
it last looked, which is correct regardless of who appended and costs O(total
edges) for the whole scan.

**Re-parsing the same text.** Every Python analysis helper parsed the text it was
handed. 86 files produced **9,338 `ast.parse` calls** — about 109 per file — and
`compile` alone was 20% of scan time. Parsing is a pure function of the text, so
one cache in front of it removed the repetition without touching any caller.

**Re-walking the same module.** Caching the parse still left three whole-module
analyses walking the same tree once per caller, three times per file, which
dominated what remained (1.1M `ast.walk` node visits). Those analyses are pure in
their arguments, so their results are memoized too.

---

## The determinism bug the gate caught

Before trusting the byte-identical gate, the harness was run twice on unchanged
code to confirm it was stable. It was not: **9 edges differed between runs.**

`_python_attribute_uses` returns a `set`, and the dedup key that consumes it
ignores both the receiver and the line number. When one attribute is reached from
several places, the surviving edge was whichever tuple set iteration happened to
yield first — which depends on `PYTHONHASHSEED`, and therefore varies per
process. It moved the recorded *receiver* as well as the line, so the same edge
was attributed to `a:A.prop` in one run and `b:A.prop` in the next.

Ordering the uses by line makes the genuinely earliest occurrence win, so
`source_location` and `evidence` now describe the same place. Verified identical
across `PYTHONHASHSEED` 0, 1, 7 and 999.

This is a second determinism defect, distinct from the 8-byte timestamp drift
already recorded. It was invisible to the test suite, and it would have been
invisible here too: had the instrument not been checked against itself first, the
9 edges would have been quietly attributed to the optimization work.

---

## Sizing the caches, by measurement

The two cache bounds are different kinds of number, which is why one wants to be
large and the other small.

**The analysis bound is a working-set requirement.** The scan makes several
passes over every file, so a cache smaller than the corpus evicts each module
before the next pass reaches it. The threshold is sharp and tracks the file
count, not any absolute size — on a 692-file tree:

| parse | analysis | seconds | peak MB |
|---:|---:|---:|---:|
| 128 | 128 | 105.8 | 601 |
| 512 | 512 | 104.5 | 742 |
| 128 | 1024 | 80.0 | 607 |
| 128 | 65536 | 80.0 | 607 |
| 16 | 65536 | 78.2 | 574 |

`(512, 512)` is slow and expensive: 512 exceeds neither the 692-file corpus nor
anything else useful. The first sweep for this was run on a 183-file corpus and
showed **nothing**, because every candidate size already exceeded it — the cliff
is only visible from a corpus larger than the cache.

**Raising that bound is free.** It is a ceiling, not an allocation: the cache
never holds more entries than the corpus has files, and its keys are the same
source strings the scan already keeps alive. 4096 to 65536 moved peak memory not
at all (607.4 MB either way). A bound beyond any realistic corpus therefore buys
exactly what deriving it from the file count would, without the plumbing.

**The parse bound is a real memory ceiling**, and once analysis results are
cached it buys almost nothing — 8 to 128 cost 34 MB for no reliable time gain,
because the remaining body parses are reused only locally. It is set to 16.

---

## Not claimed

- **`src` is not a clean before/after.** That corpus is graphgraph's own source,
  which this work modified; its symbol count moved from 1,725 to 1,728.
- **No corpus above 4,096 files was scanned.** The eviction cliff is demonstrated
  at 692 files and argued to generalize; the 65,536 bound is not empirically
  exercised at that scale.
- **`_python_body_nodes` and the tree-sitter walks were left alone.** They remain
  the largest cost after these changes.
- **Only the Python frontend was optimized.** The other languages share the
  tree-sitter path but not these helpers.
