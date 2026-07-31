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

## Result after the file-local scope fix

File-local definitions now bind before repository-wide uniqueness
(`scanner/frontends/edges.py`, resolution step 3). Re-measured on this fixture:

| | At freezing | After fix |
|---|---:|---:|
| Symbol-pass call edges | 157 | **171** (+14) |
| Inbound edges to any `helper::Middle` | 0 | **0** (all 7 languages) |

Recall moves 34/63 -> 48/63 as predicted; precision is unchanged at 7/7. Gates 1
and 2 below now pass. Gate 4 (self-recursion) still fails **by construction**:
`tgt_id == src_id` is an explicit guard in the resolver, not an oversight, so
edge 7 requires a deliberate decision about self-loops rather than a fix.

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
