# Planned work / backlog

Every open item identified across this project's review sessions, in one
place, prioritized. This is a backlog, not a roadmap commitment — per
[`rigorous-framing.md`](rigorous-framing.md), nothing here gets promoted to
"done" without a benchmark or a concrete repro backing it, same as
everything else in this codebase.

Status key: `[ ]` not started · `[~]` scoped but not built · `[x]` done
(moved to [`docs/bugs/REALFINDINGS.md`](bugs/REALFINDINGS.md) once shipped).

## Priority 1 — small, scoped, cheap to try

- [x] **Consolidate CLI/MCP shared defaults into one source of truth.**
  Found by tripping over the same bug class three separate times this
  session: `query --show-stats` existed on the CLI but not the identical
  MCP tool; MCP `validate_packet` couldn't validate a graph file the way
  CLI `validate` could; and `max_nodes`'s default value was hardcoded
  independently in `cli/parser.py` (4x), `mcp/server.py` (5x, including
  tool-schema description text), `scanner/core.py` (3x), and
  `services/native.py` (5x) — 17 places that could (and did) silently drift
  out of sync. Fixed by adding `DEFAULT_SCAN_MAX_NODES` as a single
  constant in `scanner/files.py` (exported via `scanner/__init__.py`) and
  updating every one of those 17 sites, plus the generated `AGENTS.md`
  skill text and both `doctor`/`cmd_scan` warning messages, to reference it
  instead of restating the literal. Verified end-to-end: `graphgraph scan
  --help` now shows the constant's live value in its help text.

- [x] **Well-named-identifier lexical scoring bonus** (from
  [`prior-art-research.md`](prior-art-research.md), Aider's repo-map).
  Added `identifier_quality_bonus` (`retrieval/search.py`): segments a
  label by snake_case/camelCase word boundaries, gives 0 bonus to
  single-segment or generic placeholder names (`x`, `tmp`, `data`, ...),
  and a small additive bonus (capped at 3.0, an order of magnitude below
  an exact-match-tier bonus) scaling with segment count for multi-word
  descriptive identifiers. Verified no regression: diffed a fresh canonical
  benchmark run against the last baseline across all 408 rows on every
  deterministic metric — zero differences (the synthetic corpus doesn't
  exercise close-tie ranking between competing candidates at this scale,
  same caveat as the fact-density change). Proven directly by two targeted
  tests instead: a unit test on the scoring function, and an integration
  test showing `resolve_modified_node_ids` outranks a generic `x` function
  when both otherwise match a query equally.

## Priority 2 — bigger, needs a concrete use case first

- [x] **Time-scoped query classes — built a scoped, real version.**
  graphgraph already had the bitemporal bones (`Edge.valid_from`/`valid_to`,
  `Node.created_at`/`updated_at`, an append-only operation log, and
  git-history-derived `fixes`/churn edges), but reading every entry in
  `graph/traversal.py`'s `POLICIES` table confirmed no query class
  prioritized that data at all. Added `recent_changes`: a query class that
  surfaces already-existing commit/`fixes` history for a scoped file,
  verified live against this repo's own history (see
  `docs/bugs/REALFINDINGS.md`, Session 5). Deliberately did NOT build the
  bigger "what did dependents look like as of commit X" idea — that
  genuinely needs new infrastructure (replaying/indexing graph state per
  commit), not just exposing existing data, and stays out of scope.

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
  **Note:** this is about missing synthesis *across* levels. The related
  but distinct "same fixed detail regardless of project size" gap *within*
  one level is now fixed — see `recommend_facts_per_node`
  (`planning/shape.py`) in `docs/bugs/REALFINDINGS.md`.

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

- **Roost-style signing for the plugin/marketplace distribution path**
  (from the job-posting concept list) — investigated the actual mechanism
  in `cli/install.py` before building anything: the Codex `marketplace.json`
  entry is hardcoded to `"source": "local"` and the plugin bundle is
  generated on-disk by `graphgraph install` (code the user already ran and
  trusts), then consumed by the Codex client on the same machine. There is
  no remote/downloaded plugin path anywhere in the codebase — confirmed via
  grep (only one `"source":` construction site, always `"local"`).
  Cryptographic signing solves tamper-in-transit for a fetched artifact;
  there's no transit here to protect. Revisit only if graphgraph ever adds
  a real remote/registry-based plugin source.
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
