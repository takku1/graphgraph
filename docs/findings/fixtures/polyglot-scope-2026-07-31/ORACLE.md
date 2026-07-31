# Polyglot scope fixture — oracle

Frozen 2026-07-31. Companion to `../../2026-07-31-critical-graybox-scope-resolution.md`.

22 files, 7 languages. All expected edges are true **by construction**, not by observation.

## Per language: 9 expected `calls` edges

| # | Edge | Exercises |
|---|---|---|
| 1 | `Root -> Middle` | same-file call, name duplicated in `helper` |
| 2 | `Root -> Bonus` | same-file call, globally unique name |
| 3 | `Root -> Assist` | cross-file call via import |
| 4 | `Root -> Engine.Run` | member call on an instance |
| 5 | `Middle -> Leaf` | same-file call |
| 6 | `Engine.Run -> Leaf` | method to free function |
| 7 | `Recurse -> Recurse` | direct self-recursion |
| 8 | `Assist -> Support` | same-file call inside `helper` |
| 9 | `TestRoot -> Root` | test to production, cross-file |

7 languages x 9 = **63 true call edges.**

Go note: Go's single-package rule forbids two `Middle` in one package, so core's is named
`CoreMiddle`. Go is therefore the **control** — edge 1 has a globally unique callee there.

## Precision oracle

Each `helper` file defines `Middle()`, which **nothing calls**. Any inbound `calls` edge to a
`helper::Middle` is a false positive. Expected inbound: **0, in all 7 languages.**

## Result at time of freezing (graphgraph 0.1.0)

Recall **34/63 (54%)**. Precision **7/7 (100%)** — no false edges.

| Language | Found | Missing |
|---|---:|---|
| Python | 7/9 | edge 1 (collision), edge 7 |
| Go | 7/9 | edge 4, edge 7 |
| C# | 7/9 | edge 1, edge 7 |
| Java | 7/9 | edge 1, edge 7 |
| Rust | 6/9 | edges 1, 4, 7 |
| JavaScript | 0/9 | all — collapses when TS twin present; **7/9 in isolation** |
| TypeScript | 0/9 | all — same; **7/9 in isolation** |

## Result after the nearest-scope fixes

Resolution now applies one rule at three levels -- **the nearest binding scope
wins** -- which is the visibility ordering that scope-graph name resolution
prescribes (Neron/Tolmach/Visser/Wachsmuth 2015; GitHub's stack graphs).

| Scope layer | Rule |
|---|---|
| Enclosing class | An unqualified call binds to a sibling member (C#/Java/C++ only) |
| File | A bare call binds to a definition in its own file |
| Module | An import binds to the *nearest* same-basename module, not "any" |
| Repository | Fall back to a globally unique name |

Ties at any level still return no edge, which preserves the extractor's
never-fabricate property.

Counted by enumerating callee edges per language, not inferred from edge totals:

| | At freezing | After fix |
|---|---:|---:|
| Call edges recovered | 34/63 | **52/63** |
| ... excluding deliberate self-recursion | 34/56 | **52/56** |
| Inbound edges to any `helper::Middle` | 0/7 | **0/7** |

Per language (of 9): C# 8, Java 8, Python 8, JavaScript 7, TypeScript 7, Go 7,
Rust 7. The four non-recursion misses are all `Root -> Engine.Run`, a member
call on an instance in Go/Rust/JS/TS, which needs receiver type inference rather
than scope resolution -- and the scan telemetry predicts them exactly
(`member_calls=9/2/2/0`).

Gate 1 verified on real Flask: adding a duplicate `helpers.py` moved inbound
call edges 151 -> 152. The same measurement on the previous commit gave
151 -> 140, independently reproducing the reported -11.

Gate 4 (self-recursion) still fails **by construction**: `tgt_id == src_id` is
an explicit guard in the resolver, not an oversight, so edge 7 requires a
deliberate decision about self-loops rather than a fix.

## Minimal repros

`_repro_scope/` — `a.py` defines `Support` and calls it from `Assist`; `b.py` only *defines* an
unrelated `Support`; `c.py` imports and calls it.
Ground truth: `a.py::Support` has **2** callers.
Observed: only `c.py::Imported` (the import). The same-file caller is dropped.
Scanning `a.py` alone recovers the edge — deleting `b.py` "fixes" it.

`_repro_recursion/` — `Fact` is directly self-recursive and called once by `Caller`.
Ground truth: **2** callers. Observed: **1**.

## Gates this fixture supports

1. **Scope invariance** — total inbound edges must not decrease when a file that only defines
   existing names is added.
2. **Same-file binding** — edge 1 must resolve in all 7 languages.
3. **Dead-code honesty** — `select "production_callers = 0"` must not report
   `caller_evidence_complete: true` while any call site was dropped for ambiguity.
4. **Self-recursion** — edge 7 must resolve in all 7 languages.

All four run in under a second: `graphgraph scan --depth symbols` then
`graphgraph select "kind=function" --json`.
