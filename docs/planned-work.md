# Planned work / backlog

Every open item identified across this project's review sessions, in one
place, prioritized. This is a backlog, not a roadmap commitment — per
[`rigorous-framing.md`](rigorous-framing.md), nothing here gets promoted to
"done" without a benchmark or a concrete repro backing it, same as
everything else in this codebase.

Status key: `[ ]` not started · `[~]` scoped but not built · `[x]` done
(moved to [`docs/bugs/REALFINDINGS.md`](bugs/REALFINDINGS.md) once shipped).

## Priority 1 — small, scoped, cheap to try

- [ ] **Consolidate CLI/MCP shared defaults into one source of truth.**
  Found by tripping over the same bug class three separate times this
  session: `query --show-stats` existed on the CLI but not the identical
  MCP tool; MCP `validate_packet` couldn't validate a graph file the way
  CLI `validate` could; and `max_nodes=2000`'s default was hardcoded
  independently in `cli/parser.py`, `mcp/server.py` (twice), and
  `scanner/core.py`/`services/native.py` — three-plus places that can (and
  did) silently drift out of sync. Each instance got fixed individually as
  found, but the root cause (no shared parameter/defaults layer between
  the two surfaces) is still there and will produce the next one. Scope:
  route both `cli/commands.py` and `mcp/server.py` through one shared
  `services/` layer for default values and validation, instead of each
  reimplementing its own copy.

- [ ] **Well-named-identifier lexical scoring bonus** (from
  [`prior-art-research.md`](prior-art-research.md), Aider's repo-map).
  Aider's PageRank personalization gives a well-formed identifier
  (`resolve_modified_node_ids`) a 10x weight over a generic one (`x`,
  `tmp`). Checked directly against `retrieval/search.py`: nothing currently
  distinguishes identifier quality when scoring. Cheapest, lowest-risk item
  on this list — a small bonus based on label length/segmentation
  (snake_case/camelCase word count), testable against the existing
  `benchmarks/context_graph/` suite before promotion.

- [ ] **Roost-style signing for the plugin/marketplace distribution path**
  (from the job-posting concept list). graphgraph already has a
  Codex-plugin-bundle + `marketplace.json` distribution mechanism
  (`cli/install.py`), but zero cryptographic signing or integrity
  verification anywhere in that path — confirmed via direct grep. Lower
  priority than the retrieval-quality items since it's a supply-chain
  concern, not a core knowledge-graph capability, but worth a scoped look
  if the plugin distribution ever needs to be trusted by third parties.

## Priority 2 — bigger, needs a concrete use case first

- [ ] **Time-scoped query classes** (from `prior-art-research.md`,
  Zep/Graphiti's temporal knowledge graph — published 15-point benchmark
  gap over Mem0 attributed specifically to treating time as first-class).
  graphgraph already has the bitemporal bones: `Edge.valid_from`/`valid_to`,
  `Node.created_at`/`updated_at`, an append-only operation log via
  `expire_node`/`expire_edge`, and git-history-derived `fixes`/churn edges.
  What's missing: no query class lets a caller ask a time-scoped question
  ("what did this function's dependents look like as of commit X," "what
  changed in the last N commits touching this subsystem"). The storage
  model supports it; retrieval doesn't expose it. Needs a concrete task
  definition and a benchmark before building — don't build speculatively.

- [ ] **A rule-based/deductive inference layer** (from the "Vektor" concept
  — "knowledge graph, deductive reasoning, hierarchical summarization").
  Confirmed via full-codebase grep: zero inference/rule/derivation logic
  exists anywhere. Everything graphgraph does is graph *traversal*
  (multi-hop expansion, blast radius) — structural reachability, not
  logical deduction. Meta's Glean gets this from a Datalog-style query
  language (Angle); graphgraph deliberately skipped a general query
  language for the LLM-context use case (see `prior-art-research.md`'s
  Glean section) — so this would be a new, different kind of capability,
  not a missing piece of the existing design. Needs a concrete motivating
  example (what would an agent actually ask that requires derived facts,
  not just traversal?) before scoping further.

- [ ] **Real hierarchical summarization** (also from "Vektor"). Read
  `_group_nodes_by_subsystem` and `render_doc_summary` directly
  (`packets/renderers.py`): what's called "subsystem_summary" today is
  pure bucketing by directory-derived name, listing each node's own
  pre-extracted facts verbatim — nothing synthesizes new, more-abstract
  summary text at each level (function → file → subsystem → repo, each
  condensing the level below). This is a bigger feature than it sounds
  (would likely need either an LLM-generated summary cached per subtree, or
  a non-trivial extractive-summarization algorithm) — scope it as its own
  project if pursued, don't bolt it onto the existing packet renderers.

## Priority 3 — hygiene, low urgency

- [ ] **Broader doc-index completeness sweep.** Beyond the docs already
  fixed this session (`rigorous-framing.md`, `hardware_compilation_analogy.md`
  now linked), a background audit found ~18 more files under `docs/` with
  zero inbound references from README or any other doc. Most look like
  intentional scratch/working notes (`docs/notes/*`, `docs/bugs/*`), but a
  few read like real reference material that fell off the index:
  `mathematical_formulations.md`, `tensor_context_architecture.md`,
  `locus_comprehensive_report.md`. Worth a pass to either link the real
  ones or move the scratch ones under `docs/notes/` consistently.
- [ ] **Lower-confidence "unused export" cleanup**, flagged by the same
  audit, not yet verified/acted on: `scanner/history.py`'s `CommitRecord`
  class (exported but only ever used internally by tuple, never imported
  by name) and `retrieval/text.py`'s `identifier_terms`/`node_search_text`
  (exported, zero external callers). Lower confidence than the items
  already fixed this session (`planner.py`, `find_graphify_path`,
  `save_gg_text`, the duplicated `_is_context_symbol`) — these could be
  intentional public-API surface for library consumers rather than dead
  code. Verify each individually before removing.
- [ ] **`TopologicalKVCache` naming** (`runtime/cache.py`) — the class is a
  straightforward LRU + content-hash-invalidation cache; nothing about it
  is actually "topological." Low confidence this is worth touching (the
  docstring is accurate about behavior, so it may just be a legacy name
  from an earlier design) — flagged for a human judgment call, not an
  obvious rename.

## Explicitly out of scope (already resolved as "not a gap")

Kept here so these don't get re-investigated:

- `validate_gg_max`'s residual hybrid-detection edge case — proven via a
  direct repro that hybrid and plain rendering are byte-identical for a
  no-metadata node; needs a wire-format change, not a bug fix.
- `render_tensor_array`'s O(n²) shortest-path matrix — confirmed
  unreachable from any automatic packet-selection path (only via explicit
  `--packet tensor`); low-priority even if touched.
- `Graph.structural_signature()`'s cache fingerprint gap — confirmed no
  real code path can trigger staleness (every mutator in
  `graph/operations.py` returns a new `Graph` instance).
- Live-LLM answerability eval and the real-project benchmark
  reproducibility gap — both need external cost/resources (API spend,
  cloning large external repos) per the user's own steer; revisit only on
  explicit request.
- Meta Glean's Datalog query language, CodeQL's arbitrary-query model,
  Sourcegraph's cross-repo resolution — all consciously different by
  design (see `prior-art-research.md`), not gaps to close.
