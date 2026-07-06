# NEWFINDINGS.md

Static-analysis bug review of the GraphGraph main program.

> **Second-pass status (update):** Bug 1 and Bug 2 below are now **FIXED** in the
> tree.
> - `activation.py` filters on `graph.nodes` at selection, seeding, spreading,
>   and cache-save (lines 49, 54, 69/71, 94, 104), and every renderer in
>   `packets.py` now begins with `_existing_nodes`/`_existing_edges` — the
>   phantom-node `KeyError` is gone and the renderer inconsistency is resolved.
> - `native.py:9-12` now has the `tomllib`→`tomli` fallback.
>
> A wider second pass (core graph/PageRank, io, binary storage round-trip,
> retrieval, cache, manifest, scanner, validator) surfaced one **new** bug —
> see **Bug 3** at the bottom.

---

## Bug 1 — `spreading_activation` emits node IDs that aren't in the graph → `KeyError` crash in most packet renderers

**Where:** `src/graphgraph/retrieval/activation.py:47-49` and `92-93`

`spreading_activation` seeds its energy map from a persisted cache
(`.graphgraph/activation_state.json`) written by a previous turn:

```python
if previous_activation:
    for node_id, score in previous_activation.items():
        activation[node_id] = score * decay      # node_id may no longer exist
...
selected_nodes = {nid for nid, score in sorted_nodes[:max_nodes]}   # no graph.nodes filter
```

After a re-scan, symbol IDs change, but the stale cache still holds the old IDs.
Those "ghost" IDs get decayed, can survive into `selected_nodes`, and are
returned as part of the node set. Then rendering blows up because the node set no
longer matches `graph.nodes`.

Reproduced — 6 of 8 packet formats crash:

```
selected nodes: {'a', 'b', 'ghost_node_from_old_scan'}
  gg_max: OK          lowlevel: KeyError        hybrid: KeyError
  svo: OK             doc_summary: KeyError      semantic_arrow: KeyError
  sql: KeyError        tensor: KeyError
```

**Reachable in production:** `--query-class spreading_activation` combined with
any of `--packet lowlevel|sql|hybrid|semantic_arrow|doc_summary` (the parser
doesn't restrict `--query-class`). Even with the default `gg_max` it "works" only
by silently dropping the ghost node — so the packet's node count is quietly wrong.

**Fix (one line):** filter to real nodes at selection time:

```python
selected_nodes = {nid for nid, score in sorted_nodes[:max_nodes] if nid in graph.nodes}
```

(Also worth filtering `previous_activation` on load so ghosts never enter the
energy map.)

**Related defensive inconsistency:** `render_sql`, `render_tensor_array`, and
`render_svo` use `.get()` and skip dangling references, but `render_gg_max`,
`render_gg_lex`, `render_lowlevel`, `render_hybrid`, `render_semantic_arrow`, and
`render_doc_summary` index `graph.nodes[...]` directly. Fixing Bug 1 removes the
live trigger, but the renderers should agree on defensiveness.

---

## Bug 2 — `import tomllib` breaks every command on Python 3.10 (a declared-supported version)

**Where:** `src/graphgraph/services/native.py:9`

```python
import tomllib   # stdlib only since Python 3.11, no fallback
```

`pyproject.toml` declares `requires-python = ">=3.10"` and a `Python :: 3.10`
classifier. But `tomllib` doesn't exist before 3.11. The import chain is eager and
unavoidable:

`cli/__init__.py: from .commands import *`
→ `commands.py:27: from ..services.native import ...`
→ `native.py:9: import tomllib`

So on Python 3.10 the **entire CLI (and the MCP server) dies at startup** with
`ModuleNotFoundError: No module named 'tomllib'` — not just the `status`/`context`
commands. (No impact on Python 3.11+.)

**Fix:** either add a fallback, or drop 3.10 from `pyproject.toml`.

```python
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib   # add tomli to deps for py<3.11
```

---

## Bug 3 — incremental scan resurrects deleted/renamed symbols referenced from unchanged files (silent stale graph)

**Where:** `src/graphgraph/scanner/core.py` — manifest write at `288-304`,
skipped-file restore at `139-155`, deleted-file-only cleanup at `283-286`.

The incremental scanner attributes each edge to its **source** file, but the
edge's **target** may be a symbol owned by a *different* file. When it records a
file's manifest entry it stores those foreign endpoint nodes too:

```python
# lines 289-295
file_edges = [(e.source, e.target, e.type) for e in edges if find_file_for_node(e.source) == rel]
endpoint_nodes = {nid for edge in file_edges for nid in edge[:2] if nid in nodes}
file_nodes = sorted({
    nid for nid, node in nodes.items()
    if find_file_for_node(nid) == rel or nid in endpoint_nodes   # foreign targets included
})
```

On a later scan an unchanged file is "skipped" and its stored nodes/edges are
restored verbatim from the previous graph:

```python
# lines 141-155
for nid in info.get("nodes", []):
    if nid in previous_graph.nodes:
        nodes[nid] = previous_graph.nodes[nid]   # resurrects foreign endpoint nodes
...
edges.append(matching_edge)                      # and the edge to them
```

Manifest cleanup only drops entries for deleted **files** (`283-286`), never
symbols that disappeared *within* a surviving file.

**Failure scenario:** file `A` calls `foo` defined in `B`, producing edge
`A → B::foo`, stored under `A`'s manifest entry with `B::foo` in its node list.
Rename/delete `foo` in `B` (leave `A` untouched) and re-scan:

1. `A` is unchanged → skipped → `B::foo` is restored from the old graph, and the
   `A → B::foo` edge is restored.
2. `B` is dirty → re-extracted → produces `B::bar`, but never removes `B::foo`
   (it lives in `A`'s manifest entry, which is never rewritten while `A` is
   skipped).

Result: the graph keeps a ghost `B::foo` node and an `A → B::foo` edge that no
longer exist in source. Because **both** endpoints are present, the dangling-edge
check in `validate.py:119-126` passes, so `scan_validated_graph`'s
non-incremental self-heal fallback (`native.py:63-65`) never fires. The ghost
persists on every future incremental scan until a full `graphgraph scan --rebuild`.

**Reachable in production:** `incremental=True` is the default for
`scan_validated_graph` / `ensure_native_graph`. No crash (renderers now defend),
but the compiled packet can contain symbols/edges that don't exist — the exact
"hallucination surface" the engine is meant to eliminate. Traced statically (not
runtime-reproduced, since symbol extraction needs the tree-sitter/regex frontend).

**Fix options:**
- When restoring a skipped file, only restore endpoint nodes that a *dirty* file
  hasn't just re-defined — or, simpler, restore only nodes the skipped file
  actually **owns** (`find_file_for_node(nid) == rel`) and re-resolve foreign
  edge targets against the freshly-built node set, dropping edges whose target
  is gone.
- Or store cross-file edges under *both* endpoints' manifest entries so a change
  to either file invalidates the edge.
- Or add a final prune pass that drops edges/nodes whose owning file no longer
  defines them after merge.

---

## Scope / what held up

Everything else reviewed held up: core graph / PageRank / personalized PageRank,
`Graph.expand`, search scoring, the context/packet pipeline, io JSON
serialization, the native binary `.gg` (GGB3/GGB2) save/load round-trip, the
`TopologicalKVCache` dependency-hash invalidation, and the graph/packet
validators. Edge-subset invariants are maintained through the normal
`expand_context` path, and the division/index sites are properly guarded.

Two minor, non-bug observations (noted, not worth fixing):
- `TopologicalKVCache.get` (`cache.py:68-70`) refreshes `graph_mtime` in memory
  after a successful dependency-hash re-check but doesn't `save()`, so the next
  process re-hashes the deps once more. Pure perf, not correctness.
- `Graph.structural_signature`'s own cache is keyed only on
  `(len(nodes), len(edges))` (`core.py:288-289`); a same-count in-place mutation
  would go unnoticed. Not live in the CLI/MCP flow because graphs are loaded
  immutably per invocation (a fresh `Graph` object each time).
