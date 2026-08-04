> **Academic title:** Receiver-Type Inference & Name Resolution  
> **Legacy name:** receiver-type-resolution  
> **Subsystem:** [SYSTEM.md](./SYSTEM.md)

# Receiver type resolution

How GraphGraph decides what `x` is in `x.method()`, why it currently fails on
variable receivers, and the design that closes the gap without giving up
file-incremental scanning.

This is the single largest capability gap measured against peer tools. It is
also the one with the widest blast radius: the same missing join limits Python,
C#, C++, TypeScript, and Rust simultaneously.

## Why this is the binding constraint

The scanner already reports the scalar that predicts everything downstream —
`resolved/(resolved + unknown_receiver)` on the scan line:

| repo | language | resolution |
| --- | --- | ---: |
| redis | C | 78.7% |
| flask | Python | 61.2% |
| mem0 | Python | 47.1% |
| ripgrep | Rust | 34.2% |
| UniGetUI | C# | 8.3% |
| express | JS | 2.2% |

A **36x spread** that an aggregate score hides. The pattern is not language
quality, it is *idiom*: languages whose dominant call shape is `self.x()` score
high, and languages whose idiom is `obj.method()` on an untyped local, a field,
or a builder chain score low. See
[the multi-language gray-box evaluation](../../evaluation/graybox-cycles/2026-07-30-graybox-multilang-critical.md)
for the per-symbol oracle behind these numbers.

## What actually fails

An earlier reading was that "there is no local variable or parameter type
inference." That is wrong, and the correction matters because it changes the
fix from *build an analysis* to *join two analyses that already exist*.

Both halves are present and working:

```
local types for _render: {'ctx': 'AppContext'}          # parameter annotation resolved
  -> app typed? False                                    # `app = ctx.app` yields nothing
field types in ctx.py: {('AppContext','app'): 'Flask'}   # the answer exists, elsewhere
```

Two independent gaps produce every observed miss:

1. **No attribute case in value typing.** `_python_value_type` handles `Call`,
   literals, and `Constant`. `ctx.app` is an `Attribute` and falls through to
   `""`, so an attribute assignment loses its type *even inside one file*.
2. **Field-type maps are file-local.** `_python_class_field_types(source.text)`
   is computed inside the per-source loop, so a class defined in `ctx.py` is
   invisible while scanning `templating.py`.

Module-level proxies (`current_app.ensure_sync`) add a third case — global
binding types — and attribute chains (`ctx.app.ensure_sync`) add a fourth,
multi-hop resolution. All four share the same root: nothing joins per-file type
facts across the project.

## Prior art, and the gap between it

Two mature systems bracket this problem from opposite sides, and neither
occupies the middle.

**[PyCG](https://arxiv.org/pdf/2103.00587)** reports 99.2% precision and 69.9%
recall on Python call graphs. Reading the implementation rather than the paper:
every definition carries a `NamePointer` holding a points-to *set*, assignment
merges sets, and `analyze()` runs repeated `PostProcessor` passes inside a
`while not has_converged()` loop. It is Andersen-style inclusion analysis —
precise, and **whole-program and iterative by construction**. That is
structurally incompatible with a hash-diffed incremental scan.

**[Stack graphs](https://arxiv.org/abs/2211.01224)**, which power GitHub's
Precise Code Navigation, take the opposite trade. Their defining property is
isolation: for each source file an isolated subgraph is built "without any
knowledge of, or visibility into, any other file in the program," which is what
makes them incremental at GitHub's scale. But they are purely syntactic *name
binding*, not type inference. They do not resolve `x = obj.field; x.method()`.

**[Typify](https://arxiv.org/pdf/2604.05067)** argues usage context alone
carries enough type information to skip whole-program analysis — directionally
the right instinct under a latency budget.

**A peer tool's advantage is a dependency, not an algorithm.** The
`code-review-graph` control that resolved 12/12 where GraphGraph resolved 9
does so by delegating to [Jedi](https://github.com/davidhalter/jedi)
(`jedi>=0.19.2`) in a post-build pass that re-walks Python ASTs and calls
`jedi.Script.goto()`. That is a legitimate strategy and it is Python-only. It
should not be read as an algorithmic benchmark.

## Design: file-incremental type join

The literature gap is genuine — PyCG is not incremental, stack graphs do not do
types. GraphGraph's substrate (per-file extraction, a revisioned persistent
graph, hash-diff rescan) fits the missing middle. The design applies stack
graphs' *isolation* principle to types rather than names.

**Per file, independently**, emit two kinds of fact:

- resolved local types (exists today), and
- **deferred obligations** as data: `app := typeof(AppContext.app)` — recorded,
  not resolved.

**At project level**, assemble `(class, field) -> type` from every file, then
discharge obligations by lookup.

This stays incremental where it matters. A file's emitted facts depend only on
that file, so editing one file re-emits only that file's facts. The join input
is small — field declarations plus open obligations — so re-joining is cheap and
there is no fixpoint over the codebase.

**Bounded depth, not convergence.** Attribute chains need k iterations over the
obligation set. Cap k (2-3 covers the observed shapes) and report
`unresolved_at_depth` in the receipt rather than iterating to a fixpoint. The
scan already reports why receivers went untyped; this extends that telemetry
rather than replacing it with silence.

**Precision is preserved by construction.** The gray-box evaluation found
GraphGraph's ambiguous answer to a 7-way `dispatch_request` dispatch to be
*better* behavior than a peer tool's unqualified name matching, and found
exactly one precision defect in the entire run. So the join keeps the existing
single-type discipline: when `(class, field)` resolves to more than one declared
type project-wide, it stays unresolved. Recall rises; precision does not move.

## Staged plan

| stage | change | closes | status |
| --- | --- | --- | --- |
| 1 | `Attribute` case in value typing | intra-file `x = obj.field` | **done** |
| 2 | promote field-type maps to project scope | cross-file attribute types | **done** |
| 3 | module-level global binding types | proxy receivers (`current_app`) | **done** |
| 4 | bounded k-hop obligation discharge | chains (`ctx.app.method()`) | **done** |
| 5 | import-shadowing guard | the one observed false positive | **done** |

### Measured outcome of stages 1, 2, and 5

On flask's recorded oracle, `update_template_context` moved from **0/2 to 2/2**
— the exact miss the gray-box run reported — and every symbol that already
resolved exactly still does. `ensure_sync` stays at 9 callers; its remaining
misses are a module proxy and an attribute chain, which are stages 3 and 4.

Two measurement lessons came out of this, both worth more than the code:

**The aggregate counter is too coarse to see this work.** Repo-wide
`member_calls_resolved` moved 847 → 850 on flask and not at all on requests or
mem0, while the specific reported miss went from broken to exact. Judge this
stage against a per-symbol oracle, never against the scan-line ratio.

**Stage 1 alone is nearly a no-op**, measured: one extra resolved call across
three repositories. Field-type maps were file-local, and a declaring class
almost never shares a file with the function that uses it. The value is entirely
in the stage-2 join; stage 1 is a prerequisite, not a deliverable.

Stage 5 needed a correction that only a controlled diff caught. The first guard
suppressed 11 express edges, **six of them correct**: `exports.normalizeTypes =
function(){}` is extracted as kind `method`, and the require-binding regex
matched the `require('./utils')` prefix of `require('./utils').normalizeTypes`.
Separating whole-module bindings from member bindings brought it to 4 suppressed
edges, all genuine, with the correct edges restored.

Stage 5 is independent and cheapest. `var send = require('send')` currently
collides with a local `res.send` method; a local binding introduced by an import
must *suppress* method-name matching for that identifier. Pure precision, no
inference required.

Stages 1 and 2 are language-agnostic in shape. C#, C++, TypeScript, and Rust
already have field-type maps under the same per-file confinement, so one join
lifts every language at once. That leverage — not Python specifically — is the
reason to do this.

### Measured outcome of stages 3 and 4

The implementation is now a bounded monotone constraint system rather than a
second assignment-order heuristic. Each binding holds a finite set of
source-backed type names. Join is set union:

```text
unknown = {}
concrete(T) = {T}
ambiguous(T, U, ...) = {T, U, ...}
join(A, B) = A union B
```

Only singleton sets project into receiver resolution. A dependency-indexed
worklist re-evaluates obligations when their root gains evidence, and attribute
paths longer than the configured bound remain unresolved with a receipt.
Module-global joins are keyed by both import-module provenance and symbol name,
preventing an unrelated same-named global from becoming receiver evidence.

A fresh scan of the pinned Flask fixture was compared directly with the
independent critical gray-box graph. It retained every old edge and added 20
`calls` edges: receiver telemetry moved from `850 resolved / 534 unknown` to
`871 resolved / 484 unknown`, and `ensure_sync` gained the three
source-visible callers using `current_app` (`9 -> 12`). The direct diff was
then checked against the fixture source; the additions were supported by
annotated globals, proxy inheritance, declared fields, or annotated locals.
Subsequent held-out scans retained every incumbent edge: Requests added eight
source-checked calls (`501 -> 509` resolved), and Mem0 added 28
source-checked Python calls (`1622 -> 1650` resolved). Project fields, package
re-exports, callable returns, assignments, and obligations now retain their
fact provenance and ambiguity. Cross-language generalization remains gated on
separate per-language oracles.

## Limits worth stating before generalizing

- **Recall is bounded by declared types.** Untyped JavaScript has no
  annotations to join. Stage 5 fixes express's false positive; it will not move
  express's recall, and no amount of joining will make 2.2% look like flask.
- **Only Python is held-out so far.** Flask, Requests, and Mem0 establish the
  Python slice. They do not license a recall claim for the rest of the 36x
  language spread.
- **Jedi would likely beat this on Python alone.** It is not proposed here
  because it is a heavy single-language dependency, and the join lifts six
  languages for less.

