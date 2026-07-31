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

A fourth layer was added with receiver typing, so a member call binds to the
method owned by the receiver's own type:

| Scope layer | Rule |
|---|---|
| Receiver type | `e.Run()` binds to the class the receiver was built from, same file first |

Counted by enumerating callee edges per language, not inferred from edge totals:

| | At freezing | After scope fixes | After receiver typing | After recursion |
|---|---:|---:|---:|---:|
| Call edges recovered | 34/63 | 52/63 | 56/63 | **63/63** |
| Inbound edges to any `helper::Middle` | 0/7 | 0/7 | 0/7 | **0/7** |

**All nine edge classes now resolve in all seven languages, with no false
edges.** Counts use `--include-tests`, since edge 9 crosses from a test file.

Every language now resolves 8 of its 8 achievable edges, and member-call
telemetry reads `13/0/0/0` -- every member call resolved, none ambiguous, none
lacking receiver evidence. Three separate causes were behind the original four
misses:

- **JS/TS** inferred the receiver type correctly but two files each declaring
  `class Engine` made the owner ambiguous, so both lost the edge. Same-file
  preference resolves it.
- **Go** attaches methods to a receiver instead of nesting them in the type, so
  every Go method was recorded ownerless and could never match a typed
  receiver. Receiver extraction plus a containment link fixes it, and Go gained
  local type inference (`e := Engine{}`), which it had none of.
- **Rust** instantiates a unit struct by naming it (`let e = Engine;`), which
  matched no existing pattern. SCREAMING_CASE is excluded so a constant is not
  mistaken for a type.

The only remaining gap is edge 7 in each language, below.

Gate 1 verified on real Flask: adding a duplicate `helpers.py` moved inbound
call edges 151 -> 152. The same measurement on the previous commit gave
151 -> 140, independently reproducing the reported -11.

Gate 4 (self-recursion) now passes. The `tgt_id == src_id` guard was removed
only after auditing the consumers that a self-loop could mislead:

- **Dead code.** `caller_counts` already skips `source == target`, so a
  function that calls only itself still reports zero production callers and is
  still reported as dead. Verified directly: a `DeadRecursive` calling only
  itself stays at `production_callers = 0`, while a `LiveRecursive` called once
  externally reads 1, not 2.
- **Traversal.** Expansion seeds its visited set with the start nodes, so a
  self-loop is skipped rather than revisited.
- **Relations.** `callers` now includes the function itself, which is what this
  oracle asks for: `Fact` has 2 callers, itself and `Caller`.

A self-call is the only evidence that a function is recursive, so it is
recorded; the consumers that must not count it exclude it themselves.

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
