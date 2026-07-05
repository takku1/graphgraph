# NEWFINDINGS.md

Static-analysis bug review of the GraphGraph main program. Two real bugs found
(both confirmed), plus one related defensive-hardening note.

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

## Scope / what held up

Everything else reviewed held up: core graph / PageRank, search scoring,
`Graph.expand`, the context/packet pipeline, and io serialization. Edge-subset
invariants are maintained through the normal `expand_context` path, and the
division/index sites are properly guarded.
