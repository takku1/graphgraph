# P02 typed-fact held-out receiver comparison

Date: 2026-07-31

## Decision

Promote Q02-A and the Python portion of Q02-B. Typed field, import, assignment,
return, and deferred-obligation facts improved receiver topology on the Flask
calibration repository and two held-out Python repositories without removing
an incumbent edge. Generalization to other languages and persistent
incremental facts remain open.

This comparison does not treat GraphGraph output as the oracle. Graph files
measure the delta; the target repositories' pinned source determines whether
each added call is supported.

## Frozen inputs

| role | repository | revision |
| --- | --- | --- |
| calibration | Flask | `954f5684e4841aad84a8eec7ace7b81a0d3f6831` |
| held out | Requests | `cd90742ed94d901759e26766197d0ce7c7bd9c8e` |
| held out | Mem0 | `cd79fa8914b5b1cf66daacc957d826065df57df8` |
| engine baseline | GraphGraph | `cf9fa66` |

Both engine versions scanned the same repository worktree with:

```text
graphgraph scan
  --directory <repository>
  --output <versioned-temp-graph>
  --depth symbols
  --frontend tree_sitter
  --no-docs
  --no-history
  --no-incremental
  --force
```

The baseline engine ran from a detached Git worktree at `cf9fa66`; the
candidate ran from the current worktree. Ignore files were honored. Default
pruning removed Git, GraphGraph/Graphify outputs, agent distributions, caches,
and generated reference directories reported by each scan. Tests and examples
remained included.

## Results

| repository | resolved | unknown receiver | added edges | removed edges |
| --- | ---: | ---: | ---: | ---: |
| Flask | `850 -> 871` | `534 -> 484` | 20 calls | 0 |
| Requests | `501 -> 509` | `174 -> 159` | 8 calls, 6 reads | 0 |
| Mem0, Python stratum | `1622 -> 1650` | `1211 -> 1086` | 28 calls, 26 reads | 0 |

The Flask `ensure_sync` oracle remains `9 -> 12`, recovering all three
source-visible `current_app.ensure_sync` callers in `views.py`. A package
re-export fixture covers the separate `from flask import current_app` path.

Every added Requests call was checked at its source location. They are
supported by typed `Response` fields, `Request`/`Session` constructors, or
assignment order visible in the test body. Every added Mem0 call was likewise
checked: the set consists of `_make_backend() -> PlatformBackend`,
`_make_llm() -> AWSBedrockLLM`, and `MemoryClient.project -> Project`
receivers. The paired `reads` edges are the existing test-only typed-attribute
projection of those same receiver facts.

## Complexity correction

The first candidate implementation parsed all module return facts inside the
per-callable loop. Requests exceeded the 60-second comparison window and
Mem0's symbol phase rose from `38.4s` to `54.7s`. That candidate was rejected
before promotion.

The corrected implementation:

1. parses module facts outside the callable loop;
2. walks already-parsed function AST nodes for direct return evidence; and
3. has a regression test proving module-return extraction count is independent
   of callable count.

After correction, Mem0's observed symbol phase was `37.4s` in one isolated run
and `31.9s` in a later parallel run. These are characterization samples, not a
latency promotion claim. Q02-C and Q07 still require distributions and a
delta-scaling complexity gate.

## Remaining limits

- Full project-field and package-re-export joins are recomputed during a full
  scan; per-file fact persistence is not implemented.
- Return facts cover annotations and direct stable concrete return
  expressions. They do not launch whole-program inference.
- JavaScript/TypeScript, Rust, C#/Java, and C++ are not promoted by this
  Python result.
- Unknown receivers moving to `unmatched` can make the aggregate unresolved
  counter rise even while source-backed calls improve. Per-symbol oracles and
  the resolved/unknown partition remain the acceptance measures.
