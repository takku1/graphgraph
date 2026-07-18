# Bug Review Findings — status log

This file tracks bug-review findings across sessions so we don't re-discover
and re-litigate the same issue twice. Every item below is marked with its
current status. **Before investigating something that smells like a known
issue, check here first.**

Status key: `[x]` fixed and committed · `[~]` fixed, not yet committed ·
`[ ]` deferred/open, with reasoning.

This file is a status log of *specific bugs found and fixed*. For the
forward-looking backlog of open ideas/gaps (new features, research
directions), see [`docs/planned-work.md`](../planned-work.md) instead.

## Session 6 (2026-07-17) — packet-format unification + dogfood-finding verification

- [~] **Packet format unification.** Merged the near-identical
  `render_gg_max`/`render_gg_lex` into one `render_gg(*, lexical, facts)`
  (`packets/renderers.py`); the old names are thin wrappers. Removed the
  disproven, non-weight-bearing `tensor`/`csr_arrays` renderer entirely.
  Hard-renamed the format vocabulary `gg_max`→`gg`, `gg_max_hybrid`→`gg_hybrid`
  across all src+tests (no alias; legacy `gg_max` now raises). `render_packet`
  is now a dispatch table. 411 tests green; verified byte-identical output for
  every legacy variant. Refreshed the installed global/Codex/Gemini skills to
  the new vocabulary.
- [~] **Closes prior open item `render_tensor_array` O(n²) matrix** (see the
  two `[ ]` entries below): the renderer, its routing, exports, and tests were
  removed this session, so the format no longer exists on any path — not just
  unreachable from the planner. Superseded/resolved.
- [~] **Re-verified prior open item `validate_gg_max` hybrid-detection edge
  case** against current code: for a `kind="unknown"`, no-facts node,
  `render_packet(..., "gg")` and `"gg_hybrid"` are **no longer byte-identical**
  — the `#gg` vs `#gg_hybrid` header disambiguates them and `validate_packet`
  labels each correctly. Non-issue for engine-produced packets. Resolved.
- [~] **GG-ITER-03 (homonym anchor contamination) — verified + regression
  locked.** Reproduced the leak (the intent word "affected" ranks an unrelated
  `affected_packages` above the correct test), confirmed the fix is
  defense-in-depth (`structural_anchor_query` strips planner vocab *and* anchor
  selection drops it), and added a teeth-proven test in `test_locus_findings.py`
  (asserts the homonym is a real candidate first, so it can't pass vacuously).
- [~] **GG-ITER-04 (facet unfulfilled despite in-packet evidence) — verified +
  regression locked.** Confirmed the domain-equivalence mapping in
  `_facet_evidence_queries` credits `min_promotable_candidates` for "yield",
  `rejects_parent_traversal` for "unsafe path", `load_and_run` for "running
  loaded cases"; teeth-checked (all unfulfilled if the mapping is neutralized)
  and locked in `test_locus_findings.py`.
- [~] **`project_status` graceful cold-repo status** (slice-round finding #1,
  `2026-07-17-locus-blackbox-slice-implementation-round.md`). A status probe is
  the natural first call on a fresh repo, but `build_project_status` let
  `find_graph_path`'s `FileNotFoundError` surface as an MCP `-32000` crash. Now
  returns an actionable `{"status": "no_graph", "next_action": "build_graph", …}`
  (and `"ambiguous_graph"` for the multi-graph case, preserving the deliberate
  refuse-ambiguous stance as a status, not a crash). Fixed at the shared service
  layer so CLI `status` and the MCP tool both benefit; `cmd_status` renders it.
  Regression test in `test_cli_mcp.py`.
- [~] **Build-receipt docs counters were misread as "no docs"** (slice-round
  finding #2). `phase_profile.docs_files` counts documents *parsed into
  sections* (0 on repos where markdown falls back to file-level), which read as
  "docs missing" even when doc-kind nodes landed. The receipt now also reports
  `doc_nodes` (what actually landed), reusing `graph_shape` so it agrees with
  `project_status`. Regression test asserts the two surfaces match.
- [~] **`remove_graph_files`/`update_graph_files` cryptic `-32000: 'paths'`**
  (live friction). Both handlers did a bare `args["paths"]`, so omitting the
  required arg surfaced only the key name. Added `_require_paths()` with an
  actionable message (names the tool + what to pass; rejects non-list too), and
  documented the `paths` arg in the skill (it wasn't mentioned). The MCP schema
  already marked it required; the server no longer assumes the client enforced
  it. Regression test in `test_cli_mcp.py`.
- [~] **`project_status`/build receipt couldn't say whether symbol extraction
  happened** (live friction). An incremental scan that preserves prior symbols
  rebuilt metadata with the default `frontend="files"` (the symbol block that
  sets the real label is gated on `dirty_files`), so a 6,900-node symbol graph
  reported `frontend: "files"`. Fixed both ways: the scan now inherits the prior
  graph's `frontend` label on refresh (fresh extraction still overwrites), and
  `project_status` now reports a content-derived `symbol_extraction`
  (`present`/`symbol_nodes` counted from node kinds — authoritative even if the
  label is stale). Regression test asserts symbols are detected despite a
  `frontend="files"` label.
- [~] **Systemic MCP input validation + `source_snippets` composability**
  (blackbox-eval-2026-07-18, BUG-1/BUG-2). Several handlers did a bare
  `args["x"]`, leaking cryptic `-32000: 'starts'` / `-32000: 'query_class'`
  KeyErrors that told a caller nothing. Added `_validate_required_args()` at the
  dispatch boundary (`handle_tools_call`) that checks every tool's declared
  `required` against the schema and names each missing arg with its allowed
  values -- fixes these two and any future tool at once. Also made
  `source_snippets` accept `node_ids` (the `id` field `search_nodes` returns) so
  the two tools chain, validated before graph resolution, and enriched the
  `query_class` schema descriptions with the class list. Regression tests in
  `test_cli_mcp.py`.
- [ ] **LIM-1: Rust reverse/registration edges** (blackbox-eval-2026-07-18) --
  `reverse_lookup`/`blast_radius` miss construction/registration sites
  (`Box::new(T)`, `T::new`) and in-file free-function callers. Suggested tractable
  step: capture type-construction sites and free-function call sites as
  *candidate* edges (below full receiver inference). Shared with
  `code-review-graph` (not a regression); part of the member-call substrate work.
  UX-1 (#gg legend) is intentionally deferred: adding per-packet legend tokens
  would undercut the measured terseness the same eval praises (STR-3); the legend
  lives in `describe_formats` + the skill.
- [ ] **Eval harness renders a reimplementation, not the real engine**
  (validated this session): `benchmarks/context_graph/protocol_benchmark.py`'s
  `render_packet` reimplements every format inline from `idx` dicts and does not
  import graphgraph's `render_gg`/`render_packet`. So the interpretability /
  model-reasoning eval would validate a parallel copy, not production output,
  and does not reflect the `gg` rename or `gg_lex` provenance. Making the eval
  faithful means rewiring it to the real renderers — its own focused pass, and a
  prerequisite for trusting any `gg`-vs-`gg_lex` answer-quality result.
- [~] **`doc_summary` silently returned file pointers on docs-less graphs**
  (slice-round #5, round 2). Root cause validated: doc grounding *works* — a
  graph built with `docs=true` produces `section`/`paragraph` nodes and
  `doc_summary` retrieval surfaces the prose. The friction was building without
  docs (MCP `build_graph` defaults `docs=false`), so only file pointers exist.
  Retrieval now emits an actionable `document_extraction` hint (content-derived:
  no section/paragraph nodes ⇒ "rebuild with docs=true") instead of degrading
  silently. Regression test in `test_locus_findings.py`. NOTE: markdown
  section *parsing quality* (tree-sitter-markdown) is a separate feature; the
  existing paragraph extraction already grounds.
- [ ] **Language generality validated ("any code, not just Rust"):** basic
  symbol extraction (defs/contains/calls|calls_candidate) works across Python,
  JS, TS, Go, Rust today — orientation is not Rust-only. What *is* Rust-specific
  is the advanced **receiver-type-inference** pipeline (`impl`/trait resolution,
  method-owner, struct-field and return-type inference in `scanner/frontends.py`,
  gated by `suffix != ".rs"`) that turns `calls_candidate` into resolved member
  calls. Generalizing it is a per-language type-inference effort — the deep
  substrate item — not a quick fix; other languages degrade gracefully to
  `calls_candidate` edges.
- [ ] **Not fixed, correctly deferred (validated this session):** GG-BB-002 /
  GG-BB-004 natural-language multi-hop and affected-test *recall* gaps are real
  but honestly reported (`answerability.status = incomplete`) and are eval-gated
  recall tuning on the live Locus graph, not crisp bugs. The `affected_tests`
  missing runnable-command / `covers` receipt is downstream of member-call
  resolution (no covering edge exists to build the command from). Communities
  (Leiden/CPM), unfinished-work discovery, and the live-LLM answerability eval
  remain research/benchmark-gated — not session fixes.

## Session 5 (2026-07-11) — backlog cleanup, recent_changes query class, full-graph mode

- [x] **CLI/MCP defaults consolidation** (Priority 1 backlog item). Added
  `DEFAULT_SCAN_MAX_NODES` as a single constant in `scanner/files.py`
  (exported via `scanner/__init__.py`); updated all 17 places the `5000`
  default was previously hardcoded independently (`cli/parser.py` x4,
  `mcp/server.py` x5, `scanner/core.py` x3, `services/native.py` x5) plus
  the generated `AGENTS.md` skill text and both `doctor`/`cmd_scan`
  warning messages, to reference it instead of restating the literal.
- [x] **Well-named-identifier lexical scoring bonus** (Priority 1 backlog
  item, from Aider's repo-map). Added `identifier_quality_bonus`
  (`retrieval/search.py`): segments a label by snake_case/camelCase word
  boundaries, 0 bonus for single-segment/generic-placeholder names, a
  small additive bonus (capped at 3.0) scaling with segment count for
  multi-word descriptive identifiers. No regression on the canonical
  benchmark (408 rows, zero diffs); proven directly by a unit test on the
  scoring function and an integration test showing a descriptive name
  outranks a generic one when otherwise tied.
- [x] **Roost-style plugin signing — resolved as not applicable.**
  Investigated the actual mechanism in `cli/install.py` before building
  anything: `marketplace.json`'s `"source"` is hardcoded to `"local"`
  everywhere (confirmed via grep, only one construction site) — the
  plugin bundle is generated on-disk by code the user already ran and
  trusts, then consumed by the same-machine Codex client. No remote/
  downloaded plugin path exists to sign against. Documented and moved to
  the "not a gap" section of `planned-work.md`.
- [x] **`recent_changes` query class — a scoped, real version of "time-
  scoped queries."** `extract_commit_history` already puts commit nodes +
  `fixes` edges into the graph when `history=True`, but reading every
  entry in `graph/traversal.py`'s `POLICIES` table confirmed no query
  class listed `"history"` in `preferred_families` or `"fixes"` in
  `preferred_relations` — those edges only ever survived as unprioritized
  weak-edge-limit leftovers. Added the `recent_changes` query class
  (`direction="in"`, matching `reverse_lookup`'s reasoning for finding
  incoming edges) plus budget/packet-choice defaults. Verified live
  against this repo's own real git history. **Found a second, live bug
  along the way**: `retrieve_context`'s "Ephemeral Session Layer"
  unconditionally injects every currently-*dirty* file as an extra
  anchor for every query class, which drowned out `recent_changes`'
  one deliberate anchor exactly on a repo under active development (15
  dirty files at the time) -- precisely when "what recently changed
  here" is most useful. Fixed by skipping that injection for
  `recent_changes` specifically; added a regression test proving the
  skip is scoped correctly (still active for other query classes).
- [ ] **Deductive-reasoning layer and hierarchical summarization** —
  investigated both honestly; correctly still not built. Neither had a
  use case scoped small enough to build responsibly in this pass (both
  would need genuinely new infrastructure, unlike `recent_changes` which
  only unlocked already-existing data). Left deferred in `planned-work.md`
  rather than forced.
- [x] **Full-graph rendering — found and fixed a real validation bug,
  then added an explicit "give me everything" mode.** Testing "load the
  entire graph, no query scoping" (something no existing test/CLI path
  exercised) surfaced a genuine bug: `validate_gg_max` detected packet
  sections by searching for `[r]`/`[n]`/`[e]` as bare substrings anywhere
  in the packet text. A doc-scanned concept node whose label happened to
  literally contain those characters (found for real in this repo: a
  concept node capturing an example packet string verbatim from a
  docstring/comment) corrupted parsing for the entire rest of the
  packet. Fixed by anchoring detection/splitting to the renderer's actual
  structural guarantee (these markers are always standalone lines,
  confirmed directly in `packets/renderers.py`) via `_has_marker_line`/
  `_split_on_marker_line`, instead of substring search. Verified with a
  repro that fails without the fix. Full graph (3,253 nodes / 18,110
  edges) now renders and validates correctly (~40ms total).

  Added `render_full_graph` (`services/context.py`) as an explicit
  escape-hatch mode -- `graphgraph final --full-graph` (CLI) and a new
  `full_graph` MCP tool -- deliberately not the default path (raises
  `FullGraphTooLargeError` above a token guard, default 20,000, unless
  raised/disabled). On this repo the full graph costs ~80,000 tokens
  vs. ~100-800 tokens for a real scoped query -- confirms the value of
  query-scoping is inherent to the retrieval design, not something a
  smarter full-graph encoding could close.

## Session 4 (2026-07-11) — real-world usage findings + dogfood pass + dynamic detail density

Two sources: (1) a user's real-world test of graphgraph against a large C
codebase (a game decompilation project), reporting concrete false negatives;
(2) an actual dogfood pass using graphgraph's own tools (`doctor`,
`search_nodes`, `source_snippets`, `project_status`) to navigate this repo,
not just reading source looking for bugs.

- [x] **Silent scan truncation (major).** `collect_files` (file-count cap)
  and both symbol extractors silently dropped everything past their cap
  with zero indication — root-caused to `max(500, max_nodes*5)` = exactly
  10,000 at the old `max_nodes=2000` default, the same "suspiciously round"
  number the user observed independently. A function with 469 real call
  sites had zero caller edges and didn't even appear in `search_nodes`
  because its file was processed after the cap was exhausted. Fixed by
  threading a `truncated` flag through `collect_files`/`ExtractionResult`/
  `scan_directory`'s metadata; `graphgraph scan` now prints an explicit
  WARNING, and MCP's `build_graph`/`update_graph_files` surface the same as
  JSON fields. Raised defaults (file cap 2000→5000, symbol multiplier
  ×5→×20) and fixed the same `2000` default hardcoded independently in
  three more places (`mcp/server.py` ×2, `services/native.py`).
- [x] **Function-pointer/callback calls invisible to the call graph.** A
  function invoked exclusively via callback registration
  (`SetMainCallback2(CB2_InitBattle)` in C) read as having zero callers,
  since static call-graph detection only recognizes `name(...)` call
  sites. Verified the exact tree-sitter node shape empirically for C/JS/
  Python before implementing (all three expose a call's arguments via
  `child_by_field_name("arguments")`). Added a weak `references` edge (not
  `calls`) for any bare-identifier argument matching a known function,
  including Python's `func=callback` keyword-argument idiom (`set_defaults
  (func=cmd_scan)`), which needed unwrapping a `keyword_argument` node's
  `value` field. Verified live: 191 real edges found in this repo's own
  graph.
- [x] **Dogfood pass found 4 more real gaps**, from actually using the
  tools: (1) the registered MCP server was running stale code (inherent to
  how MCP works, not fixable, but worth knowing — restart after upgrading);
  (2) `doctor` never checked the graph's own truncation metadata despite
  being the "is something wrong" diagnostic surface, and had a stale
  "default 2000" reference; (3) `project_status` had the identical gap;
  (4) `source_snippets` printed a confusing "No readable source path for
  node" block for a doc-derived "concept" node sharing a label with the
  real code match, right next to the useful result. Fixed all four; also
  caught the same stale `2000` default baked into the generated `AGENTS.md`
  skill content (`install.py`).
- [x] **Dynamic per-node detail density.** Confirmed via grep that every
  hybrid packet renderer hardcoded `node.facts[:2]`/`[:3]` — a fixed
  constant regardless of whether the packet held 5 nodes or 500, so
  "smaller project = more detail per thing" was never a deliberate
  behavior, just less competition for a static budget. Added
  `recommend_facts_per_node` (`planning/shape.py`): scales the per-node
  fact allowance down as selection size grows (`max_facts/sqrt(node_count)`,
  clamped to `[1, max_facts]`). Wired into all 4 hybrid renderers plus the
  `stats.py` token-cost proxy. The exact curve/constant are explicitly
  flagged as provisional (no benchmarked per-fact token-cost term exists
  yet to fit against, unlike `estimate_gg_max_tokens`'s node/edge
  coefficients) — same honesty pattern as the `ambiguous` threshold in
  session 3. Verified no regression: diffed a fresh run of the canonical
  benchmark (`canonical_results/`) against the committed baseline across
  all 408 rows on every deterministic metric (tokens, node/edge/path
  recall, irrelevant ratio) — zero differences. The synthetic corpus
  doesn't populate rich facts, so this confirms no regression rather than
  proving the feature's real-world effect; that's proven separately by two
  targeted unit tests (`recommend_facts_per_node`'s monotonic scaling, and
  a render-level test: 5 facts shown for a 1-node selection vs ≤2 for a
  60-node selection).

## Session 3 (2026-07-11) — grep-vs-graphgraph measurement + performance fix

See [`docs/retrieval-confidence-routing.md`](../retrieval-confidence-routing.md)
for the full writeup. Summary:

- [~] **Performance:** `load_any()` (`io/core.py`) reloaded and re-parsed the
  graph file from disk on *every* MCP tool call, even within one long-lived
  server process, discarding the advantage of not being a fresh CLI
  shell-out. Added an mtime+size-fingerprinted in-memory cache. Measured
  end-to-end through the real `dispatch()` entry point: cold first call
  ~300ms, every subsequent call on an unchanged graph ~15-18ms (down from
  ~800-1300ms per call before) — now comparable to or faster than `git
  grep` for exact-symbol lookups. Verified safe by confirming (via direct
  code read) that every mutator in `graph/operations.py` returns a new
  `Graph` instance rather than mutating in place, so sharing the cached
  object across callers can't cause cross-call contamination.
- [~] **New feature:** `search_nodes` (MCP) now returns `top_score_gap_ratio`
  and a provisional `ambiguous` flag (ratio < 1.3), giving callers a
  machine-checkable confidence signal instead of silently trusting
  whichever match happened to sort first. Grounded in both an 11-query
  measured benchmark against this repo and published confidence-gated
  retrieval-routing research (see the doc's Sources section). The 1.3
  cutoff is explicitly flagged as provisional, not calibrated.
- [~] Updated the generated `AGENTS.md`/`SKILL.md` guidance (`cli/install.py`)
  with the resulting decision rule: grep is still fine for exact-symbol
  lookups with no relationship question attached; escalate to graphgraph
  specifically for callers/dependents/blast-radius/"how does X work"
  questions, using `ambiguous`/`top_score_gap_ratio` to decide whether to
  trust a single top hit.
- [~] **"Instant file:line" gap:** every symbol/section node's source line
  was already recorded by the scanner, but only as an "L<N>" token smuggled
  inside `Node.summary`, decoded by exactly one consumer
  (`services/snippets.py::_node_line` via its own private regex).
  `search_nodes`, `query_context`'s anchor list, and the CLI's
  `--show-anchors` text output all showed the file path but never the line
  — an agent had to make a second `source_snippets` round-trip just to
  learn where in the file a match was. Added a proper `Node.line` cached
  property (`graph/core.py`, same pattern as the existing
  `normalized_scope_values` property — no storage/schema migration needed,
  works on every already-saved graph) as the single place that convention
  gets decoded; consolidated `snippets.py`'s duplicate regex into it; wired
  `line` into `search_nodes`'s JSON output, `query_context`'s JSON anchors,
  and the CLI's text anchor listing (now `path:line` instead of just
  `path`). Verified live against this repo:
  `graphgraph query "resolve_modified_node_ids" --show-anchors` now prints
  `src/graphgraph/retrieval/git_utils.py:69` directly in the anchor line.

---

## Session 1 (2026-07-08) — retrieval/scanner core review

Code review of the graph core, operations, IO, search, retrieval/knapsack.

- [x] **Scanner skip rules applied to the *absolute* path, silently producing
  empty graphs.** `scanner/files.py::collect_files` compared `path.parts`
  (absolute) against `SKIP_DIRS` instead of `path.relative_to(root).parts`.
  Any project checked out under `~/repos/x` or `/tmp/x` scanned to zero
  nodes with no warning. **Fixed:** `2df2131`.
- [x] **`search_nodes` returned expired (inactive) nodes** as viable anchors,
  which `expand()` then silently dropped, producing an empty/degraded packet
  with no explanation. `retrieval/search.py::_search_index` had no
  `node.active` filter unlike every other traversal function. **Fixed:** `2df2131`.
- [x] **`KeyError` crash in `build_bfs_tree`** when a start node wasn't itself
  in the candidate set (e.g. an anchor `expand()` dropped for being
  inactive/out-of-scope) but had a neighbor that was. **Fixed:** `2df2131`.
- [x] **Orphan candidates could never be selected by the tree-knapsack** —
  the orphan-DFS loop marked every disconnected candidate as visited
  *before* the code meant to record orphan roots ran, so
  disconnected-but-relevant nodes were silently unselectable. **Fixed:** `2df2131`.
- [x] **Recursive DFS/backtrack in `tree_knapsack.py` could hit Python's
  recursion limit** on a long dependency chain (~1000+ nodes, plausible in a
  2000-node graph). Converted to explicit-stack iteration. **Fixed:** `92b1da5`.
- [x] **`expand()` dropped same-round edges when the node budget was hit**
  mid-round, losing some intra-subgraph edges from the packet. **Fixed:** `99e9288`.
- [x] **Exact-sequence label boost couldn't fire on labels containing
  stopwords** (`search.py`: `terms` tokenized with stopwords removed, but
  `label_term_sequence` kept them — mismatch meant "how to deploy" could
  never match its own label). **Fixed:** `5baf60a`.
- [x] **Duplicate labels in legacy `.gg` text files were silently
  misattributed** — a colliding node got a renamed id, but edges resolved
  via a label→id map that kept only the *last* node per label, collapsing
  both nodes' edges onto one. **Fixed:** `dd2faf1`.
- [x] **`merge_node` left `Node.parent` dangling** after absorbing a node —
  rewrote edges pointing at the deleted node but not `parent` fields naming
  it. **Fixed:** `97a02be`.
- [x] **Qualified `receiver.method()` calls resolved to unrelated same-name
  free functions** (cross-language false-positive call resolution),
  causing actively-used code to read as isolated. **Fixed:** `834e81f`.
- [x] **`Type::function()` / `Namespace::function()` associated-call syntax**
  (Rust/C++) was over-excluded by the above fix, causing a second false-isolation
  read for actively-used code. **Fixed:** `8647cf7`.
- [x] **`negative_query` used hops=0/budget=1**, so it could never show
  connectivity evidence for any node — contradicting its own "is this
  isolated" purpose. Bumped to hops=1/budget=8. **Fixed:** `fdaae45`.

## Session 2 (2026-07-11) — whole-project pass

Triggered by an external multi-reviewer PDF audit
(`docs/notes/graphgraph-collab-review-2026-07-08.pdf` — treat that file's
"4-agent consensus" framing skeptically; its file:line claims were verified
independently before acting on them, not taken at face value). Quick hygiene
fixes plus four parallel subsystem bug-hunts (scanner/concepts,
graph/retrieval/planning, packets/io/storage, cli/mcp/services), each fix
confirmed with a fail-before/pass-after regression test and independently
re-verified against the actual diff (not just "tests pass").

### Hygiene / process (not bugs, but resolved open items)
- [~] Removed confirmed-dead `storage_backends.py` compat shim (zero
  references anywhere in the repo).
- [~] Fixed triple-redundant silent `except Exception: pass` around
  git-metadata lookups (`retrieval/git_utils.py` + two now-removed redundant
  wrappers in `search.py`/`context.py`) — now logs at debug level instead of
  swallowing silently.
- [~] Added a Windows job to CI (`.github/workflows/ci.yml`) — was
  Ubuntu-only despite Windows-centric install/doctor paths.
- [~] Split the 4,256-line single-class `tests/test_graphgraph_core.py`
  into 8 subsystem files (`test_graph_core.py`, `test_packets.py`,
  `test_planning.py`, `test_retrieval.py`, `test_tree_knapsack.py`,
  `test_scanner.py`, `test_io.py`, `test_cli_mcp.py`).
- [~] Fixed misleading "Bellman early-stopping" comment in
  `retrieval/activation.py` — it's a `marginal_utility < 0.005` greedy
  cutoff, no value function, no MDP.
- [~] Added `docs/start-here.md`; linked it and the previously-orphaned
  `docs/rigorous-framing.md` from the README.
- [~] Added `benchmarks/context_graph/canonical_results/` — committed
  output from the one fully self-contained, seeded benchmark
  (`protocol_benchmark.py`), so at least one number in this project is
  checkable from a fresh clone.

### CLI/MCP/services
- [~] `main()` only caught `ValueError`, not `FileNotFoundError` — the CLI
  dumped a raw traceback instead of a clean message on the most common
  failure (no graph built yet). `cli/__init__.py`.
- [~] 5 MCP tool handlers used `args.get(x) or default`, silently
  discarding an explicitly-passed `0` (falsy-zero bug) in favor of the
  default — `source_snippets` (context_lines, max_lines), `search_nodes`
  (limit), `build_graph`/`update_graph_files`/`remove_graph_files`
  (max_nodes). `mcp/server.py`.
- [~] `graphgraph query --show-stats` was rejected while `context
  --show-stats` worked, despite the installer's own generated docs telling
  agents to use it on `query`. Added the flag + wired the same diagnostic
  line. `cli/parser.py`, `cli/commands.py`.

### Packets/IO/storage
- [~] `validate_gg_max`'s hybrid-format detection regex required a
  single-word label before `[kind]`, so any doc-derived multi-word label
  (e.g. "Getting Started") caused a real `gg_max_hybrid` packet to be
  misreported as plain `gg_max`. `packets/validation.py`.
- [~] `save_graph_binary` truncated the destination file immediately on
  open; a mid-write failure (confirmed with an unpaired UTF-16 surrogate)
  destroyed the last good persisted graph instead of just failing the save.
  Now writes to a temp file + atomic replace. `storage/backends.py`.

### Graph/Retrieval/Planning
- [~] `spreading_activation` never checked `node.active` anywhere (starts,
  cached reinjection, or final selection) — soft-deleted nodes could
  resurface via the cross-turn `.graphgraph/activation_state.json` cache.
  `retrieval/activation.py`.
- [~] `path_matches("**/tests/**", ...)` matched **every** path in the repo
  — the leading-wildcard prefix was `""` and `path.startswith("")` is
  always true. Replaced with a proper glob→regex translation.
  `planning/policies.py`.
- [~] `Graph.expand(hops=0)` silently dropped edges directly connecting two
  of the caller's own start nodes, since the traversal loop that normally
  catches those edges never runs at hops=0. `graph/core.py`.

### Scanner/concepts
- [~] C/C++ `ops->process()` pointer-member calls resolved as bare calls to
  unrelated same-named free functions — same bug class as the `receiver.method()`
  fix above, just missing the `->` exclusion. `scanner/ast.py`.
- [~] JS/TS arrow-function detection regex had no required `=>`, so plain
  constants (`const apiUrl = "...";`, `const config = {...};`) were
  misclassified as `"function"` symbols. `scanner/ast.py`.
- [~] Git history parsing split numstat lines on generic whitespace instead
  of `\t`, breaking on renamed files and paths containing spaces, silently
  losing the `fixes`-commit edge for both. `scanner/history.py`.

### Follow-up pass (after re-triaging the deferred list below)
- [~] Regex-fallback extractor (`_EXTRACTORS` in `scanner/ast.py`) had no
  Ruby/PHP entries despite both being declared in `PARSEABLE_SUFFIXES`/
  `SOURCE_SUFFIXES` — files degraded to file-level nodes with tree-sitter
  unavailable. Added `_defs_ruby`/`_defs_php`.
- [~] `cli/install.py` vestigial `if True:` with no `else` — dedented, no
  behavior change.
- [~] Duplicated O(paths × nodes) git-modified-path→node-id lookup,
  independently implemented in both `retrieval/search.py` and
  `retrieval/context.py`. Consolidated into
  `git_utils.resolve_modified_node_ids` (O(nodes + paths)), with a
  regression test confirming the "multiple nodes share one path" case
  (list-per-path, not last-wins) is preserved exactly.
- [~] `merge_graphify` (`io/core.py`) had zero test coverage despite being a
  real, exported public function. Added coverage
  (`test_merge_graphify_enriches_base_adds_overlay_and_dedupes_edges`).
  Still deliberately not wired into `cmd_ingest` — that's a CLI behavior
  decision (merge-by-default vs. explicit flag vs. status quo replace),
  not a bug, and stays a `[ ]` item below.

### Feature-completeness pass (missing/partial functionality vs. what's advertised)
- [~] **Major:** Kotlin/Scala/Swift symbol-level scanning was completely
  broken end-to-end despite being advertised in the README and fully
  supported by `TreeSitterExtractor` in isolation. `PARSEABLE_SUFFIXES`
  (`scanner/files.py`) — which gates whether `_build_graph_from_split` even
  attempts extraction, *before* `select_extractor()` ever chooses
  tree-sitter vs. regex — never included `.kt`/`.scala`/`.swift`. Every
  existing test for these languages called `select_extractor("tree_sitter")`
  directly, so the gap was invisible until an integration test went through
  the real `scan_directory` pipeline. Fixed the suffix list and, for
  defense-in-depth when tree-sitter isn't installed, added regex-fallback
  extractors (`_defs_kotlin`/`_defs_scala`/`_defs_swift`). Verified with a
  script cross-checking `SOURCE_SUFFIXES` against `PARSEABLE_SUFFIXES` and
  `_EXTRACTORS` — no other advertised language has this gap.
- [~] MCP `validate_packet` could only validate rendered packet text — no
  way for an MCP-only agent to validate a saved graph file at all, unlike
  the CLI's `validate` command (which auto-detects and validates the saved
  graph when no packet/stdin is given). Also used `validate_packet()`
  instead of `validate_any()`, so it couldn't even recognize raw graph JSON
  pasted as `packet` text. Fixed to mirror the CLI exactly: `packet` is now
  optional, `graph_path` is a new optional param, and text input routes
  through `validate_any`.
- [~] The generated `AGENTS.md`/`SKILL.md` content (`cli/install.py`, what
  actually teaches *other* agents/clients how to use graphgraph) documented
  only 6 of the 14 real MCP tools, and its `validate_packet` description
  ("not a saved graph JSON file") was already stale even before the fix
  above. Added `source_snippets`, `update_graph_files`/`remove_graph_files`,
  and the four `describe_*` introspection tools to both the AGENTS.md bullet
  list and the SKILL.md table; updated the `validate_packet` description.

### Meticulous re-validation pass (re-checked every remaining deferred item with direct proof, not just re-stated reasoning)
- [~] `scanner/core.py::_get_git_metadata` git-status quoting, previously
  deferred as "no clean repro built" — turned out to be readily testable:
  git's `core.quotepath` escaping is fully deterministic. Built a real temp
  git repo with a non-ASCII filename, confirmed the old code corrupted the
  path into a literal `"notes caf/303/251.md"` string (the quote characters
  and octal escapes leaking straight through), then fixed it properly by
  switching to `git status --porcelain -z` (NUL-separated, never-quoted
  output) with correct handling of the extra token that follows
  rename/copy entries. Added two tests: one for the quoted-path case, one
  specifically guarding the rename-token-skip logic (verified it fails
  without that logic before confirming it passes with it). Also fixed the
  same silent `except Exception: pass` pattern here as `git_utils.py`
  earlier.
- [~] `scanner/doc.py` "mentions" heuristic, previously called "an
  intentional precision/recall tradeoff, not a bug" — re-examined and that
  was too generous. The check was a raw substring test
  (`file_label.lower() in body.lower()`), and file stems are commonly
  short/generic words (`core`, `io`, `app`...). Proved a concrete false
  positive: a doc containing "score" produced a `mentions` edge to
  `core.py` purely because "core" is a substring of "score". Fixed with
  word-boundary regex matching; verified the false positive is gone while a
  genuine mention (`"see core.py for..."`) still produces the edge.
- [ ] `validate_gg_max` residual hybrid-detection edge case — re-verified
  with a direct reproduction rather than just reasoning about it: rendered
  `render_gg_max(..., hybrid=True)` and `render_gg_max(..., hybrid=False)`
  for a node with `kind="unknown"` and no facts, confirmed the two outputs
  are **byte-identical** (`'[r]\n[n]\n1 Widget\n[e]'` both times). This is
  now empirically proven, not speculative — genuinely needs a renderer-side
  format change, still correctly deferred.
- [ ] `render_tensor_array`'s O(n²) matrix — re-verified reachability
  directly: grepped `planning/` for `"tensor"`/`"csr_arrays"` and confirmed
  zero matches, so the empirical planner (`choose_packet`) can never select
  this format; it's only reachable via an explicit `--packet tensor`
  request. Confirmed low-priority, correctly deferred.
- [ ] `Graph.structural_signature()`'s cache fingerprint gap — re-verified
  by reading every mutator in `graph/operations.py`
  (`add_node`/`add_edge`/`expire_edge`/`expire_node`/`merge_node`/
  `add_policy_node`) directly: every one constructs a brand-new `Graph(...)`
  instance rather than mutating in place, and `_structural_sig_cache` is a
  plain instance attribute, so a fresh object never inherits a stale cache.
  Confirmed there is no real code path that can trigger this; correctly
  deferred.

### Deferred / found-but-not-fixed (considered, intentionally left alone — don't re-flag without new information)
- [ ] `merge_graphify` (`io/core.py`) — real logic, now has test coverage
  (see follow-up pass above), but still zero callers/CLI wiring. Not wired
  into `cmd_ingest` because that's a merge-vs-replace behavior decision,
  not a bug; removal isn't appropriate either since it's real, tested,
  exported logic. Leave as an available library primitive until there's a
  concrete decision to wire it in or deprecate it.
- [ ] `validate_gg_max` residual hybrid-detection edge case — see the
  meticulous re-validation pass above for the direct proof; needs a
  renderer-side format delimiter change, which changes the wire format —
  a design decision, not a bug fix.
- [ ] `render_tensor_array`'s O(n²) all-pairs shortest-path matrix — see
  the meticulous re-validation pass above; confirmed unreachable from any
  automatic packet-selection path, low-priority efficiency note.
- [ ] `Graph.structural_signature()`'s cache fingerprint doesn't include
  `node.active` — see the meticulous re-validation pass above for the
  direct verification; no real code path can trigger this.
- [ ] Live-LLM answerability eval (`benchmarks/context_graph/llm_answer_benchmark.py`)
  has never been run/published — needs a paid API key, and is separate from
  graphgraph's actual (local, no-API-key) runtime operation. Deferred to
  the user's discretion, not attempted.
- [ ] The real-project empirical numbers in `docs/empirical-findings.md`
  (e.g. the promoted shape rule's `2.87%`) still depend on external repos
  checked out under `$AIPROJECTS_ROOT`/`resources/`, which aren't part of
  this repo and aren't reproducible from a fresh clone. `canonical_results/`
  (session 2) only closes this gap for the one synthetic-corpus benchmark,
  not the real-project numbers.
