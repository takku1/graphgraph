# Q02-C persistent type facts and affected-key re-join

Date: 2026-07-31

## Decision

Promote Q02-C for the Python receiver-fact stratum. Per-file fact
contributions and obligations now survive in manifest version 4. An
incremental edit updates the changed contributions, recomputes only the
forward-reachable package re-export keys, and uses a reverse obligation
relation to promote unchanged consumers whose receiver edges can change.

This does not promote general incremental equivalence. Definition topology,
JavaScript and the other language strata, no-op artifact identity, manifest
load cost, and graph load/save cost remain separate queued work.

GraphGraph output was not used as the oracle. Each incremental graph was
compared with a clean full rebuild from the same source state, and the
fixtures assert a non-empty expected retarget or removal so equality cannot
pass vacuously.

## State model

For file `f`, the manifest stores a finite contribution `F_f` and obligation
set `O_f`. For fact key `k`, the project environment is:

```text
J(k) = join({F_f(k) | f contributes k} U {J(s) | s -> k is a re-export})
```

`join` is the existing finite powerset union: empty is unknown, a singleton
is concrete, and multiple types are ambiguous. Package re-exports form a
directed relation and are solved with a bounded monotone worklist.

For an edit, let `D` be the changed project keys after contribution and
re-export propagation. The unchanged files promoted for extraction are:

```text
A = union({reverse_obligations(k) | k in D})
```

Field obligations are conservatively keyed by field name because their owner
is itself a local data-flow result. Thus a changed `Context.value` fact wakes
files containing a `.value` obligation, not every Python file.

The loaded-index update cost is:

```text
O(changed file facts + reachable changed re-exports + affected obligations)
```

Unrelated contribution and re-export rows are not iterated by the re-join.
Manifest JSON and graph loading are intentionally outside this claim and
remain assigned to Q07-B's persistent-state experiments.

## Equivalence gates

The focused fixtures cover:

- imported factory return `Old -> New`, retargeting an unchanged caller from
  `Old.ping` to `New.ping`;
- project field `Context.value: Old -> New`;
- deletion of a return-fact provider, removing the stale typed call from an
  unchanged consumer;
- package `__init__` re-export propagation; and
- ambiguity preservation through two package re-exports of the same name.

For the return, field, and deletion cases, incremental nodes and every edge
field equal a clean full rebuild. Telemetry reports changed fact count,
affected obligation count, and promoted file count. The manifest round-trip
test covers the new per-file payload; the extractor capability flag preserves
third-party/custom extractors that implement the prior protocol.

## Delta-scaling benchmark

Reproduction:

```text
uv run python benchmarks/context_graph/incremental_type_fact_rejoin.py
```

Environment: Windows 11 Pro 10.0.26200, 11th Gen Intel Core i7-11850H,
31.2 GiB RAM, Python 3.11.15, uv 0.11.24. Each row has 25 samples. Index
construction is outside the timed interval.

With one changed fact and one affected consumer:

| unrelated facts plus re-exports | median | p95 |
| ---: | ---: | ---: |
| 0 | 0.0278 ms | 0.0342 ms |
| 1,000 | 0.0669 ms | 0.0871 ms |
| 10,000 | 0.0987 ms | 0.1387 ms |

With one changed fact and increasing affected consumers:

| affected files | median | p95 |
| ---: | ---: | ---: |
| 1 | 0.0267 ms | 0.0274 ms |
| 100 | 0.0586 ms | 0.1752 ms |
| 1,000 | 0.3294 ms | 0.5423 ms |

The small unrelated-volume increase is consistent with larger hash-table
cache footprints; the algorithm performs no unrelated-row traversal. Growth
tracks materialized affected consumers.

## Intentional invalidation

The manifest schema moved from version 3 to 4. Existing manifests fail the
compatibility check and receive a clean rebuild, preventing an older manifest
without facts from silently claiming incremental equivalence.

## Remaining limits

- A new process still parses the complete manifest JSON and loads the previous
  graph before applying the indexed delta.
- Generic symbol additions, removals, and renames can affect unchanged callers
  outside the typed-fact relation; Q07 owns universal incremental equivalence.
- No-op effective-graph identity and the `<100 ms` preflight target are not
  claimed here.
- Python is the only persisted typed-fact stratum. Q02-D owns language
  generalization.
- The scanner still carries global member-call telemetry from the last full
  snapshot; it does not synthesize global counts from incremental fragments.
