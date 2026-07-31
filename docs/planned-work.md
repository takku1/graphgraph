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

## Active ordered improvement program — post-`a534942` (2026-07-30)

This P-series is the active execution order. The older T-series below preserves
completed receipts and remaining sub-items, but does not override this order.
Only one behavior-changing policy task may be active at a time.

### Executable queue

This is the dependency queue beneath the P-series. A batch may begin only when
its `depends on` gate is green. Pure measurement and characterization may run
ahead; two behavior-changing policy batches may not overlap.

| batch | scope | depends on | promotion gate |
| --- | --- | --- | --- |
| Q02-A | Complete typed facts for Python fields, imports, assignments, returns, and deferred obligations; retain transitive provenance | P02 lattice | Focused ambiguity/provenance tests and no lost incumbent Flask edges |
| Q02-B | Held-out Python receiver evaluation on Requests and Mem0, with Flask used only as calibration | Q02-A | Per-symbol source oracle improves; zero source-disproved added edges |
| Q02-C | Persist per-file facts and re-join only affected keys | Q02-B | Full/incremental graph equivalence and measured `O(delta facts + affected obligations)` growth |
| Q02-D | Addressable receiver slices for JS/TS, Rust, C#/Java, and C++ in descending oracle volume | Q02-C | Per-language held-out recall improves or the language explicitly abstains; precision does not regress |
| Q03-A | Versioned routing feature registry plus calibrated query-class model | P01, Q02-D | Held-out conceptual/compound utility improves over incumbent with paired CI |
| Q03-B | Multi-label facet decomposition and expected-loss selection | Q03-A | Facet completeness improves at equal token budget; red controls stay zero |
| Q03-C | Utility-fitted abstention and next-action information gain | Q03-B | Brier/ECE and abstention utility improve by query class |
| Q04-A | Inventory and normalize every ranking signal, boost, penalty, threshold, and cap | Q03-C | Every policy term has invariant, fitted provenance, or removal decision |
| Q04-B | Ranking tournament: calibrated linear fusion, RRF, learning-to-rank baseline, and diversity selection | Q04-A | Held-out NDCG/facet gain at equal tokens with paired minimum effect |
| Q05-A | Make all advertised packet formats generate and validate end to end | Q04-B | `10/10` format contract tests or remove unsupported advertisements |
| Q05-B | Constrained packet selection with connectivity and token/latency constraints | Q05-A | Better required-evidence utility at equal resources; deterministic receipts |
| Q06-A | Fit and version token, latency, and fact-density surfaces | Q05-B | Held-out residual/error reports and coefficient sensitivity stored |
| Q06-B | Bounded resource controller over the fitted surfaces | Q06-A | Stability/no-oscillation and hard-budget tests pass |
| Q07-A | Exact no-op equivalence and constant-time preflight | Q06-B | Effective graph delta is zero on `3/3`; no-op update `<100 ms` |
| Q07-B | Phase-complete build/update telemetry and persistent-state experiments | Q07-A | Largest runtime terms attributed; delta scaling beats whole-corpus scaling |
| Q08-A | Separate correctness, completeness, freshness, and provenance calibration | Q07-B | False-incomplete rate falls without unsafe answerability |
| Q08-B | Deterministic source-value selection and affected-test attribution | Q08-A | Cross-process signature exact; held-out affected-test coverage improves |
| Q09-A | Characterize and split orchestration monoliths into typed stages and lifecycle state machines | Q08-B | Behavior, benchmark signatures, and receipts remain unchanged |
| Q10 | Adjacent optimization candidates ranked by expected value | active batch | Independent measurement passes and rollback remains trivial |

Queue rule: a failed promotion gate keeps the incumbent and records `no
change`; it does not trigger threshold tuning on the held-out set. Q10 work may
ship beside an active batch only when it does not change that batch's frozen
evaluation baseline.

### Current measured baseline

- Local gates: `956 passed`, `96 subtests passed`, and Ruff green.
- GitHub CI run `30588946790`: distribution, quality gates, and the full
  Windows/Ubuntu Python 3.10–3.12 matrix pass.
- Independent local cold-process wall-clock samples: exact relation CLI
  `[491.20, 469.85, 457.85, 466.91, 557.84] ms` (median `469.85 ms`);
  no-op one-file update `[1023.96, 939.70, 929.47] ms` (median `939.70 ms`).
- Current self-graph telemetry: `10119` nodes, `37484` edges, `394` resolved
  member receivers, and `1285` unknown receivers. Treat these topology counts
  as diagnostic rather than ground truth until source-derived or external
  oracles corroborate the affected language slice.
- Exact-symbol self-eval is strong, but the current field-ranking tasks are
  lexically easy. A broad improvement query routed at confidence `0.147` and
  abstained after emphasizing the wrong subsystem. Conceptual and compound
  task coverage is therefore the first retrieval-evaluation gap.
- Independent critical gray-box evaluation now supplies a second baseline:
  mean positive-task recall `0.779`, complete recall on `10/14`, false
  incompleteness on `6/10` complete-recall tasks, no-op incremental
  equivalence `0/3`, Express receiver resolution `2.24%`, and only `6/10`
  packet formats validated end to end. Treat these as externally generated
  hypotheses until each active slice is reproduced against source and direct
  graph diffs; the report and its three task fixtures are indexed under
  operational findings.

### Decision policy: use the right abstraction

The goal is not “remove every `if`.” Branches are correct for semantic
invariants; hand-tuned ladders are weak for uncertain ranking and resource
allocation. Classify each decision before changing it:

| Decision shape | Required abstraction | Examples |
| --- | --- | --- |
| Semantic invariant | Explicit gate, pattern match, or decision table | query direction, packet validity, unsupported format |
| Lifecycle/protocol | Typed finite-state machine with legal transitions | freshness, answerability, source-index state |
| Evidence propagation | Monotone constraint system or bounded graph algorithm | receiver typing, inferred relations |
| Ranking under uncertainty | Calibrated score or probabilistic model | routing, anchoring, source relevance |
| Selection under a budget | Constrained optimization | node/edge/fact selection, packet format |
| Repeated dynamic work | Incremental algorithm with a complexity contract | update, graph load, semantic index refresh |
| Tunable numeric policy | Versioned fitted parameter with provenance | thresholds, weights, token and latency coefficients |

Hard gates remain hard when they encode meaning. A continuous formula must not
blur `in` versus `out`, valid versus invalid, or exact versus ambiguous merely
to look more mathematical.

### Common objective and promotion rule

Policy candidates should optimize a shared risk-adjusted objective rather than
accumulating unrelated boosts and penalties:

```text
J(S, p, r) =
    expected_required_evidence(S, r)
  + beta_diversity * coverage_diversity(S)
  - lambda_missing * missing_facet_risk(S)
  - lambda_noise   * irrelevant_context(S)
  - lambda_tokens  * token_cost(S, p)
  - lambda_latency * latency_cost(r)
  - lambda_stale   * freshness_risk(S)
```

subject to:

```text
packet_valid(S, p)
required_invariants(S, r)
token_cost(S, p) <= token_budget
latency_cost(r) <= latency_budget
red_control_recall == 0
```

The coefficients are not new magic constants. Fit or sweep them on frozen
train/calibration tasks, report sensitivity, and promote only on held-out
projects. If the data does not identify a stable coefficient, retain the
simpler incumbent and record `no change`.

### P00 — Restore a trustworthy green baseline

- [x] Add a red Windows/CRLF regression for distribution-artifact parity.
- [x] Make tracked artifact comparison newline-aware while preserving exact
  detection of semantic drift; keep generated output deterministic.
- [x] Run artifact, distribution, Ruff, full pytest, and self-eval gates.
- [x] Repair the stale `uv.lock` entry for the existing `semantic` extra and
  require `uv sync --locked` in CI so dependency drift cannot rewrite the lock
  during validation.
- [x] Push and require every Windows/Ubuntu matrix job to pass before P01.
- [x] Record benchmark hardware, Python version, cold/warm state, corpus size,
  graph size, and sample distribution for every latency claim.

Progress receipt (2026-07-30): a CRLF-converted copy of all ten distribution
artifacts failed red, then passed after newline-normalized comparison was
centralized in `distribution.py`; an appended semantic change remains stale.
Exact CI commands pass with `956 passed, 96 subtests passed`; Ruff and artifact
parity pass; structural graph validation passes at `10119` nodes / `37484`
edges; four real self-eval tasks and the RED control pass with calibration ECE
`0.0556`; wheel and sdist build successfully. GitHub Actions run `30588946790`
passes distribution, gates, and all Windows/Ubuntu Python 3.10–3.12 jobs.

Benchmark receipt for the two cold-process latency claims above: Windows 11 Pro
10.0.26200, 11th Gen Intel Core i7-11850H (8 cores / 16 logical processors),
31.2 GiB RAM, Python 3.11.15, and uv 0.11.24. Direct Git inventory at receipt
time is 409 tracked files / 5,142,368 bytes at `954ba1e`; GraphGraph independently
reports a full-scan snapshot over 399 files, and that self-reported count remains
diagnostic rather than an oracle. Each bracketed list is the complete sample
distribution; no warm samples were mixed into either median.

### P01 — Freeze evaluation before changing more policy

- [x] Build paraphrase and conceptual tasks whose queries share no identifier
  tokens with their expected evidence.
- [x] Add compound/multi-facet queries, ambiguous names, negatives, and
  cross-language receiver oracles. Expected answers must come from source or an
  independent analyzer, never GraphGraph output.
- [x] Freeze repository-held-out train/calibration/test splits and version the
  task resolver, tokenizer, token proxy, and expected-evidence schema.
- [x] Report per-query-class recall, first-hit MRR, NDCG, facet completeness,
  Brier/ECE, tokens, cold/warm latency, and abstention utility. Never hide a
  failing stratum inside one aggregate.
- [x] Add a paired-comparison harness with bootstrap confidence intervals and a
  minimum practical effect, not merely a positive mean delta.

Progress receipt (2026-07-30): `eval/retrieval-v1` freezes 24 tasks across
repository-held-out GraphGraph train, Flask calibration, and Express/ripgrep
test splits. All qrels carry direct source receipts at pinned commits; the
loader enforces split isolation, protocol versions, oracle independence, stable
task IDs, and zero identifier overlap for `lexical_disjoint` tasks. Structural
mode repeated twice with identical non-latency results: overall node recall
`0.695833`, MRR `0.424954`, NDCG@10 `0.299862`, facet completeness `0.489583`,
Brier `0.160045`, and ECE `0.152075`. Exact reverse lookup remains strong
(`1.0` recall), while lexical-disjoint recall is only `0.152778` with zero
NDCG@10; the frozen suite therefore exposes the intended conceptual gap. The
report includes complete token/latency distributions and failing task IDs.
Paired comparisons use stable IDs, deterministic percentile bootstrap samples,
confidence intervals, and an explicit minimum practical effect.

### P02 — Replace receiver heuristics with bounded constraint propagation

- [x] Represent local types, field types, imports, assignments, returns, and
  deferred attribute obligations as typed facts with provenance.
- [x] Define a small type lattice: `unknown < concrete`, conflicting concrete
  facts join to `ambiguous`, and no pass may guess through ambiguity.
- [x] Implement module/global proxy bindings (receiver-resolution stage 3).
- [x] Implement bounded `k`-hop obligation discharge (stage 4) with explicit
  depth, unresolved, and ambiguity receipts rather than whole-program fixpoint
  convergence.
- [ ] Generalize only after Python oracle gains survive held-out repositories;
  then attack addressable JS/TS, C#, Rust, and C++ buckets by measured volume.
- [x] Complexity target: re-emit facts for changed files and re-join affected
  keys, approaching `O(delta facts + affected obligations)` rather than a
  whole-corpus analysis.

Progress receipt (2026-07-30): Python local evidence now joins in a finite
powerset lattice, where set union is monotone and only singleton facts project
to receiver types. A dependency-indexed worklist revisits obligations only
when their root binding changes; attribute traversal has an explicit default
depth of three and emits `depth_limit`, `unknown_root`, `unknown_field`,
`ambiguous_root`, or `ambiguous_target` receipts. Module globals require an
explicit annotation, and imported facts join on `(module provenance, symbol)`
rather than symbol name alone.

Against the independent Flask gray-box graph, a fresh full scan kept all
`16,086` prior edges and added `20` call edges. Resolved receivers moved
`850 -> 871`, unknown receivers `534 -> 484`, and exact `ensure_sync` callers
`9 -> 12`; the three recovered callers are the source-visible
`current_app.ensure_sync` sites in `views.py`. All 20 additions were inspected
as a direct old/new graph diff and matched source-visible declared field,
proxy-base, or annotated-local evidence. This is a calibrated-repository gain,
not by itself a cross-repository promotion; the next receipt records the
subsequent held-out gate.

Q02-A / Python Q02-B receipt (2026-07-31): project field facts, annotated
module globals, package re-exports, callable return facts, assignments, and
deferred obligations now retain provenance and ambiguity through the finite
lattice. Against `cf9fa66`, paired full scans removed zero incumbent edges.
Flask moved `850 -> 871` resolved and `534 -> 484` unknown with 20 added calls;
held-out Requests moved `501 -> 509` and `174 -> 159` with 8 added calls; held-
out Mem0's Python stratum moved `1622 -> 1650` and `1211 -> 1086` with 28
added calls. All additions were checked against pinned source. A per-callable
module reparse regression was caught by the comparison, removed, and locked by
a file-bounded extraction-count test. Detailed commands, revisions, edge
classes, and limits are in the indexed P02 held-out finding.

Q02-C receipt (2026-07-31): persistent per-file facts and affected-key rejoin
are green for Python.
Manifest v4 stores finite contributions, reverse obligations, and re-export
adjacency; incremental return, field, and provider-deletion fixtures equal
clean full rebuilds. With one changed fact and one affected consumer, loaded
re-join p95 remained `0.1387 ms` with 10,000 unrelated fact/re-export rows;
with 1,000 affected consumers median was `0.3294 ms`. Serialization and graph
load are excluded and remain in Q07-B. The indexed finding contains the state
equations, reproduction command, equivalence gates, and limits.

Queue position: Q02-D language generalization is next. Q07 still owns
universal incremental/no-op equivalence; Q02-C does not close those failures.

### P03 — Calibrate routing and facet decomposition

- [ ] Keep semantic query-class gates explicit, but replace hand-set routing
  confidence with a calibrated log-linear or multinomial model over the current
  interpretable features.
- [ ] For compound queries, predict a set of required facets rather than force
  one winner. Select facets by expected loss relative to abstaining:

  ```text
  choose A* = argmin_A E[missing_cost(A) + excess_cost(A) | features]
  ```

- [ ] Fit abstention using held-out utility; report the next action that has the
  highest expected information gain instead of only saying “retry narrower.”
- [ ] Move signal definitions, feature provenance, fitted coefficients, and
  router version into one typed policy artifact. Regexes may extract features;
  they should not also hide the calibration policy.
- [ ] Gate on conceptual and compound tasks from P01, including the broad audit
  query that currently misroutes.

### P04 — Unify anchor, source, and evidence ranking

- [ ] Inventory every boost, penalty, threshold, and cap in `search.py`,
  `anchors.py`, `source_planner.py`, and semantic retrieval; assign each an
  invariant, fitted provenance, or removal candidate.
- [ ] Normalize heterogeneous signals before fusion. Compare calibrated linear
  scoring, reciprocal-rank fusion, and a simple learning-to-rank baseline.
- [ ] Treat authority, exactness, semantic similarity, graph influence,
  freshness, and provenance as explicit features. Avoid multiplying ad hoc
  penalties whose combined scale is unknowable.
- [ ] Use diversity-aware selection (for example maximal marginal relevance or
  a monotone submodular coverage objective) only when it improves required
  facet coverage at equal tokens.
- [ ] Do not resume attention-field or coupling promotion until P01 can detect
  a field contribution. The incumbent remains the winner when PPR or coupling
  only reorders the tail.

### P05 — Solve packet construction as constrained selection

- [ ] Preserve hard connectivity/path constraints where intermediate nodes
  unlock required evidence.
- [ ] Express node, edge, fact, and packet-format selection against the shared
  objective. Compare greedy marginal gain, lazy submodular greedy, and the
  existing tree-knapsack path policy on frozen neighborhoods.
- [ ] Replace fixed per-relation quotas with utility allocation when the
  benchmark supports it:

  ```text
  gain(item | S) =
      relevance * provenance * novelty * facet_gain
      / marginal_token_cost
  ```

- [ ] Stop when the best feasible marginal gain is below its calibrated shadow
  price, not an unproven global threshold.
- [ ] Emit a receipt explaining binding constraints, omitted high-value items,
  and the estimated value of one additional token/latency unit.

### P06 — Turn budgets into fitted resource control

- [ ] Refit token surfaces whenever packet syntax changes; store corpus,
  residuals, held-out error, and coefficient uncertainty with the version.
- [ ] Fit latency surfaces over graph size, changed-file count, node/edge count,
  backend state, and cold/warm process state.
- [ ] Replace isolated node caps with a constrained integer choice over the
  token and latency surfaces; retain explicit caller budgets as hard limits.
- [ ] Use observed first-page cost as feedback for a bounded second decision.
  Require stability/no-oscillation tests before any iterative controller.
- [ ] Calibrate fact density from measured marginal answer utility; the current
  `max_facts / sqrt(node_count)` curve remains provisional until then.

### P07 — Make the edit loop genuinely incremental

- [ ] Add a constant-time no-op preflight before loading/deserializing the full
  graph. Target no-op update `<100 ms` on every frozen fixture.
- [ ] Separate persistent graph state from CLI process startup. Target exact
  relation retrieval `<50 ms` resident and `<200 ms` cold CLI.
- [ ] Profile graph load, manifest/hash work, parse, merge, serialize, and
  process startup independently; optimize the largest measured term first.
- [ ] Evaluate indexed append/delta persistence, memory mapping, and a resident
  MCP/daemon path under crash-safety and equivalence tests.
- [ ] Enforce an empirical complexity gate: one-file update growth should track
  delta size, not total corpus size; current cross-corpus ratio must fall below
  the recorded CI target.

### P08 — Calibrate confidence, completeness, and source value

- [ ] Model correctness and completeness separately. Exact target identity,
  topology completeness, facet coverage, freshness, truncation, and source
  provenance are features, not hardcoded confidence ceilings.
- [ ] Reconcile changed-path test evidence with semantic packet validation. A
  changed-path regression command is currently emitted with concrete test
  provenance but then rejected because only direct/transitive roles satisfy
  the attribution gate; either license that role explicitly or withhold the
  command.
- [ ] Compare logistic, isotonic, and monotone calibration on held-out tasks;
  promote the simplest model with better Brier/ECE and useful risk-controlled
  abstention.
- [ ] Choose optional semantic/memory/trace/federated sources by expected value
  of information per latency/token cost. Explicit opt-in and warmup remain hard
  operational gates.
- [ ] Remove cross-process nondeterminism from automatic source planning before
  treating production-mode eval deltas as promotable. Two pinned P01 runs moved
  overall MRR from `0.418467` to `0.418358` and token p95 from `1447.2` to
  `1501.55`; structural mode repeated exactly.
- [ ] Report calibration by query class and language stratum; never infer trust
  from retrieval recall alone.

### P09 — Replace orchestration monoliths with typed stages

- [ ] Characterize and split, one at a time: `retrieve_context`,
  `_build_graph_from_split`, `search_nodes`, and `_add_tree_sitter_calls`.
- [ ] Use typed stage inputs/outputs for `route -> anchor -> source -> expand ->
  select -> pack -> validate`; receipts are produced by stages rather than
  reconstructed afterward.
- [ ] Model freshness, semantic-index, answerability, and compilation lifecycle
  as finite-state machines with exhaustive transition tests.
- [ ] Move policy data into versioned registries and keep mechanism functions
  free of query-class string ladders where a dispatch table is equivalent.
- [ ] Require no behavior or benchmark change during pure refactors.

### P10 — Opportunistic optimization lane

Opportunistic work is welcome only when it is adjacent to the active P-task and
does not move its evaluation baseline. Record each candidate with baseline,
hypothesis, expected complexity change, blast radius, measurement command, and
rollback.

Rank opportunities by expected value rather than intuition:

```text
priority(o) =
    P(success | evidence)
  * expected_user_or_agent_benefit
  / (implementation_cost + validation_cost + regression_risk)
```

Preferred opportunities:

1. eliminate repeated scans, serialization, tokenization, or graph loading;
2. replace linear lookup with a maintained index when update cost stays
   bounded;
3. cache pure computations by graph revision and policy version;
4. combine repeated score passes into one feature extraction pass;
5. remove dominated branches or constants after sensitivity analysis;
6. replace duplicated categorical ladders with typed tables/state machines;
7. improve asymptotic behavior only when real corpus sizes reach the crossover.

Current packaging opportunity: migrate `project.license` to an SPDX string and
remove the deprecated license classifier before the setuptools enforcement date
(`2027-02-18`), with wheel metadata and clean-install verification.

Current CI-maintenance opportunity: evaluate `actions/checkout` v7 and
`astral-sh/setup-uv` v9, including setup-uv's changed cache-pruning default,
before upgrading the current v4/v5 pins. GitHub currently forces both Node-20
action versions onto Node 24 and emits deprecation annotations; this is
maintenance evidence, not a reason to disturb P01.

Reject an opportunistic change when it lacks an independent oracle, changes a
frozen task while tuning against it, obscures receipts, adds a dependency to
the default local path, or wins only on a proxy while downstream quality is
flat.

### Definition of “fixed up”

The program is complete only when:

- all supported CI platforms and distribution gates are green;
- extraction, retrieval, confidence, and latency gates pass per language and
  query stratum on held-out repositories;
- conceptual and compound queries improve without breaking exact lookup or the
  red control;
- no production policy constant lacks invariant or measurement provenance;
- edit/update cost is demonstrably delta-sensitive;
- experimental algorithms remain behind explicit flags until they beat the
  incumbent at equal resources;
- operational docs, formulas, code, receipts, and benchmark implementations
  describe the same policy version.

## Historical baseline recorded 2026-07-22

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

**Cycle-7 metric repair and eval-gated ranking (2026-07-26).**

- [x] **Make unresolved eval ground truth visible.** Every task now reports
  `expected_resolved_count`, `expected_unresolved_count`, and the unresolved
  strings. Recall remains scored against all declared expectations (bad
  fixtures cannot become green), while unresolved tasks are excluded from
  calibration. This caught the Redis review's coarse-path failure mode in the
  instrument itself.
- [x] **Replace fabricated calibration negatives with explicit labels.** The
  eight impossible tasks in `graphgraph-calibration.json` used nonexistent
  node expectations as negative outcomes. They now use
  `expected_answerable:false`; the 16 positive tasks still require graph-
  resolved retrieval expectations. Fresh structural receipt: `n=24`, base
  rate `0.666667`, resolution `0.222222`, ECE `0.088958`, Brier `0.012801`,
  unresolved/excluded tasks `0`. No confidence weights were tuned to obtain
  this result; the dataset semantics were repaired.
- [x] **Make eval measure the shipped compiler path.** `evaluate_graph` now
  runs through `GraphRuntime`/`GraphProgram`, including the same source planner
  as `query`, instead of calling `retrieve_context` directly. This exposed a
  real disagreement: production retrieved ripgrep's
  `crates/core/flags/parse.rs` while the old harness scored a miss. The new
  `eval --source-mode {auto,off,all}` keeps production parity explicit and
  provides a deterministic structural baseline; an auto-mode cold run also
  reproduced the known semantic-index cliff (>184 s timeout), so warmup/cold
  semantic cost remains open rather than hidden.
- [x] **Lift the hand-verified ripgrep ranking gate.** A bounded directional
  `printed -> {write, render, emit, output}` code-vocabulary bridge, admitted
  only after the external fixture proved `standard.rs` implements output via a
  dense `write_*` family, moved the six-query production-mode oracle from
  recall `5/6`, mean MRR `0.39647`, mean NDCG@10 `0.29932` to recall `6/6`,
  mean MRR `0.56313`, mean NDCG@10 `0.33600`. The target query moved from a
  miss to recall `1.0` / MRR `1.0`; Ruff and focused search regressions pass.
- [x] **Rank reverse-lookup evidence by production role and relation strength.**
  Direct `calls` now lead references/import containers; maintained source
  callers lead benchmarks and tests. On the July-26 F1 self task,
  `cmd_query` moved from packet rank 8 to rank 2 (MRR `0.125 -> 0.5`) without
  dropping any benchmark evidence. Fresh structural self-eval is recall `1.0`,
  mean MRR `0.875`, mean NDCG@5 `0.75` across the four real tasks; the red
  control remains recall `0.0` and is explicitly unresolved by design.
- [~] **Document authority target refreshed, but trust-state work remains.**
  The target now names the actual latest July-26 review. Both architecture and
  latest-review tasks score recall `1.0` / MRR `1.0`; packets mechanically and
  semantically validate at 1,140 and 1,345 proxy tokens. Architecture is
  `answerable`; the latest-review query remains `incomplete`, so T10/T11 are
  not declared complete on recall/rank alone.
- [x] **Repository gates.** Ruff passes, the full pytest suite passes, project
  distribution artifacts are current, and a post-edit `context --sync git`
  refreshed 16 paths with structural graph and packet validation passing.

- [x] **Import cycles: none at import time.** A Tarjan SCC pass over the
  package's *top-level* imports finds **zero** runtime cycles; every logical A↔B
  dependency is already broken by a function-local import (the recommended
  pattern, e.g. `io.core`'s local import of `storage.delta`). No change needed.

**Cycle-8 bounded semantic latency and fast-quality recovery (2026-07-26).**

- [x] **Remove hidden semantic preprocessing from interactive auto queries.**
  `QuerySourcePlanner` no longer builds a missing/stale semantic index in
  `auto`; `all` retains the explicit eager behavior and `platform semantic
  --rebuild` remains the dedicated preprocessing command. A bounded metadata
  prefix check classifies the sidecar without decoding its large vector body.
  Receipts now expose `semantic_index_state` (`missing`, `stale`, `current`,
  `cold_backend`, `rebuilt`, `invalid`, etc.) and a matching warning when auto
  degrades. A stale self-index query completed in **2.844 s**, versus the
  Cycle-7 **>184 s timeout** (at least **64x** faster).
- [x] **Do not initialize FastEmbed inside a fresh auto query.** Even a current
  dense index can trigger ONNX/model setup and a Hugging Face fetch on its first
  query. The exact ripgrep six-case run reproduced this at roughly **255 s**.
  Auto now consumes a current FastEmbed index only when that process already
  warmed the backend; explicit `all` still opts into the cost. The fast six-case
  run completes in about **14 s**.
- [x] **Recover dense-only recall with measured code vocabulary.** Fast auto
  initially exposed one real loss: `how are command line arguments parsed`
  anchored on subprocess and line-buffer symbols instead of
  `crates/core/flags/parse.rs`. Phrase-aware normalization now treats `command
  line` as the compound modifier it is, and the directional
  `argument -> {flag, flags}` bridge maps user vocabulary to the maintained code
  vocabulary. Ripgrep auto is now **6/6 recall**, mean MRR **0.61868**, mean
  NDCG@10 **0.34270**—better ranking than the cold dense receipt (**0.56313** /
  **0.33600**) without model startup. Self real-task recall remains **1.0**,
  mean MRR **0.875**, mean NDCG@5 **0.75**; RED remains **0.0**.

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

`P00 -> P01 -> P02 -> P03 -> P04 -> P05 -> P06 -> P07 -> P08 -> P09`

`P10` is a constrained side lane, not a phase that bypasses the active task's
gates. The T-series remains below as historical receipts and source material
for P-series acceptance criteria.

Only one behavior-changing retrieval task should be active at a time. Pure
documentation indexing and test-file splitting may proceed alongside a task
only when they do not alter the evidence corpus or evaluation baseline.
