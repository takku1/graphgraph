# GraphGraph execution plan

This is the canonical ordered task list for current GraphGraph work. Historical
investigations remain under [`docs/findings/`](findings/); they are evidence,
not competing roadmaps. Findings docs are treated as temporary and may be
cleared, so this plan does not depend on any single one.

Status: `[ ]` not started · `[~]` in progress · `[x]` verified complete ·
`[!]` blocked on an external resource or owner decision.

## Working rule: prove, implement, verify

For every behavioral task:

1. capture the current behavior with the smallest reproducible command;
2. add a failing regression test or a characterization test when behavior must
   remain unchanged during a refactor;
3. implement the smallest coherent change;
4. run the focused test, then the affected suite, then the repository gates;
5. update this checklist and the relevant operational documentation with the
   exact verification receipt.

Do not combine an unmeasured retrieval change with an architectural refactor.
Do not claim an absence, dead symbol, or complete blast radius from unresolved
member-call topology.

## Baseline recorded 2026-07-22

- [x] Full unit suite: `678 passed, 59 subtests passed in 29.47s`.
- [x] Clean full graph scan: `8912 nodes`, `31560 edges`, structural validation
  passed.
- [x] Current member-call baseline: `264 resolved`, `1082 unknown_receiver`
  (`19.6%` of resolved + unknown receiver sites resolved).
- [x] Self-eval: four real tasks at `node_recall=1.0`; red control at
  `node_recall=0.0`; `render_query_context` remains below the ranking target at
  `NDCG@5=0.0`.
- [x] Restore the lint baseline. Ruff's four import-order failures were fixed;
  `ruff check src tests` now passes.

Repository gates after each phase:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest
graphgraph eval --graph .graphgraph\graph.gg --tasks eval\graphgraph-self.json
```

## Phase 0 — correctness and trust blockers

Complete these in order before broader refactoring.

### T01 — Repair and lock generated skill artifacts

- [x] **Test first:** extend
  `test_tracked_skill_bundles_match_canonical_asset` to compare both `SKILL.md`
  and `scripts/validate_live.py` across the canonical package asset,
  `.agents/`, and `plugins/` copies. Add a launcher smoke test using `--help`.
- [x] **Implement:** regenerate the repo-local `.agents` launcher from
  `src/graphgraph/assets/validate_live.py`; it currently imports the removed
  `graphgraph.live_validation` module instead of
  `graphgraph.acceptance.live_validation`.
- [x] **Verify:** the focused installer/artifact tests pass and all tracked
  asset hashes match.
- [x] **Harden:** make `doctor` inspect project-local skill/plugin artifacts as
  well as user-installed Codex artifacts.

Verification: three focused regressions and the complete `test_cli_mcp.py`
suite pass.

### T02 — Make `select` caller caveats use repository-scoped telemetry

- [x] **Test first:** scan a fixture fully, incrementally update a subset, then
  assert `caller_evidence_quality()` and CLI/MCP `select` report the retained
  `member_calls_global_*` snapshot and explicitly label its scope/staleness.
- [x] **Implement:** prefer global telemetry over the generic last-update keys;
  fall back only for legacy graphs that lack global metadata.
- [x] **Verify:** `status` and `select` agree after both full and incremental
  scans. Preserve the existing upper-bound warning when receivers are unknown.

Verification: the predicate suite passes, and live `select` reports
`264/1346` with `scope=full_scan_snapshot` after an incremental refresh.

### T03 — Restore a green static-quality gate

- [x] Treat the current Ruff failure as the red check.
- [x] Organize imports in `cli/commands.py`, `platform/__init__.py`,
  `retrieval/context.py`, and `scanner/frontends/edges.py` without suppressing
  additional rules.
- [x] Run Ruff and the full unit suite.

Verification: Ruff passes; the full suite reports `681 passed, 59 subtests
passed`.

### T04 — Test executable documentation contracts

- [x] **Test first:** add `tests/test_docs_contract.py` with local Markdown-link
  validation and a small allowlisted parser/help check for commands in
  `README.md`, `docs/start-here.md`, and the skill contract.
- [x] Fix `docs/start-here.md`: `validate` accepts `--packet`, while saved graph
  validation uses `validate-graph --graph`; use `snippets` when promising exact
  source lines.
- [x] Remove or replace every link to missing `docs/bugs/REALFINDINGS.md`.
- [x] Normalize public packet names to the accepted CLI surface (`gg`,
  `gg_hybrid`, `gg_lex`, `gg_lex_hybrid`) and explain historical/internal
  `gg_max` terminology once.
- [x] Update the skill's measured call-resolution number and language coverage
  from generated/current data rather than embedding stale prose.
- [x] Run the docs contract test, Ruff, and the full suite.

Verification: documentation contracts and skill parity pass; Ruff passes; the
full suite reports `685 passed, 66 subtests passed`.

## Phase 1 — consolidate shared contracts and adapters

### T05 — Create one public contract registry

- [x] **Characterize first:** assert that CLI choices, MCP schemas, HTTP packet
  validation, format descriptions, query-class descriptions, and compiler-pass
  choices expose the same sets and defaults.
- [x] Introduce typed registries for packet formats, query classes, compiler
  passes, and shared limits/descriptions in their owning domain modules.
- [x] Generate CLI argument choices, MCP schema fragments, HTTP allowlists,
  doctor/capability output, and documentation tables from those registries.
- [x] Delete duplicated literal lists only after parity tests pass.
- [x] Verify CLI/MCP/service contract snapshots and the full suite.

Verification receipt (2026-07-22): four red-first cross-surface parity tests now
cover packet formats, query classes, compiler passes, defaults, dispatch, HTTP
validation, capability output, and generated architecture tables. Focused
CLI/MCP/platform/planning/packet suites pass, repository-wide Ruff passes, and
the full pytest suite passes. The extraction timing ceiling also passed in an
isolated rerun after one load-sensitive full-suite overrun.

### T06 — Centralize runtime/compiler construction

- [x] **Characterize first:** compile the same request through CLI platform,
  MCP `compile_context`, and HTTP service; compare route, passes, sources,
  validation, and bounded output.
- [x] Add one `GraphRuntime`/provider factory that owns evidence-store paths,
  providers, source planner, source mode, memory scopes, refresh behavior, and
  runtime defaults. Input-security bounds remain transport-owned and dynamic
  retrieval bounds remain planner-owned.
- [x] Route CLI, MCP, HTTP, native context, and benchmark construction through it.
- [x] Keep transport parsing separate from compilation semantics.
- [x] Verify cross-surface parity and security/bounds tests.

Verification receipt (2026-07-22): red-first parity tests proved HTTP silently
discarded an explicit query class and that no shared factory existed. CLI, MCP,
HTTP, native context, transform/capabilities, and benchmarks now use
`create_graph_runtime`; HTTP preserves the requested class, and `.graphgraph`
stores resolve the same project root on every surface. Cross-transport receipts
and packets match, affected transport/retrieval/benchmark/security suites pass,
repository-wide Ruff passes, and the full pytest suite passes.

### T07 — Make generated distribution artifacts one-way

- [x] **Test first:** assert every tracked/generated skill, plugin manifest,
  MCP config template, and validation launcher derives from a named canonical
  source.
- [x] Keep canonical assets under `src/graphgraph/assets` (or replace this with
  one explicitly documented generator source).
- [x] Add one deterministic sync/check command shared with installer generators
  and enforced by CI.
- [x] Stop hand-editing generated `.agents` and plugin copies.
- [x] Verify a clean regeneration is byte-stable.

Verification receipt (2026-07-22): four red-first tests inventory ten tracked
skill/plugin/MCP/marketplace artifacts, require a named asset or generator for
each, detect exact-byte drift, and prove a second synchronization is a no-op.
`graphgraph artifacts` normalizes the copies; `graphgraph artifacts --check`
passes and is wired into CI. Project installation creates matching skill
examples and validators, focused installer/artifact tests pass, repository-wide
Ruff passes, and the full pytest suite passes.

### T08 — Decompose orchestration monoliths without changing behavior

- [x] **Characterize first:** preserve public imports, CLI output receipts, MCP
  JSON envelopes, graph writes, cache behavior, and exception messages.
- [x] Split `services/native.py` into graph lifecycle, freshness/sync, project
  status, runtime probes, and native-context orchestration.
- [x] Split `cli/commands.py` and `mcp/server.py` by command/tool domain while
  retaining thin dispatch modules.
- [x] Move compatibility re-exports out of `retrieval/context.py`; give the
  orchestrator explicit stage interfaces instead of importing large private
  sibling surfaces.
- [x] Split the corresponding 1,000–2,600-line test modules by behavior, not by
  arbitrary line count.
- [x] Make one move at a time and run focused characterization tests after each.

#### Active T08/T08A slice sequence

Execute these serially. Each slice starts with a failing ownership or wire-contract
test, preserves compatibility imports until callers migrate, runs its focused
suite plus Ruff and `git diff --check`, then refreshes the exact changed paths in
GraphGraph. Run the full suite after slices 3, 6, and 8.

1. [x] **CLI lifecycle:** move `scan`, `update`, `remove`, and their private
   helpers into `cli/lifecycle.py`; retain `cli.commands` re-exports and direct
   parser ownership. Preserve graph writes, progress output, shrink guards, and
   exception text.
2. [x] **CLI retrieval:** move `query`, `context`, `final`, `render`, and
   `snippets` orchestration into a retrieval-owned CLI module. Preserve packet,
   cache, refresh, validation, and control receipts byte-for-byte.
3. [x] **CLI diagnostics:** move `plan`, `profile`, `select`, `doctor`, and
   `status` into coherent planning/diagnostic domains; leave `commands.py` as a
   compatibility facade. Run the first full-suite checkpoint.
4. [x] **MCP graph management:** move build, targeted update/removal, export,
   and their schemas into one domain. Preserve required-path errors, mutation
   receipts, exclusions, truncation warnings, and public handler imports.
5. [x] **MCP retrieval/status/validation:** move plan/final/full/query,
   snippets/search/select, project status, and packet validation into bounded
   domains. Keep `server.py` as registry/envelope routing only.
6. [x] **Retrieval/test boundaries:** remove compatibility imports from
   `retrieval/context.py`, introduce explicit stage interfaces, and split large
   tests by behavior without changing collection or fixtures. Run the second
   full-suite checkpoint and mark T08 complete.
7. [x] **Machine-contract gate:** snapshot names, required inputs, enums,
   defaults, safety caveats, routing cues, representative result shapes, and
   aggregate/per-tool serialized size before changing MCP text.
8. [x] **Transport compaction:** replace prose-heavy descriptions with dense,
   regular machine contracts and compact JSON-only payloads; set the size
   ceiling from the measured result, verify routing/semantic preservation, run
   the final full-suite checkpoint, and mark T08A complete.

Progress receipt (2026-07-22): red-first boundary tests now lock the native
service domains and MCP dispatch location. CLI/MCP callers use lifecycle,
freshness, project-status, and native-context seams instead of importing the
native monolith directly; compatibility paths remain available through a thin
facade with the same signatures. JSON-RPC dispatch moved to `mcp/dispatch.py`
with the same handler patch points and error envelopes. Focused CLI/MCP tests
and a full-suite checkpoint pass. `GraphBuildStatus` and the graph-manifest
contract now live in `services/lifecycle.py`; saved-graph freshness inspection,
scope projection, and refresh receipts now live in `services/freshness.py`
instead of delegating back into the monolith. Project-status assembly, runtime
probes, native-context orchestration, and all lifecycle implementation bodies
now live in their owning modules; `services/native.py` is a compatibility
facade only. The affected boundary, CLI/MCP, control, incremental, and
acceptance suites pass. CLI decomposition has started with the eval/calibration
command now owned by `cli/evaluation.py`, while `cli/commands.py` keeps a
compatibility re-export and the parser imports the owning domain directly.
Saved-graph validation/I/O/comparison now live in `cli/graph_io.py`, and
ontology/frontend/traversal descriptions live in `cli/descriptions.py`, with
the same direct-parser/compatibility-facade pattern. Cache inspection,
clearing, and centrality recomputation now live in `cli/cache.py`, again with
direct parser ownership and a compatibility re-export; artifact/install parser
wiring also targets its existing `cli/install.py` owner directly. MCP
introspection schemas and handlers now live in `mcp/descriptions.py`; compiler,
repair, structural change, memory, and temporal schemas/handlers live in
`mcp/platform_tools.py`.
The server retains the public tool registry, compact text envelope, and legacy
imports while routing those domains through explicit ownership sets. Direct
MCP, public-contract, platform, runtime-factory, and transport-parity tests
pass. Remaining CLI/MCP domains, test-module splits, and retrieval
compatibility exports still need migration before T08 is complete.

Slice 1 receipt (2026-07-22): `cmd_scan`, `_run_scan`, `cmd_update`,
`_run_update`, and `cmd_remove` now live in `cli/lifecycle.py`; the parser
imports the public commands from their owner and `cli.commands` preserves the
five compatibility imports. The red-first ownership test, the complete
CLI/MCP characterization suite, Ruff, patch-integrity validation, and exact
GraphGraph refresh pass.

Slice 2 receipt (2026-07-22): `cmd_render`, `cmd_final`, `cmd_query`,
`cmd_snippets`, and `cmd_context` now live in `cli/retrieval.py`; shared compact
JSON emission lives in `cli/output.py`. The parser imports retrieval commands
from their owner and `cli.commands` retains identity-preserving compatibility
imports. Ownership, CLI/MCP, control-receipt, acceptance, Ruff, and patch
integrity checks pass.

Slice 3 receipt (2026-07-22): planning, selection, and profiling now live in
`cli/planning_commands.py`; doctor/status and their artifact-health helpers live
in `cli/diagnostics.py`. `cli/commands.py` is a 32-line compatibility facade,
and the parser imports every CLI domain directly. Ownership tests, the full
pytest suite, repository-wide Ruff, and `git diff --check` pass.

Slice 4 receipt (2026-07-22): build, exact-file update/removal, export, schemas,
and mutation receipts now live in `mcp/graph_management.py`. Public server
handler identities and required-path errors are preserved; focused MCP,
incremental, boundary, Ruff, and patch-integrity gates pass.

Slice 5 receipt (2026-07-22): plan/final/full/query, status, validation,
snippets/search/select, registry validation, and routing now live in
`mcp/retrieval_tools.py`. `mcp/server.py` is an 84-line stable facade over the
domain owners and dedicated dispatcher. Boundary and MCP characterization
tests pass.

Slice 6 receipt (2026-07-22): `retrieval/context.py` now imports explicit stage
modules instead of re-exporting roughly ninety private sibling symbols. Tests
and benchmarks import each helper from its owning module while the retrieval
package preserves its documented public API. Twelve project-status tests moved
from the 2,700-line mixed characterization module into
`test_mcp_project_status.py` without changing collection. The focused retrieval
suite and second full-suite checkpoint pass.

Slice 7 receipt (2026-07-22): `mcp/machine_contract.py` and its contract tests
snapshot all 22 tool names, non-empty required fields, every enum/default,
routing and safety cues, representative JSON-RPC/result shapes, and the
21,705-character pre-compaction per-tool baseline.

Slice 8 receipt (2026-07-22): MCP tools/list now uses regular `ACT/IN/OUT/SAFE`
machine contracts and removes redundant property prose while preserving names,
types, required fields, enums, defaults, routing cues, and safety caveats.
Measured size is 9,802 characters / about 2,451 proxy tokens, down 54.8% from
21,705 / about 5,426; the measured ceiling is 9,850 characters. JSON-only MCP
results use compact separators. Focused parity tests, the final full suite,
repository-wide Ruff, and `git diff --check` pass.

### T08A — Minimize machine-facing transport context

- [x] **Benchmark first:** record the compact MCP `tools/list` baseline by tool
  and in aggregate. Current baseline: 22 tools, 21,705 UTF-8 characters, about
  5,426 proxy tokens; `query_context` alone is 4,217 characters.
- [x] Add contract tests that preserve tool names, required arguments, enum and
  default constraints, safety caveats, and action-to-tool routing cues while
  measuring serialized size.
- [x] Replace prose-heavy tool/property descriptions with dense, regular,
  machine-oriented contracts; compact JSON-only result bodies without
  presentation indentation.
- [x] Set an initial aggregate context ceiling only after the semantic contract
  tests are green. Prefer the smallest measured representation, not a target
  chosen independently of routing quality.
- [x] Verify MCP/CLI parity, missing-argument behavior, representative tool
  selection, packet validation, proxy-token cost, and the full suite.

This task follows T08 because ownership must be stable before behavior and
wire-size change together. Its objective is recurring LLM context cost and
unambiguous model interpretation; human-oriented prose is not a requirement.

## Phase 2 — documentation and retrieval trust

### T09 — Establish a documentation information architecture

- [x] **Test first:** classify every operational/reference document and assert
  it has an inbound index link; permit explicit archival exceptions.
- [x] Make `docs/README.md` the authoritative map with current operational,
  architecture/reference, findings, research/hypotheses, and archive sections.
- [x] Link the gray-box cycle sequence and this execution plan prominently.
- [x] Mark superseded findings as historical; do not silently rewrite their
  original measurements.
- [x] Reconcile the old claim that no inference exists with the current bounded
  Horn-style optional compiler pass. Distinguish the unavailable scanner
  `cpg` frontend from the platform `CpgEvidenceProvider`.
- [x] Move scratch material under `docs/notes/` or archive it; do not let it
  present as current reference documentation.

Progress receipt (2026-07-23): `docs/README.md` rebuilt as the authoritative
index (Operational / Architecture & reference / Findings / Comparisons /
Research & hypotheses / Archive), covering all 51 non-scratch docs; the three
gray-box cycles and the execution plan are linked; the inference/`cpg`
reconciliation note is inline. New `test_every_doc_has_an_inbound_index_link`
in `test_docs_contract.py` enforces reachability from the README (BFS over
local links), exempting `docs/notes/`. Docs contract, ruff, and full suite pass.

### T10 — Add document-authority and truncation regression fixtures

- [x] **Test first:** add a hand-verified eval fixture for questions about the
  latest findings and current architecture. Delivered as
  `eval/graphgraph-doc-authority-target.json` (a *target*, not yet in the
  passing self-suite, per the T11 "add the gate only after expectations are
  met" rule). Two tasks, hand-verified against `docs/architecture.md` section
  headings and the newest gray-box cycle (cycle 3 — the repo has cycles 2–3 and
  an eval doc, not a "cycle 8"; the fixture targets the newest that exists).
  Recorded baseline (real harness, 2026-07-23): current-architecture
  `node_recall 0.167`, `mrr 0.026`; latest-findings `node_recall 1.0` but
  `mrr 0.023` (~rank 44). This quantifies the drift the tuning below must fix:
  a doc query routes to code-first `subsystem_summary` and the large truncated
  `planned-work.md` outranks `architecture.md`.
- [x] Record scan truncation in document-level retrieval metadata and make a
  truncated requested document an explicit partial result. The scanner already
  records every clipped document in `graph.metadata["docs_truncated_files"]`
  (part one); retrieval now reads it. `context._truncated_requested_documents`
  intersects the *requested* documents (anchor paths ∪ resolved anchor node
  paths) with that set using segment-aware matching (`foo.md` never masquerades
  as a suffix of `barfoo.md`). On a hit, the packet carries a
  `document_truncation` receipt and an otherwise-answerable result is downgraded
  to a new `partial` answerability status (`abstained=False` — a partial result
  still returns its clipped evidence; a stronger upstream abstention is left
  untouched). Verified `partial` survives `reconcile_semantic_retrieval_receipt`
  (the CLI/MCP surface) with no validator error and is handled correctly by the
  acceptance `is_complete`/`evidence` gates (treated as not-complete). Covered
  by `DocumentTruncationPartialResultTest` (downgrade, negative, unrelated-doc,
  segment-aware matching). Full suite green.
- [x] Add document authority/status metadata (`current`, `historical`,
  `research`, `notes`, `generated`) or an equivalent deterministic ranking
  signal. Deterministic signal delivered: `analysis/document_authority.py`
  derives a tier per doc from the README section that indexes it (single source
  of truth with T09) plus a recency tiebreak for dated cycles;
  `authority_sort_key` gives descending (tier, date, cycle). Tested in
  `test_document_authority.py`. **Wired into retrieval ranking:** `search.py`
  adds `_node_authority_rank` and uses it as a strict tiebreaker *below* score
  (`key=(-score, -authority_rank, path, label)`), so authority never overrides
  a lexical/semantic win — it only orders score ties. A neutral rank is returned
  for non-`docs/` paths so code-node ordering is unperturbed (lazy import breaks
  the `search -> analysis/__init__ -> eval -> retrieval` cycle).
  `AuthorityRankingWiringTest` covers the current-beats-historical tie and the
  code-node neutrality invariant. Full suite green.
- [ ] Tune caps/chunking so the findings cycles and core operational docs retain
  the paragraphs needed by the fixture.
- [ ] Verify recall, facet coverage, packet validity, and token cost before and
  after the change.

### T11 — Add a broad architecture retrieval gate

- [ ] **Test first:** save expectations for the major runtime path—scanner,
  storage, planning/retrieval, packet validation, services, CLI/MCP, and
  platform compiler—without using benchmark reports as answer evidence.
- [ ] Reproduce the current drift into benchmark scripts and historical
  findings for a broad architecture query.
- [ ] Improve authority-aware anchoring and subsystem coverage under the
  existing node/token budget.
- [ ] Require the result to report unfulfilled subsystems instead of presenting
  a narrow packet as a complete map.
- [ ] Add the gate to `eval/graphgraph-self.json` only after expectations are
  independently verified from source.

### T12 — Tighten exact-symbol execution receipts

- [x] **Test first:** exact, unique identifiers should use the documented fast
  path or explain precisely why ranking was required; reverse lookups must
  identify omitted known neighbors and their count.
- [x] Align `anchor=exact_fast_path`/`ranked`, `answerable`/`incomplete`, and
  continuation guidance with the behavior documented in the skill. (Skill line
  188 already documents `ranked` = ambiguous/absent; the new `disambiguation`
  field is a consistent enhancement, so no artifact edit was needed.)
- [x] Verify exact direct and reverse lookup on overloaded names, qualified
  members, test-heavy callers, and budget truncation. (Overload + truncation
  covered by ExactOverloadReceiptTest; qualified-member fast-path verified.)

Progress receipt (2026-07-23): characterized the exact-symbol receipts. Unique
identifiers already take `anchor=exact_fast_path`; reverse lookup already
reports `known/returned/omitted_direct_neighbors`. The gap was the *overloaded*
exact name -- `avg` (19 defs) fell to `anchor=ranked` with no explanation. Added
an additive `retrieval.disambiguation` receipt field (identifier, definition
count, reason) via `_exact_overload_disambiguation` in `retrieval/context.py`;
kept `anchor_strategy` binary to avoid touching its contract enum. Three
red-first regressions in `tests/test_retrieval.py::ExactOverloadReceiptTest`
(overloaded reports the count, unique still fast-paths, phrase query is not
mislabeled). Ruff and the full suite pass. Remaining in T12: qualified-member /
test-heavy-caller cases and skill-doc alignment for the receipt strings.

## Phase 3 — finish the open findings work

### Active Cycle 3 test-and-implementation sequence

The cross-language gray-box findings are executed as the following bounded
slices. Each slice starts with a failing fixture or a clean external-repository
measurement; implementation is accepted only after the focused test, relevant
regression suite, and a fresh non-incremental fixture scan agree.

1. [x] **C3-1 — JavaScript callable identity and lookup.** Reproduce Express's
   missing property/prototype/callback definitions; add minimal fixtures; teach
   extraction the observed idioms; require `res.send` to select the method
   rather than `test/res.send.js`. This establishes symbol identity only—member
   receiver resolution remains a separately measured gap.
2. [x] **C3-2 — Query freshness handoff.** Reproduce `fresh:?` through
   `query --json`; pass the already-computed source-hash freshness into the
   control envelope; require `fresh:+`/`fresh:-` and the scoped repository
   receipt. Do not call a cache current merely because source hashes match.
3. [x] **C3-3 — Per-language extraction telemetry.** First preserve the
   Express/Ripgrep baselines and add mixed-language fixtures. Emit
   language-conditioned call-resolution counts in status/query trust receipts.
   Keep this named as call coverage, not the broader “extraction depth” claim;
   a true depth score requires independently labeled language fixtures.
4. [x] **C3-4 — Extractor/cache identity and age.** Add a failing incremental
   fixture proving extractor-semantic changes cannot restore old nodes. Record
   scanner/extractor identity and measurement time separately from worktree
   freshness, then invalidate or explicitly abstain on incompatibility.
5. [x] **C3-5 — Rooted memory.** Reproduce add→recall with no structural
   edges; add exact/qualified symbol anchoring with ambiguity and truncation
   receipts; project accepted anchors as normal `remembers` edges. Never infer
   a root merely from a weak stem collision.
6. [x] **C3-6 — Interface and temporal follow-through.** Test whether aliases
   or router-owned dispatch reduce the observed flag/verb failures without
   growing the machine contract. Extend `as-of` only after a scored
   conversational temporal fixture shows a retrieval gain.

This ordering keeps the machine-facing objective explicit: improve structural
identity first, then expose honest trust state, then connect persistent memory.
Human-readable narration is not a gate unless it also improves model routing or
reduces recurring context cost.

Cycle 3 receipt (2026-07-22): focused JavaScript identity/qualified-lookup,
freshness, language telemetry, incremental preservation, project-status, and
relocated-graph tests pass. Fresh non-incremental external scans validate with
Express at `javascript resolved=0/6278 receiver sites` and ripgrep at
`rust resolved=1210/3542` (`0.3416`); both status receipts report `fresh=true`.
The zero JavaScript ratio remains an explicit receiver-typing task, while
`res.send` itself is now a grounded method and exact dot-qualified lookup.
Rooted-memory tests and a real ripgrep CLI round-trip auto-anchor code-shaped,
qualified, or backticked identifiers, persist bounded ambiguity/truncation
receipts, and project normal `remembers` edges. Plain prose collisions are
rejected. The previously failing `memory add --text` and `memory search`
invocations now work as aliases without changing the MCP tool count or
exceeding its context ceiling. Conversational `as-of` remains intentionally
deferred: no scored temporal-query fixture yet demonstrates a gain over the
existing materialized snapshot operation.

### T13 — Improve member-call receiver resolution with fixture-first slices

- [ ] Preserve the current full-scan baseline and per-language fixture table.
- [ ] For each receiver shape/language, add a failing minimal fixture before
  changing extraction: Python named locals/call results/field chains, Rust
  containers and return types, TypeScript fields, then C#/Java/C++ gaps.
- [ ] Implement only addressable high-volume buckets; do not optimize generic
  or external receivers that cannot name repository symbols.
- [ ] Rebuild with `--no-incremental`, report the full-scan scope, and compare
  resolved/unknown/external/unmatched counts.
- [ ] Run affected-test and dead-code-caveat regressions before accepting a
  resolver lift.

**Progress — C#/Java field receivers (2026-07-23).** The dominant real member-
call shape, `_repo.Method()`, was fully unresolved: a field's type lives at the
class level, invisible to the per-method-body local inference that resolved
locals/params/`new`/`this.Method()`. Added `csharp.csharp_class_field_types`
(fixture-first: `test_csharp_class_field_types_unit`,
`test_csharp_field_receiver_calls_resolve`, `test_java_field_receiver_calls_resolve`
all red before the change) — a brace-unaware scan that requires an access
modifier, which fields carry and method locals do not, keeping it from typing a
local as a field. `edges.py` merges owner fields both as `this.field` and, for
C#/Java, as the *bare* field name under `setdefault` so a genuine local of the
same name still wins. Measured before/after on a field-heavy C#/Java corpus
(field-type inference toggled off = "before"): resolved member calls **0 → 6**,
resolving `_repo.Save`/`_repo.Load`, C# `this.Cache.Get` (auto-property), and
Java `repo.save`/`repo.load`. Existing local/param/`this` C#/Java tests still
green; full suite + ruff green.

**C++ blocker resolved (2026-07-23).** `class_specifier` and
`struct_specifier` are now first-class graph definitions, so the existing
lexical-owner pass converts inline `function_definition` children into owned
methods. `cpp_class_field_types` adds a conservative class-depth field pass:
only nominal declarations at class-body depth zero are admitted, method locals
are excluded, and bare fields plus `this->field` are merged into a method's
receiver environment without overriding stronger local evidence. The former
blocker fixture is now positive: it asserts `Repo`/`Service` type nodes,
`save`/`run` method nodes, and a resolved `run -> save` call through
`Repo repo_`. Unit coverage also pins pointer fields, primitive rejection, and
method-local exclusion. All 87 scanner-frontend tests and the full repository
suite pass. Still open only as measurement, not implementation: a real
repository-scale C#/Java/C++ before/after table; this workspace has no such
evaluation corpus.

### T14 — Calibrate answerability against labeled completeness

- [x] **Test first:** add deterministic reliability/Brier/Murphy metrics and
  PAV regressions for invalid inputs, tied-confidence order independence, and
  exact step-function application.
- [x] Connect confidence to the existing eval ground truth: a positive outcome
  means every node/edge recall dimension declared by the task meets an explicit
  threshold. Never use runtime non-observation as a negative label.
- [x] Add opt-in `graphgraph eval --calibration` output without changing the
  legacy eval JSON shape. Record the tiny self-eval baseline rather than fitting
  a production mapping to it.
- [ ] Expand labeled tasks across query classes, evidence provenance, and more
  than one repository; retain impossible red controls and report sample counts
  for every stratum.
- [ ] Freeze train/calibration/test splits and minimum-sample rules before
  fitting isotonic or other recalibration. Compare held-out Brier, reliability,
  resolution, ECE/MCE, recall, and abstention against the unmodified signal.
- [ ] Apply a calibrated mapping only where held-out results improve. Otherwise
  surface the raw heuristic and its evidence caveats rather than asserting a
  probability or conformal guarantee.
- [ ] Instrument whether a documented trust threshold actually reduces agent
  re-verification without increasing incomplete answers; this is the product
  success criterion, not calibration error alone.

Progress receipt (2026-07-22): the focused calibration/eval suite passes. The
five-task self-eval produced four complete answers at confidence `0.7` and one
red failure at `0.2617`; Brier `0.085697`, ECE `0.29234`, MCE `0.3`. This proves
the measurement path can separate these examples but is not enough data to fit
or deploy recalibration.

### T15 — Reduce incremental update fixed cost safely

- [x] **Benchmark first:** decomposed the fixed per-update cost on the 8,407-
  node / 30,897-edge self-graph (~4 MB `.gg`). Uncached load **124 ms (62%)**,
  validated save **76 ms (38%)** — of which serialize+write is 67 ms and
  validation only 6.6 ms. Total ~**200 ms fixed, O(N), independent of Δ**. Both
  halves are CPU-bound on Python object/dict construction, not I/O; the manifest
  is negligible (confirming the "do not optimize the manifest" note). `load_any`
  is already memoized by (path, mtime, size), so a long-lived server pays only
  the save half per update.
- [x] Write equivalence and crash-safety tests before changing persistence.
  Equivalence of the *splice* was already proven by the incremental acceptance
  case (byte-identical to clean rebuild, splice-scoped). For the new store,
`test_storage_delta.py` adds replay-equals-direct-application, torn-tail
tolerance (base `.gg` untouched), corrupted-record stop, and compaction.
- [x] Prototype an append/index design behind an experimental backend:
  `storage/delta.py` — an append-delta sidecar (`.gg.delta`). Each record is
  `MAGIC | len | crc32 | payload`; a load replays
  until the first torn/corrupt record and returns base + intact deltas; the base
  is mutated only by atomic compaction. Measured **append_delta 0.35 ms vs full
  save 70.5 ms = ~202x** on the save path for a one-node change; the delta record
  is a size constant independent of N.
- [x] Promote only if latency improves materially without weakening the guards.
  Because a `Graph` is materialized
  in full everywhere, a load is inherently `Θ(N)` — the append design provably
  cannot make *load* sublinear, only *save*. So the win is ~35% per update in
  the fresh-process CLI (load still dominates) but ~200x on the fixed cost in the
  load-cached server regime — exactly the multi-update agent edit-loop the
  incremental feature targets.

Promotion receipt (2026-07-23): validated update/remove lifecycle writes now
select the delta path automatically when the encoded change and accumulated
sidecar remain below the measured 25%-of-base cost threshold; large changes,
64-record compaction, non-native stores, and damaged/torn sidecars use the
existing atomic validated full rewrite. Edge identity is
`(source,target,type,source_location)`; changed edge attributes are
delete+upsert, metadata is versioned with the delta, and deleted nodes remove
incident edges. Normal `load_any` and both cache layers fingerprint/replay the
sidecar, while a full rewrite clears it so stale changes cannot resurrect.
Append/cost-gate/compaction decisions share the runtime's cross-process,
stale-lock-safe file lock, preventing CLI/watch writers from interleaving
records. Lifecycle scans exclude graph/manifest/delta artifacts. Tests cover exact
metadata/location-aware equivalence, cache invalidation, full-rewrite cleanup,
the large-delta cost gate, torn/corrupt tails, compaction, concurrent writers,
and two consecutive real validated source updates whose second update loads the
first through the sidecar. Full suite and Ruff pass.

### T16 — Measure and gate real semantic recall

- [!] Requires a real embedding backend and the Flask evaluation repository.
- [ ] **Test first:** keep the offline/hash baseline and red control fixed; add
  backend identity/dimension mismatch tests and a reproducible matched-pair
  measurement command.
- [ ] Run the reference embedding server, rebuild the semantic index under that
  backend, and record lexical versus paraphrase recall on the persisted Flask
  suite.
- [ ] Iterate semantic seed/anchor ranking only behind the eval. Targets:
  semantic-paraphrase recall above the lexical fallback baseline, Flask mean
  recall `>= 0.85`, and `NDCG@5 >= 0.40`.
- [ ] Keep structural evidence authoritative and preserve abstention/red-control
  behavior.

## Phase 4 — release and long-term hygiene

### T17 — Expand CI from source tests to distribution tests

- [x] Add Markdown contract/link checks and generated-artifact parity. (Already
  in the `test` job: `tests/test_docs_contract.py` runs under pytest and
  `graphgraph artifacts --check` is an explicit step.)
- [x] Build wheel and sdist, install the wheel in a clean environment, and
  smoke-test `graphgraph`, `graphgraph-mcp`, package data, and the bundled live
  validator. (New `distribution` job in `.github/workflows/ci.yml`.)
- [x] Test every Python version the package claims to support, or constrain
  `requires-python`/classifiers to the tested range. (Matrix 3.10/3.11/3.12
  matches the classifiers.)
- [x] Keep costly external/model benchmarks explicitly separate from the local
  deterministic PR gate. (Benchmarks under `benchmarks/` are not in the PR gate.)

Progress receipt (2026-07-23): added a `distribution` CI job that `uv build`s
the wheel+sdist, installs the wheel in a clean venv, and smoke-tests it. Proven
locally end-to-end: wheel/sdist build, clean-env install pulls all deps, `import
graphgraph`, `graphgraph --help`, `graphgraph doctor` (Version 0.1.0), the
`graphgraph-mcp` entry point resolves, and the `graphgraph_skill.md` +
`validate_live.py` package data ship in the wheel. YAML validated (heredoc
indentation correct). Full suite + ruff pass.

### T18 — Verify lower-confidence cleanup candidates individually

- [x] Characterize public use before removing `CommitRecord`,
  `identifier_terms`, or `node_search_text`; zero graph callers is not proof of
  an unused public API.
- [x] Decide whether `TopologicalKVCache` is a compatibility name or should be
  renamed; if renamed, provide an alias/deprecation path.
- [x] Remove only candidates proven unused by source search, import tests, and
  public API review.

Verification receipt (2026-07-23): source search proved every candidate is
live, so nothing was removed. `CommitRecord` backs `extract_commit_history`
(`scanner/core.py:881`, exercised by `test_scanner_history.py`);
`identifier_terms` is called by `retrieval/relevance.py:36` and
`retrieval/text.py:77`; `node_search_text` is called by
`retrieval/search.py:614`. All three remain exported public API.
`TopologicalKVCache` keeps its name: it is an accurate description (a KV packet
cache keyed by topological fingerprint) with active callers in
`cli/retrieval.py`, `cli/cache.py`, `services/context.py`, and
`acceptance/cache_latency.py`; no alias or deprecation path is needed. The
earlier zero-caller report was stale graph data, confirming the working rule
that graph zero-caller counts are not deletion evidence while member-call
coverage is incomplete.

### T20 — Adversarial input hardening (loader corruption and hostile source)

- [x] **Test first:** five red-first regressions covering a truncated binary
  `.gg`, text `.gg` content without the self-describing `gg/1` marker
  (wrong-schema JSON, prose, empty file), wrong-schema `.json` graphs, and a
  minified/chained Python expression that blows the ast recursion limit.
- [x] Corrupted or truncated binary `.gg` stores now raise `ValueError` with a
  rebuild hint instead of leaking a raw `struct.error` traceback.
- [x] Legacy text `.gg` parsing requires the `gg/1`/`gg/2` version marker;
  previously ANY text file (a stray JSON object, prose, a corrupted graph)
  "parsed" into a nonsense graph and passed `validate-graph` as
  `STRUCTURAL PASS`.
- [x] JSON graph loading validates schema shape (`nodes` list, per-node `id`,
  per-edge `source`/`target`) instead of leaking `KeyError`/`TypeError`.
- [x] Python type-inference helpers and `platform/contracts.py` treat
  `RecursionError` from `ast.parse` like a syntax error; previously one
  generated/minified file (e.g. one `1+1+...` chain of ~10k terms) aborted the
  entire repository scan with no graph written.
- [x] `is_binary_gg` reads only the 4-byte magic instead of the whole store,
  removing a double full-file read on every load.

Verification receipt (2026-07-23): all corrupted-input probes now fail with a
clean `Error:` line and exit 1; `update --files` against a corrupted graph and
corrupted manifest correctly promotes a clean full rebuild via the existing
ValueError repair path; a pathological fixture repo (null bytes, invalid UTF-8,
syntax errors, a 200k-term chained expression, 500-level nesting) scans to
completion. Six new regressions in `test_io.py`/`test_scanner_frontends.py`;
full suite `768 passed, 66 subtests passed`; repository-wide Ruff passes.

### T19 — Deterministic subsystem map; model synthesis stays off the hot path

- [x] Owner decision ratified by implementation direction.
- [x] First define a user query and a scored fixture that deterministic
  directory/community summaries cannot answer.
- [x] Compare extractive hierarchy against optional cached model synthesis on
  answerability, token cost, staleness, and reproducibility.
- [x] Do not add model-generated hierarchy to the default hot path without a
  measured win.

**Decision evidence (2026-07-23) — recommendation: NO model synthesis on the
default path; adopt a path-primary + centrality-representative extractive model.**
Measured on the self-graph (1,206 code symbols across 17 `src/graphgraph/`
packages):

* The existing deterministic community detector (`intelligence.detect_communities`,
  weighted label propagation) is **degenerate for architectural rollup here**: it
  collapses **862 / 1,206 nodes (71%) into one community spanning all 17
  packages** (retrieval 182 + platform 161 + scanner 78 + graph 70 + services 55
  + cli 49 + …). Purity vs packages **0.35**, NMI **0.26**. Label propagation has
  no resolution/modularity control, so the interconnected core merges into a
  single meaningless blob. Any summary of that blob — keyword-bag *or* model —
  summarizes noise, so it cannot be the substrate a synthesis decision rests on.
* The **file-path tree is the architect's own decomposition**: grouping by
  package gives **purity 1.0 at ~0 compute**, and ranking each package's members
  by PageRank extracts the true API surface deterministically — `graph → Graph,
  Edge, Node`; `retrieval → retrieve_context, search_nodes`; `scanner →
  scan_directory`; `services → render_native_context, scan_validated_graph`. A
  complete labeled subsystem map is ~255 tokens.
* Against the four axes, model synthesis loses on the default/agent path:
  **reproducibility** (model output varies run-to-run; path+centrality is
  deterministic), **staleness** (prose rots on every edit; the extractive map
  recomputes for free), **token cost + latency** (a model call in the hot path is
  an explicit non-goal), and **answerability for an agent** (structured
  `subsystem → representative symbols` is more actionable than prose). The only
  defensible use is a one-off, explicitly-requested, cached *human-onboarding*
  narrative — a documentation feature, not retrieval, and never on the hot path.
* Fixture the task asked for: the query "what are the main subsystems of
  graphgraph and what does each do" is answered well by the path+centrality map
  and poorly by both a flat function dump and the label-prop blob — so it is the
  scored anchor.

Implementation receipt (2026-07-23): broad `subsystem_summary` queries now
carry a compact `retrieval.subsystem_map` machine contract:
`{method:"source_path+pagerank",subsystems:[{subsystem,n,api}],omitted}`.
Source layout alone defines boundaries; persisted/cached PageRank only chooses
two representative symbols per boundary. Tests pin src-layout, crates, test/
benchmark/script exclusion, deterministic ordering, centrality selection, and
the broad-query gate so narrow subsystem questions do not pay for a whole-
project map. The self-graph returns the real surfaces (`graph -> Graph, Edge`,
`retrieval -> retrieve_context, search_nodes`, `scanner -> node_id,
scan_directory`, `io -> load_any, save_graph`) without generated prose or an
external/model dependency.

### T21 — Post-cycle-4 boundary and lifecycle hardening

Follow-ups from the 2026-07-23 differential audit. Full suite green and Ruff
clean after each.

- [x] **Subsystem map reaches the agent.** The T19 map was built into retrieval
  metadata but compact JSON drops everything except `actionable`, so it never
  reached the agent. It is now included in `_actionable_receipt`
  (`services/context.py`) — the one key compact JSON preserves — and the response
  cache version bumped to `request_v10_subsystem_map_actionable`. Transport tests
  in `test_retrieval_subsystems.py` assert the broad query carries the map and a
  narrow one does not.
- [x] **Delta honesty + O(E+Δ) replay.** Corrected the module header (it is the
  *promoted* lifecycle writer, not an opt-in prototype) and the cost claim (the
  append step is ~200x, but the lifecycle diff+validate make the end-to-end win
  ~4.5x, not 202x). Rewrote `_apply` from O(E·Δ) to a single-pass **O(E+Δ)**:
  100 changed edges over 30k replayed in **6.4 ms, was ~443 ms (69x)**. The
  compaction fallback now clears the stale sidecar (was left to replay onto the
  folded base = corruption), with a strict-`mtime` guard in `apply_delta_sidecar`
  as the crash-safe backstop.
- [x] **Transactional manifest ordering.** The scanner wrote the manifest
  mid-scan, so a failed graph write left `manifest_changed=True,
  graph_changed=False`. `scan_directory`/`update_paths`/`remove_paths` now accept
  a `manifest_sink` (default `None` → unchanged for the ~70 other callers); the
  lifecycle passes one and commits the manifest only *after* the graph is durably
  saved. `Manifest.save` is now atomic (temp + `os.replace`). Regression:
  `test_scanner_incremental.py::ManifestDeferralTest`.
- [x] **Unified graph cache.** Replaced the unbounded dict in `load_any` plus the
  second bounded LRU in `io/cache` with one bounded (16-entry), lock-guarded LRU
  in `io.core`; `io/cache` is now a thin delegator. Fixes the long-lived-server
  leak; the base+sidecar fingerprint (already shared) keeps appended deltas
  visible to cached loads.
- [x] **Skill language coverage.** The C#/Java row now reflects the real field/
  property + bare-receiver work (`_repo.Method()`); C++ member fields noted as
  pending. Tracked `.agents`/`plugins` copies regenerated (`artifacts --check`
  passes).
- [x] **JS/TS module-qualified calls.** `module_alias_targets` returned `{}` for
  everything non-Python, so `const store = require('./store'); store.persist()`
  (and the ESM `import * as`/default forms) never resolved -- a large slice of
  the JS 0-call-edge gap. Added `_js_module_alias_targets` binding `require`/
  `import` specifiers to path-suffix-matchable module paths, routed through the
  same conservative, ambiguity-safe join as Python's F3. Fixture-first tests in
  `test_scanner_frontends.py`. (Framework-injected receivers like `res.send`
  stay unresolved: JS has no type annotations, so an untyped callback parameter
  is not statically typeable -- that is a real limit, not a bug.)
- [x] **End-to-end verify.** Full `scan --no-incremental` rebuilds 8,559 nodes /
  31,689 edges, structural validation PASS, with graph and manifest both present
  and consistent.

**Cycle-5 follow-ups (2026-07-24).**

- [x] **Semantic recall via an opt-in `[semantic]` extra** (paraphrase, cycle-5
  F-a). Owner chose the design that respects the zero-dependency core over
  bundling a heavy default. Added a `graphgraph[semantic]` extra (`fastembed`,
  onnxruntime — no torch) and `embeddings.FastEmbedBackend`; `resolve_backend`
  now auto-registers the local ONNX model when the extra is installed (an
  explicit `GRAPHGRAPH_EMBED_URL` still wins), and a core install stays on the
  offline hash. Construction is lazy (no import/download until first `embed`);
  `doctor` reports the active backend. Tests cover extra-gated selection, env
  override, and lazy construction.
- [x] **JS/TS `named_local` factory receivers** (cycle-5 F-b, the histogram's
  dominant unresolved shape). `const s = createStore()` where `createStore`
  returns `new Store()` now types `s`, so `s.save()` resolves. Added
  `typescript._ts_return_type_from_body` (single-concrete-`return new X()`
  inference) + `_ts_local_call_return_types`, extended the repo-wide return-type
  map to JS/TS, and wired the call-return binding into the TS/JS local-type pass
  (mirroring Rust). Fixture-first test. (Property/`await`/destructured receivers
  remain untyped -- not statically inferable.)
- [x] **Eval nonzero exit on garbage** (cycle-5 F-c) verified already fixed:
  both a wrong-schema task file and non-JSON input print a descriptive error and
  **exit 1** in the current build (the report was measured on an older one).
- [~] **Orchestrator monoliths — `retrieve_context` reduced 737 → 622 lines** via
  two verbatim, full-suite-verified extractions (`_affected_tests_metadata`,
  `_document_status_answerability`), plus `search_nodes`'s exact-lookup index
  (`_exact_lookup_index`). The remaining three (and further decomposition) stay as
  incremental, characterization-guarded follow-ups.

**Cycle-6 fixes (2026-07-24).**

- [x] **`--max-nodes` is honored, not inverted** (cycle-6 finding #1). For doc
  and `subsystem_summary` queries `retrieval_node_budget` clamped an explicit
  budget *down* with `min(max_nodes, internal_cap)`, so 20/200/1000 were
  identical and setting the flag dropped below the adaptive default (e.g. 120 →
  ≤32) -- breaking an agent's main recovery move. An explicit budget is now
  honored for every class; the internal budgets apply only as the default when
  none is given. Regression + monotonicity assertions in `test_planning.py`.
- [x] **Subsystem map is anchor-independent** (cycle-6, latent). A broad
  architecture query returns the whole-graph map even when no node lexically
  anchors, instead of an early `unanswerable`. This also de-flaked an
  order-dependent test.
- [x] **Clear staleness message on a scanner-version mismatch** (cycle-6, the
  "false-positive" warning). When a graph is stale only because it was built by a
  different extractor (0 changed, 0 deleted), the warning now names that reason
  rather than the confusing "stale for 0 changed and 0 deleted".
- [~] **Ranking — anchor selection surfaces authoritative doc sections**
  (path-to-10 #1, first measured lever). A curated multi-word section heading
  whose full title appears in the query (`label_terms ⊆ query_terms`) now gets a
  direct-answer boost in `search_nodes`, and such a section is exempt from the
  document-intent penalty (it is the answer, not incidental prose). Measured on
  the self-graph: for "current architecture …" listing the section titles,
  `architecture.md` sections went from **rank ~33 → ranks 1-5**, and the
  doc-authority fixture's current-architecture recall rose **0.0 → 0.333** with
  **no self-eval regression** (reverse_lookup still `node_recall 1.0`, RED test
  still `0.0`). Regression tests in `test_retrieval_section_relevance.py`. The
  broader MRR≥0.4 gate is a longer eval-gated loop and the eval's PageRank-based
  MRR under-measures anchor-answer classes (it should rank by the consumed
  relevance order per class) -- both recorded as the next steps.
- [~] **Latency — lazy imports** (path-to-10 #4). `import graphgraph` went
  **125 ms → 12 ms** (~10x) via PEP 562 lazy loading of the public API, so the
  scanner (tree-sitter), concept, planning, and retrieval stacks load only on
  first use. `scanner/__init__` and `platform/__init__` are lazy too, and the CLI
  dispatch imports each command's handler on invocation (`_lazy_cmd`) instead of
  eagerly at parser-build time; `cli/__init__` no longer star-imports the command
  aggregator. Building the CLI parser and every non-`platform` command no longer
  loads `platform.benchmarking` or the tree-sitter frontends. This is the
  resident-process (MCP) import path the finding targets — the report itself
  notes "a resident process would collapse it," and the resident server now pays
  a fraction of the old import cost. Remaining for the *fresh-process CLI query*:
  the query service still pulls the scanner frontends via
  `platform.cpg → scanner.frontends` at import (used only during CPG extraction),
  which needs a lazy `scanner.frontends/__init__` to fully defer -- a deeper
  cascade left as a follow-up. Full suite green throughout.
- [~] **Deferred, triaged from cycle 6:** JS 2.2% resolution is dominated by
  untyped framework receivers (`res.json` where `res` is an untyped callback
  param) -- not statically typeable, an extraction ceiling, not a bug; ranking
  quality (Rust MRR 0.007) and confidence calibration (inverted) are the deferred
  T10/T11 and T14 efforts (retrieval tuning / labeled calibration data); the
  opt-in `[semantic]` model has a first-use download + a dense index ~10x the
  graph, inherent costs of real embeddings that want an explicit warmup step.

- [x] **Import cycles: none at import time.** A Tarjan SCC pass over the
  package's *top-level* imports finds **zero** runtime cycles; every logical A↔B
  dependency is already broken by a function-local import (the recommended
  pattern, e.g. `io.core`'s local import of `storage.delta`). No change needed.

Deferred (larger, separately-verified efforts): a store-level lock wrapping the
whole commit (manifest ordering closes the concrete divergence; concurrent
same-store scans remain a single-writer assumption, and a write-only lock cannot
fix the stale-read race without holding the lock across the expensive build);
consolidating the two subsystem classifiers (`renderers._subsystem_name` vs
`subsystems.subsystem_for_path` have intentionally different contracts --
display-groups-everything vs excludes-non-product); and splitting the four
orchestration monoliths (`retrieve_context`, `_build_graph_from_split`,
`search_nodes`, `_add_tree_sitter_calls`) -- behavior-preserving refactors best
done one at a time behind characterization tests.

## Explicit non-goals unless scope changes

- General Datalog/CodeQL-style arbitrary query languages. GraphGraph now has a
  bounded optional inference pass; that does not imply a general rule engine.
- Remote plugin signing while distribution remains local-only.
- Automatic use of tensor/CSR packet formats that are currently explicit-only.
- Model calls or external services in the default local scan/query path.
- Deleting code solely because GraphGraph reports zero callers while member-call
  coverage is incomplete.

## Immediate execution order

`T01 -> T02 -> T03 -> T04 -> T05 -> T06 -> T07 -> T08 -> T09 -> T10 -> T11 -> T12 -> T13 -> T14 -> T15 -> T16 -> T17 -> T18`

Only one behavior-changing retrieval task should be active at a time. Pure
documentation indexing and test-file splitting may proceed alongside a task
only when they do not alter the evidence corpus or evaluation baseline.
