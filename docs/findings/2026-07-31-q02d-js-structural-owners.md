# Q02-D JavaScript structural receiver owners

Date: 2026-07-31

## Decision

Promote the first Q02-D JavaScript/TypeScript slice. Function-valued property
and prototype assignments now retain a module-scoped structural owner, so
`this.method()` and a syntactically proven `alias = this` can resolve within
annotation-free JavaScript without falling back to method-name matching.

This is a partial language promotion. Express framework callback parameters
and calls into the external `router` package remain untyped and are explicitly
not synthesized.

GraphGraph output was not the oracle. The source checkout supplied the
expected calls; paired graphs measured the topology delta.

## Rule

For an assignment:

```text
res.send = function send(...) { ... }
Store.prototype.save = function save(...) { ... }
```

the callable identity retains the assignment owner. Member-call matching uses
the provenance-bearing key:

```text
owner_key = (source module path, assignment owner)
```

Inside that callable, `this` has `owner_key`. A local receives the same fact
only for the explicit syntax `const|let|var local = this`. The target method
must have the same key and be unique. The finite lookup therefore abstains
when:

- the receiver is an untyped parameter;
- two candidate methods share the owner key;
- the only same-spelled owner lives in another module; or
- the target belongs to an external dependency.

No Express names or framework-specific argument positions appear in the
implementation.

## Frozen comparison

| role | repository | revision |
| --- | --- | --- |
| held out | Express | `18e5985b8a9d5e8423db0a9121f22bdaecd5b120` |
| neutral cross-project check | Mem0 | `cd79fa8914b5b1cf66daacc957d826065df57df8` |
| Express engine baseline | GraphGraph | `a987b94` |
| Mem0 neutral-check baseline | GraphGraph | `0f54dbe` |

The formal Express pair used clean detached worktrees. The existing checkout's
untracked `semantic.json` was excluded by using the clean worktree, not assumed
harmless. Both sides ran:

```text
graphgraph scan
  --directory <clean-express-worktree>
  --output <versioned-temp-graph>
  --depth symbols
  --frontend tree_sitter
  --no-docs
  --no-history
  --no-incremental
  --force
```

## Results

| metric | baseline | candidate |
| --- | ---: | ---: |
| resolved member-call sites | 143 | 180 |
| unknown-receiver sites | 6,246 | 6,182 |
| resolved / (resolved + unknown) | 2.24% | 2.83% |
| logical call edges added | — | 33 |
| logical call edges removed | — | 0 |

The five extra method nodes are previously-collided property methods whose
identity now includes their owner. Raw node IDs therefore change; the edge
comparison normalized by source path/label, target path/label, and relation.
Every one of the 33 additions:

- stays within one source module;
- has `tree_sitter_type_resolved` provenance; and
- targets a method carrying the same structural-owner fact.

Pinned Mem0 was neutral: 11,840 nodes, 28,378 edges, and zero logical call-edge
changes. Its member telemetry also remained exactly
`2547 resolved / 54 ambiguous / 2704 unknown`.

## Frozen response-method oracle

The earlier Express audit froze seven expected callers for `send`, `location`,
and `status`. The baseline recovered none. The candidate recovers all seven:

| target | expected callers recovered |
| --- | --- |
| `send` | `json`, `jsonp`, `sendStatus` |
| `location` | `redirect` |
| `status` | `redirect`, `send`, `sendStatus` |

It also recovers the source-visible `render -> send` call at
`lib/response.js:916`, which was omitted from the narrower original oracle.
All eight target-specific edges are supported directly by pinned source.

## External boundary abstention

`Route` and `dispatch` have no definition node in the Express graph because
they come from the external `router` dependency. `test/Route.js` contains 13
direct `route.dispatch(...)` invocations, but manufacturing an internal target
would invent package topology. The candidate therefore leaves this frozen
retrieval task unresolved. External symbol contracts need their own typed
representation and evaluation gate.

## Regression gates

Focused fixtures prove:

- property-assignment `this` calls resolve;
- prototype-assignment `this` calls resolve;
- explicit `alias = this` resolves;
- an unproven parameter named `self` does not resolve;
- lexical `this` inside an arrow-function assignment does not resolve; and
- same-spelled structural owners in different modules do not cross-link.

## Remaining limits

- The absolute Express ratio remains low because most of its 6,182 unknown
  receivers are annotation-free parameters, closures, or framework-injected
  objects.
- Cross-module structural-object identity requires import/export evidence; raw
  owner spelling is deliberately insufficient.
- External dependency methods remain absent.
- Q02-D still needs fresh addressable-volume measurements for Rust, C#/Java,
  and C++ before choosing the next slice.
