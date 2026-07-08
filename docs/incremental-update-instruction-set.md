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

## Proposed primitives

Two entry points, thin wrappers around machinery that already exists inside
`scan_directory`:

- **`update(paths)`** — caller asserts these specific files changed (or are
  new). Skip `collect_files` entirely; skip hashing everything else. Load
  the manifest + previous graph, restore every *other* tracked file's
  nodes/edges verbatim (trusted, not re-verified), and run the existing
  dirty-file pipeline (`extract_symbols(..., context_nodes=<restored>)`,
  `add_file_edges`, doc/history/concept passes) scoped to only `paths`.
- **`remove(paths)`** — caller asserts these files were deleted/renamed away.
  Drop their nodes/edges from the manifest and restored set; no directory
  walk, no re-extraction.

Both map onto the CRDT vocabulary above: `update` is "rmvN/rmvE for the old
version of this file, then addN/addE for the new one"; `remove` is pure
`rmvN`/`rmvE`. Node/edge identity is already stable (`Node.id`, and now
`(source, target, type)` for edges via the new index), so "old version" is
just "whatever the manifest last recorded for that path."

To actually hit the "skip collect_files and the full concept pass" win, two
things need to change beyond just adding a CLI flag:

1. The dirty/skip split (`scan_directory` lines ~112-131) needs a mode where
   the "skip" side is populated from `manifest.files.keys()` directly instead
   of from a fresh `collect_files()` walk — i.e. trust the manifest's file
   list rather than re-deriving it from disk, when the caller has explicitly
   scoped the update to `paths`.
2. The interpretation-concept pass (`link_source_interpretation_concepts`,
   currently `for node in tuple(nodes.values())` — all nodes, every scan)
   needs to scope to nodes belonging to `dirty_rels` plus whatever the
   manifest already recorded as concept edges for skipped files (mirroring
   how `skipped_edges` restoration already works for other edge types).

Both are targeted, low-risk changes to existing loops, not a rewrite --
`scan_directory`'s dirty/skip architecture already has the right shape, it's
just always fed "everything is dirty until proven otherwise" instead of
"only `paths` is dirty, full stop."

## Where this fits in the agent loop

This directly answers the "add code, test, measure, read context graph"
loop: after fixing the O(n²) bug, that loop is already viable for
small-to-medium repos (a few seconds per rescan). The `update(paths)`
primitive would make it viable for large monorepos with big vendored
corpora (locus's 22k-file tree) by making rescan cost proportional to what
the agent just edited, not to repo size. Correctness caveat carried over
from every incremental indexer that does this (ctags, LSP, salsa alike):
files *indirectly* affected by a change (e.g. a caller in an untouched file)
won't get new edges until that file is itself scanned — acceptable for a
tight edit-test loop, not a substitute for an occasional full rescan before
a big blast-radius query.

## Status

- [x] O(n²) edge-lookup fix in `scan_directory` (shipped, verified 5.5x on
      locus, output-identical).
- [ ] `update(paths)` / `remove(paths)` CLI + MCP primitives.
- [ ] Manifest-sourced (not disk-walk-sourced) skip-file enumeration.
- [ ] Scope the interpretation-concept pass to dirty files.
