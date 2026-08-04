# Incremental update instruction set

Working notes for making iterative "edit code, then re-query the graph" loops
snappy. Written after profiling a real regression on the locus monorepo
(41,546 nodes / 87,326 edges, 7,602 tracked files) during a code-review pass
on 2026-07-08.

## What we measured

A **no-op** rescan (zero files changed) of locus took **86 seconds** before
any fix. Profiling (`cProfile` on `scan_directory` directly) found the cause
wasn't hashing or re-extraction -- both were already correctly skipped for
unchanged files. It was this loop, run once per *edge reference* recorded in
every skipped file's manifest entry:

```python
for src, tgt, etype in info.get("edges", []):
    matching_edge = None
    for pe in previous_graph.edges:          # linear scan over ALL edges
        if pe.source == src and pe.target == tgt and pe.type == etype:
            matching_edge = pe
            break
    skipped_edges.append((src, tgt, etype, matching_edge))
```

With ~87k edges and ~87k manifest edge-references to resolve, this is
effectively O(E²). Indexing `previous_graph.edges` once into a
`dict[(source, target, type), Edge]` and doing O(1) lookups dropped the same
no-op rescan to **15.7 seconds** (5.5x), with byte-identical output
(same node/edge counts). Fixed in `scanner/core.py` (`previous_edge_index`).

Remaining ~15s breakdown (profiled after the fix):

| Cost | ~time | Scales with |
|---|---|---|
| `collect_files` directory walk (`nt.stat`, `rglob`, skip-dir regex matching) | ~5-7s | total files in tree, **not** files changed |
| `detect_interpretation_concepts` (concept-linking pass) | ~6s | total **nodes** in the graph, **not** nodes changed |
| Loading + saving the previous graph (`.gg` binary, manifest JSON) | ~2-3s | total graph size |

None of these three remaining costs are algorithmically broken (no O(n²)) --
they're just **unconditionally O(total)** when the caller already knows
exactly which files changed. That's the real opening for an instruction-set
style API: skip re-deriving "what's different" and let the caller assert it.

## Prior art (why this is a well-trodden pattern, not a new idea)

- **LSP `textDocument/didChange`** — editors tell the language server exactly
  which document changed (and often the exact byte range), rather than the
  server diffing the whole workspace on every keystroke.
- **rust-analyzer / salsa** — an incremental-computation framework built
  around revision-tagged inputs. A file edit bumps a revision counter and
  invalidates only the *dependency-graph-reachable* downstream computations,
  not the whole index. Recent work made the crate graph itself incremental,
  so adding/removing a dependency invalidates only the affected crates
  instead of the entire workspace. ([rust-analyzer architecture](https://rust-analyzer.github.io/book/contributing/architecture.html), [durable incrementality](https://rust-analyzer.github.io/blog/2023/07/24/durable-incrementality.html))
- **Graph CRDTs** — the canonical minimal instruction set for a mutable graph
  under concurrent/incremental edits is four ops: `addN(node)`, `rmvN(node)`,
  `addE(src,dst)`, `rmvE(src,dst)`. A node/edge is live iff it has an add not
  shadowed by a later remove. This is the right vocabulary for graphgraph's
  own primitives below.
- **Differential dataflow / incremental view maintenance** — compute output
  deltas from input deltas instead of recomputing the whole view; the
  general technique is "delete-and-rederive" scoped to exactly the changed
  keys.

The common thread: **the caller (editor, git hook, agent) already knows what
changed** — the expensive part of naive incremental systems is almost always
*rediscovering* that fact by brute force, not applying the change itself.
graphgraph's `scan_directory` already does the "apply the change" part
correctly and cheaply (dirty-file extraction, `context_nodes` merging); it
just currently always pays the "rediscover what changed" cost too, even when
a caller could hand it the answer directly.

## Correction: graphgraph already had half of this instruction set

An earlier draft of this doc claimed "no add_node/remove_node exists on
`Graph`." That was wrong — missed on first read. `graph/operations.py`
already implements exactly the CRDT vocabulary above, as an append-only,
operation-logged API over a single in-memory `Graph`:

| CRDT op | graphgraph function | Delete semantics |
|---|---|---|
| `addN` | `add_node(graph, node)` | — |
| `addE` | `add_edge(graph, edge)` | — |
| `rmvE` | `expire_edge(graph, src, tgt, type, valid_to, reason)` | soft: `active=False`, `valid_to` set |
| `rmvN` | **was missing** — added below | — |
| (compound) | `merge_node(graph, source_id, target_id)` | dedupes edges, drops source node |

Every op returns `(new_graph, GraphOperation)` and can be appended to a
JSONL log via `append_operation`/`read_operations` for replay/audit. This is
the right layer for *fine-grained, programmatic* graph mutation — e.g. an
agent asserting "this specific edge is now stale" or recording a decision
trace — independent of any source file on disk.

**Gap closed**: added `expire_node(graph, node_id, valid_to, reason,
expire_incident_edges=True)` to `graph/operations.py`, mirroring
`expire_edge`'s soft-delete convention exactly (mark inactive, don't erase,
so the operation log stays a true history). Defaults to also expiring
incident edges, since a live edge pointing at a dead node is a dangling
reference. Exported through `graph/__init__.py` and the top-level
`graphgraph` package, same as `expire_edge`.

## Two layers, not a duplication

`update_paths`/`remove_paths` (below) operate at a **different granularity**
than `graph/operations.py` and don't replace it:

- **`graph/operations.py`** — single node/edge, soft-delete, caller supplies
  the exact mutation. No filesystem involved. Right tool for "assert one
  fact changed."
- **`scanner/core.py` (`update_paths`/`remove_paths`)** — whole-file
  granularity, hard delete via omission (matching `scan_directory`'s
  existing convention: a file's stale nodes are never re-added, not marked
  inactive), driven by re-reading source files from disk. Right tool for
  "I edited/deleted these files, re-derive what's true from source."

Both are legitimate "instruction set" members; they answer different
questions ("what should this file's subgraph look like now" vs. "apply this
one exact mutation").

## Implemented: `update_paths(paths)` / `remove_paths(paths)`

Shipped in `scanner/core.py`, exported from `graphgraph.scanner` and the
top-level `graphgraph` package. Both require a prior `scan_directory` run
(existing manifest + graph at the given paths) and raise `ValueError`
otherwise; the CLI/MCP wrappers (`update_paths_validated_graph` /
`remove_paths_validated_graph` in `services/native.py`) catch that and any
validation failure, and fall back to a full `scan_directory` rebuild — the
same repair philosophy `scan_validated_graph` already uses.

- **`update_paths(root, paths, ...)`** — caller asserts these specific files
  changed (or are new). No `collect_files` walk, no hashing of anything the
  caller didn't name. Every other tracked file (read from
  `manifest.files.keys()`, not rediscovered from disk) is restored verbatim.
  A named path that no longer exists on disk is treated as an implicit
  removal rather than erroring. Passes `scope_concepts_to_dirty=True` to
  `_build_graph_from_split` (see below).
- **`remove_paths(root, paths, ...)`** — caller asserts these files were
  deleted/renamed away. No re-extraction at all: just drop their manifest
  entries and let the restoration loop naturally omit them.
- **`_build_graph_from_split(...)`** — the ~250-line body of what used to be
  the tail of `scan_directory`, extracted so both the full-discovery path and
  the two targeted primitives run the *exact same* extraction/manifest/
  confidence-adjustment logic. This is what makes the correctness guarantee
  possible: `update_paths` and `scan_directory` are provably doing the same
  work on the dirty set, just arriving at that set differently.

**Second win, scoping concept-linking**: `link_source_interpretation_concepts`
is a pure function of a node's own fields (label/kind/path/facts) — it reads
no other file's content. Its edges are already correctly attributed back to
the originating file in manifest bookkeeping (via the `endpoint_nodes`
side-channel: a `implements_algorithm` edge's source is the originating
symbol, so `find_file_for_node(edge.source) == rel` already captures it into
that file's manifest entry). So for a skipped file, its concept edges get
restored through the *existing* `skipped_edges` mechanism — the exact same
path already used for `calls`/`contains`/etc. — with zero new bookkeeping
needed. `scope_concepts_to_dirty=True` (opt-in, only used by the targeted
primitives, `scan_directory`'s default behavior is untouched) skips
re-running concept detection on restored nodes and relies on that existing
restoration instead. Verified with a dedicated test
(`test_update_paths_preserves_concept_edges_for_untouched_files`) that an
untouched file's concept edge survives a targeted update of a different file.

### Measured end-to-end result (locus, 41,546 nodes / 87,325 edges)

| Operation | Time | vs. original |
|---|---|---|
| No-op full rescan, before any fix | 86s | baseline |
| No-op full rescan, after O(n²) fix | 15.7s | 5.5x |
| `update_paths(['crates/locus-cli/src/main.rs'])` | **2.1s** (library call) / 6.2s (cold CLI process) | **~40x** |

Correctness verified two ways: (1) synthetic cross-file-call test comparing
`update_paths` output to a full rescan node-for-node and edge-for-edge
(`test_update_paths_matches_full_rescan_including_cross_file_calls`); (2)
direct run against the real locus graph, matching node/edge counts.

### CLI / MCP surface

- `graphgraph update --files <path...> [--directory D] [--output O] [--depth ...]`
- `graphgraph remove --files <path...> [--directory D] [--output O] [--depth ...]`
- MCP tools `update_graph_files` / `remove_graph_files`, same shape as
  `build_graph`. All three (`update_paths`, `remove_paths`, `expire_node`)
  have direct pytest coverage; the CLI and MCP paths were smoke-tested
  end-to-end (real subprocess, real stdin/stdout JSON-RPC) against both a
  synthetic repo and the real locus repo.
- MCP `query_context` also accepts `changed_paths` / `deleted_paths`. It
  combines both sets into one authoritative splice, persists the validated
  result, and queries the returned in-memory graph immediately. This removes
  the update, remove, then query round-trip sequence and prevents a packet
  cache hit or graph reload from observing pre-splice state. When refresh
  options are omitted, scan depth/frontend/docs/history inherit from the
  saved graph.
- MCP `query_context` also accepts `sync: "git"`; CLI `context` exposes the
  same behavior as `--sync git`. Git supplies candidate changed/deleted paths,
  manifest hashes make repeated calls idempotent, and one batched ignore-rule
  check removes paths indexed before they became ignored. This avoids a
  repository walk, but the precise cost includes O(manifest path strings) for
  ignore reconciliation plus hashing/extraction only for Git-changed
  candidates.

## Where this fits in the agent loop

This directly answers the "add code, test, measure, read context graph"
loop. After the O(n²) fix, a full rescan is viable for small-to-medium repos
(seconds). `update_paths` makes it viable for large monorepos with big
vendored corpora (locus's 22k-file tree): rescan cost is now proportional to
what the agent just edited, not to repo size. Correctness caveat carried
over from every incremental indexer that does this (ctags, LSP, salsa
alike): files *indirectly* affected by a change (e.g. a caller in an
untouched file) won't get new edges until that file is itself scanned —
acceptable for a tight edit-test loop, not a substitute for an occasional
full rescan before a big blast-radius query.

## Status

- [x] O(n²) edge-lookup fix in `scan_directory` (shipped, verified 5.5x on
      locus, output-identical).
- [x] `expire_node` added to `graph/operations.py` (missing `rmvN`).
- [x] `update_paths(paths)` / `remove_paths(paths)` in `scanner/core.py`,
      exported from the top-level package.
- [x] Manifest-sourced (not disk-walk-sourced) skip-file enumeration for the
      targeted primitives.
- [x] Concept-linking pass scoped to dirty files for the targeted primitives
      (default `scan_directory` behavior unchanged).
- [x] CLI (`graphgraph update` / `graphgraph remove`) and MCP
      (`update_graph_files` / `remove_graph_files`) wiring, with fallback to
      a full rebuild on any validation failure.
- [x] Fused MCP refresh + retrieval through `query_context`, including one
      changed/deleted splice, direct in-memory retrieval, and saved scan-option
      inheritance.
- [x] Idempotent Git-derived refresh for MCP and CLI, including stale ignore
      reconciliation and compact refresh metadata.
- [x] Query-aware dirty-file representatives: at most one seed per path and a
      logarithmic four-path cap instead of every dirty symbol becoming a seed.
- [x] Measured end-to-end on locus: 86s -> 15.7s -> 2.1s.
