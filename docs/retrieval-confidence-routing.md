# grep vs. graphgraph: a measured decision rule

This documents an actual experiment (not a design guess) into when an agent
should reach for `grep`/`git grep` versus graphgraph, run against this repo
on 2026-07-11. Per [`rigorous-framing.md`](rigorous-framing.md): this is a
small-sample empirical finding, not a fully calibrated production
threshold — treat the 1.3 cutoff below as a documented starting point, not
settled science.

## The wrong question

"Which tool wins?" isn't well-posed. Current field practice (multiple
2026 sources on AI coding agents converge on this) treats code search as a
tiered escalation, not a single choice:

1. **Lexical** (`grep`/`rg`) — zero setup, all-file-type, high recall, the
   default bootstrap action.
2. **Structural** (tree-sitter/ast-grep) — "where does this code shape
   appear."
3. **Graph** (resolved call/usage/impact edges) — "who actually calls or
   depends on this," which no amount of text matching can answer, because
   it requires resolving *which* `process()` a given call site actually
   binds to.

The real question is: **when does an agent's task need tier 3, and is
graphgraph cheap enough that it actually gets used there instead of being
avoided as "slow"?**

## What was measured

Eleven real queries against this repo, four categories, comparing `git
grep` against graphgraph's `query`/`search_nodes`:

| Category | Example | grep | graphgraph (cold CLI) | graphgraph (warm, cached graph) |
|---|---|---|---|---|
| A: exact unique symbol | `resolve_modified_node_ids` | 30ms, 5 precise hits | ~810ms | **~17ms** |
| B: common/ambiguous token | `path` (1483 hits), `active` (157 hits) | 30ms, mostly noise | ~800-1300ms, top anchors tied/low-confidence | ~15-20ms |
| C: relationship question | "what calls `expire_node`" | 50ms, 7 hits, no caller/import distinction | ~1000ms | ~185ms (full packet incl. real call edges) |
| D: natural language, no exact symbol | "how does incremental scanning avoid rescanning" | not applicable | ~875ms | comparable, this is graphgraph's actual strength |

### Finding 1: the ~800ms is process overhead, not search cost

Breaking down a cold CLI invocation:

```
~82ms   Python interpreter startup
~90ms   import graphgraph
~120ms  load_any() -- deserialize graph.gg from disk
~220ms  search_nodes() first call -- git subprocess calls (git diff/git status) populating a process-local cache
~330ms  remainder -- packet rendering, budget planning, expansion
```

None of that is `search_nodes`'s actual scoring work. Once the graph is
loaded and the git-cache is warm — i.e., in a **long-lived process**, not a
fresh CLI shell-out per query — every subsequent `search_nodes` call takes
**~15-20ms**, comparable to or faster than `git grep`.

**The catch:** the actual MCP server (`mcp/server.py`) called `load_any()`
fresh on every single tool call before this investigation, discarding that
advantage even though the server process itself is long-lived. Fixed by
adding an mtime+size-fingerprinted cache to `load_any()`
(`src/graphgraph/io/core.py`) — verified end-to-end through the real
`dispatch()` entry point: first call ~300ms (cold), every subsequent call on
an unchanged graph ~15-18ms. `Graph` is immutable everywhere in this
codebase (every mutator in `graph/operations.py` returns a new instance), so
sharing the cached object across calls is safe — verified by reading every
mutator function directly, not assumed.

### Finding 2: score-gap ratio predicts single-answer confidence

For category A/B queries, the ratio between the top match's score and the
runner-up's cleanly separated "one dominant answer" from "genuinely
ambiguous":

```
resolve_modified_node_ids:  105.5 / 51.2  = 2.06   (dominant)
_defs_kotlin:                81.5 / 40.2  = 2.03   (dominant)
PARSEABLE_SUFFIXES:          45.8 / 14.7  = 3.11   (dominant)
Node:                        27.5 / 15.5  = 1.77   (moderate)
path:                        15.5 / 15.5  = 1.00   (tied -- ambiguous)
active:                      13.3 / 11.7  = 1.13   (tied -- ambiguous)
```

This isn't a novel idea — it's the same principle behind published
confidence-gated retrieval routing (query-performance prediction using
retrieval scores to decide whether to trust top-1 or hedge). See Sources.

Category C/D queries didn't fit this pattern as cleanly: a low score-gap on
a "how does X work" question often reflects several genuinely co-relevant
nodes (a correct outcome), not a failed lookup. The ratio signal is
specifically useful for "does this resolve to one entity," not for grading
architectural/conceptual answers.

## The algorithm (implemented)

`search_nodes` (MCP tool, `src/graphgraph/mcp/server.py`) now returns:

- `top_score_gap_ratio`: `matches[0].score / matches[1].score`, or `null` if
  fewer than 2 matches or the runner-up scored 0.
- `ambiguous`: `true` when the ratio is below `1.3` (provisional cutoff —
  the 11-point sample above puts every genuinely tied case at ≤1.13 and
  every dominant case at ≥1.77, so 1.3 is a documented midpoint, not a
  calibrated boundary).

**Decision rule for an agent:**

1. Already have an exact symbol/string in hand and don't need
   relationships? `grep` is still fine — it's not slower, and graphgraph
   isn't trying to replace it here.
2. Need to know callers, dependents, or blast radius? Use graphgraph.
   Check `ambiguous`: if `false`, trust the top anchor; if `true`, the
   query matched several real candidates — surface them rather than
   silently picking rank 1.
3. Asking a "how does X work" question with no exact symbol? Use
   graphgraph's `query_context`/`subsystem_summary` — this is the case grep
   structurally cannot help with at all, regardless of speed.

## What's still open

- The 1.3 threshold is fit to 11 examples on one codebase. It should be
  re-measured (or replaced with an actual query-performance-prediction
  model) once more usage data exists — don't treat it as final.
- Category C/D need a different confidence signal than score-gap ratio;
  this doc doesn't propose one yet.
- The `load_any` cache fingerprints on `(mtime_ns, size)`. A rescan that
  happens to produce identical file size within the same mtime tick (rare,
  but theoretically possible on coarse filesystems) would serve stale data
  for one call. Not observed in testing; worth tightening if it ever shows
  up.

## Sources

- Query-performance prediction for confidence-aware retrieval routing:
  [EverydayGPT: Confidence-Gated Routing for Efficient and Safe Hybrid GPT-RAG Conversational QA](https://arxiv.org/pdf/2606.11212)
- Tiered lexical/structural/graph search for coding agents:
  [Code search for AI agents: the grep replacement is three tools, not one](https://zzet.org/gortex/grep-replacement-for-ai-agents/)
- [Code Search for AI Agents: ripgrep, ast-grep, or Semantic?](https://ceaksan.com/en/code-search-for-ai-agents-which-tool-when)
