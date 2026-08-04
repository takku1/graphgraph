# GraphGraph 0.1.0 — Comprehensive Gray-Box Evaluation After Updates

**Date:** 2026-07-27
**Control fixture:** `resources/flask` at
`954f5684e4841aad84a8eec7ace7b81a0d3f6831`
**Baseline:** immediate prior controlled Flask run on 2026-07-26; all required baseline numbers
are reproduced in this report, so no deleted historical report is needed
**Method:** The original evaluation was a CLI-only gray-box differential; GraphGraph implementation
and Git history were not read during that phase. The same Flask commit, exclusion policy, rebuild
command, direct source oracles, negative controls, metamorphic relations, and live-validation
queries were reused. Post-evaluation implementation receipts below are explicitly labeled and use
source inspection, regression tests, competitor differentials, and primary research.
**Mutation scope:** The original audit intentionally rebuilt `.graphgraph`, the independent
skill-validation graph, and this report. The labeled post-evaluation receipts additionally changed
GraphGraph implementation/tests/guidance; no Flask source file changed.

---

## Executive verdict

This is a standalone current-state evaluation and path-to-10 report. The updates produced a large,
externally verifiable improvement. This is not a counter-only win:
the additional edges repair the exact user-facing failures they should repair.

**Current fixture score: 7.4/10, up from 5.2/10. Credible ceiling: 9.8/10.** This is a
single-fixture score, not a replacement for a multi-language board.

The prior run's four most important failures now behave as follows:

| Prior critical gate | Before | Now | Verdict |
| --- | --- | --- | --- |
| Auto-routed fantasy query | 16 irrelevant nodes; wrong abstention reason | 0 nodes, `unanswerable`, confidence 0.0 | **Fixed** |
| `make_response` affected tests | 0 direct / 0 transitive | 7 direct / 3 transitive | **Fixed at retrieval; commands incomplete in the frozen audit** |
| Exact Flask request path | Correct packet but `incomplete`, confidence 0.217 | `answerable`, confidence 0.995 | **Fixed** |
| Budget monotonicity | Lost nodes at 10→52 and 52→100 | Loses 0 nodes at 10→52→100 through two CLI paths | **Fixed** |

The official GraphGraph skill harness independently moved from **2/4 to 3/4 query-valid**, while
packet validity stayed 4/4 and structural gates stayed 2/2. The remaining harness failure is the
unscoped testing-document query, where a tangential truncated `docs/api.rst` anchor still poisons
answerability.

The center of gravity has moved. The largest problem is no longer “can the graph find the evidence?”
On the exact Python controls, it usually can. The new cap is **whether every surface interprets and
acts on the same evidence consistently**.

### Post-evaluation implementation receipt — evidence equivalence

After the CLI-only evaluation above, the highest-priority R3 contradiction was implemented and
retested without changing Flask source. A new metamorphic regression fixes the query pair from this
report and requires route, anchors, selected nodes/edges, typed obligation closure, status, and
confidence to agree. This follows the evidence-sufficiency rule behind reject-option systems: a
selection decision should follow the evidence/risk state, not an ancillary wording transformation
([El-Yaniv and Wiener, JMLR 2010](https://jmlr.csail.mit.edu/papers/v11/el-yaniv10a.html)).

The first normal-user reproduction exposed two independent failures:

- automatic routing classified the invocation-chain paraphrase as `direct_lookup` rather than
  `multi_hop_path`;
- with `multi_hop_path` held fixed, both executions had identical anchors, 80 nodes, 156 edges,
  byte-identical packets, and `required_obligation_closure=3/3`, yet confidence/status remained
  0.9951/`answerable` versus 0.2483/`incomplete`.

The implementation is deliberately narrower than a blanket closure override. The router now treats
`invocation chain` as path intent, while facet parsing classifies invocation/carry/start/end wording
as path framing. The real residual content facet, `wsgi flask`, must still be grounded; it is proven
by `Flask::wsgi_app` in the selected packet. Thus a genuine waypoint/content constraint can still
fail instead of being erased by 3/3 endpoint closure. Router and query-cache contracts were versioned
so stale responses cannot manufacture a pass.

Fresh automatic-routing results on the frozen Flask graph are now identical:

| Query form | Class | Packet | Closure | Status | Confidence | Missing facets |
| --- | --- | --- | ---: | --- | ---: | --- |
| canonical call-path wording | `multi_hop_path` | 80 nodes / 156 edges | 1.0 | `answerable` | 0.9951 | none |
| invocation-chain paraphrase | `multi_hop_path` | same packet bytes | 1.0 | `answerable` | 0.9951 | none |

Both packet and semantic validation pass. The official live harness consequently moved from **3/4
to 4/4 query-valid**, with packet validity still 4/4 and structural gates still 2/2. Its test phase
is not a product regression: the detected Hermes interpreter lacks Flask, and adding `flask/src` to
`PYTHONPATH` reaches the next missing fixture dependency, `werkzeug`. This environment limitation is
recorded rather than counted as a passing Flask suite.

GraphGraph's own repository gates pass after the change: the full `pytest` suite, Ruff, the
documentation contract checks, and `git diff --check` are clean.

### Post-evaluation implementation receipt — runnable affected-test closure

The second priority item was then implemented against the frozen Flask graph. The red control
reproduced the report exactly: seven raw direct candidates, one emitted command, and six uncovered
candidate IDs. Two of those IDs (`add_x_parachute` and `new_function`) are nested helpers in
`test_view_decorators`, not independently runnable pytest tests.

The implementation now separates two previously overloaded concepts:

- **structural test evidence** remains in the packet as a proof witness;
- **runnable test identity** controls direct-test counts and executable commands.

For Python, default runnable functions/methods must use pytest's `test*` naming contract unless
explicit scanner facts identify a custom test. Non-runnable witnesses are retained instead of
discarded. When one same-file runnable direct test is unambiguous, a witness receives an
`attributed_to` receipt rather than a fabricated standalone command.

Root coverage and command closure are also separate contracts. The existing bounded greedy pass
still covers requested symbols. A residual exact set-cover pass then covers every runnable direct
test using at most 12 direct candidates, with worst-case cost
`O(candidate_commands * 2^12)`. Broader changed-path commands supersede redundant exact filters and
record every superseded command in the receipt.

The corrected normal CLI result is stable across a v19 response-cache miss and warm hit:

| Receipt | Before | After |
| --- | ---: | ---: |
| Runnable direct tests | 7 raw candidates | **5** |
| Structural helper witnesses | mixed into direct count | **2, both attributed to `test_view_decorators`** |
| Runnable file commands | 1 | **3** (`test_basic.py`, `test_helpers.py`, `test_views.py`) |
| Uncovered runnable direct tests | 6 raw candidates | **0** |
| Semantic / packet validation | pass / pass | **pass / pass** |

The response-cache regression first proved that the production request incorrectly hit both the
pre-equivalence v17 contract and the interim command-only v18 contract. The final
`request_v19_affected_test_witness_attribution` key misses both legacy entries, then returns the
same corrected action set on a warm hit.

Validation after the implementation:

- the focused runnable-command, structural-witness, homonym-exclusion, Cargo-supersession, and
  legacy-cache contracts pass;
- all seven GraphGraph-attributed regression modules pass;
- repository-wide Ruff and `git diff --check` pass;
- the full suite has no functional failure; its extraction timing test measured 13.51 s under
  suite contention against a 10 s ceiling, then passed immediately in isolation. This is retained
  as a timing-environment qualification rather than reported as an unconditional full-suite pass.

---

### Post-evaluation implementation receipt — low-level relation lane

The next competitive control came from the local source checkout at
`C:\Users\dcarn\aiprojects\resources\code-review-graph`. Code Review Graph felt faster for
caller/callee mapping because its `query_graph` path is intentionally narrow: resolve a qualified
SQLite node, use an indexed source/target edge lookup, filter `CALLS`, and return at most five rows
in minimal mode. It bypasses natural-language routing, facet planning, graph expansion, packet
rendering, and answerability validation.

That architecture explains both the speed and the observed defects:

- an unqualified exact symbol can become `ambiguous` because broad search candidates include a
  containing file or substring-matching tests;
- callee output includes unresolved built-ins such as `append`, `setdefault`, and `items`;
- minimal mode silently returns only five rows while `result_count` may be much larger;
- no receipt distinguishes response truncation from incomplete static call extraction;
- the comparator's own reproducibility document labels its canonical impact recall as a circular,
  graph-derived upper bound; independent co-change canonical results were not yet reported.

GraphGraph now exposes a separate demand-driven lane instead of weakening `query_context`:

```text
MCP: graphgraph/query_relations target=<id|label|path::symbol> direction=callers|callees [sync=git]
CLI: graphgraph relations <symbol> --direction callers|callees [--sync git]
```

The hot path performs exact resolution and one cached adjacency lookup only. Exact code symbols
outrank same-named concept/document nodes; `path::symbol` resolves real code collisions; genuine
same-name code definitions return explicit candidates. Only `calls` edges participate. External
nodes are excluded by default, tests are opt-in, and production/benchmark/test/external roles have
deterministic ordering.

The default MCP/CLI representation is a low-token tuple IR:

```json
{"v":2,"s":"ok","d":"<-calls","tk":["id","label","kind","path","line"],"k":["label","kind","path","line","role","confidence"],"t":["TARGET","work","function","src/core.py",10],"n":[["run","function","src/app.py",20,"production",0.95]],"r":{"matched":1,"eligible":1,"returned":1,"omitted":0,"filtered":{"tests":0,"external":0},"graph_complete":true,"topology":"complete","answer_complete":false,"freshness":"unchecked","ms":1.3},"a":["sync_if_completeness_required"]}
```

The receipt deliberately separates three claims:

1. `graph_complete`: every eligible matching edge already in the saved graph was returned;
2. `topology`: extraction telemetry is `complete`, `partial`, or `unknown`;
3. `freshness`: the default fast path is `unchecked`; `sync=git` / `--sync git` fuses an
   incremental Git-delta refresh and can license `fresh` in the same call.

Micro IR v2 adds the missing target tuple schema (`tk`), labels filtered counts, and emits stable
`a` action opcodes for missing/ambiguous targets, truncation, unchecked freshness, or partial
topology. `answer_complete` now requires all three gates—untruncated rows, complete topology, and
checked freshness—so an unchecked graph can no longer license a globally complete answer.

Identical in-process measurements used eight calls per exact target. GraphGraph numbers include its
memoized graph loader and micro serialization; Code Review Graph numbers include opening its SQLite
store and compact JSON serialization. Token counts use the same `ceil(chars/4)` proxy for both:

| Exact caller query | GraphGraph cold | GraphGraph warm median | GG proxy tokens / rows | CRG cold | CRG warm median | CRG proxy tokens / rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `retrieve_context` | 156.6 ms | **1.67 ms** | **274 / 6** (+97 tests filtered) | **10.0 ms** | 8.81 ms | 283 / 5 (100 total) |
| `render_query_context` | 1.4 ms after resident load | **1.38 ms** | 320 / 8 (+9 filtered) | 2.7 ms | 2.73 ms | **272 / 5** (12 total) |
| `affected_test_recommendations` | 1.4 ms after resident load | **1.33 ms** | **199 / 2** (+2 filtered) | 2.5 ms | 2.21 ms | 239 / 3 |

GraphGraph therefore wins the resident direct-query latency on all three controls and retains lower
token cost per returned actionable row after adding the self-decoding schema and actions. It does
not yet win cold start: the first native `.gg` load
materializes the whole graph (~185 ms), while SQLite can seek directly into its persistent indexes.
The next performance slice is therefore a versioned persistent relation index (or memory-mapped
adjacency sidecar), updated transactionally with graph deltas and queried without full graph
materialization.

The design is grounded in primary work rather than copied from one comparator:

- [Code Property Graphs](https://ieeexplore.ieee.org/document/6956589) show the value of a unified
  representation across syntax, control flow, and data dependence.
- [IFDS graph reachability](https://doi.org/10.1145/199448.199462) establishes precise
  interprocedural analysis as a graph-reachability problem for a broad distributive class.
- [Demand-driven refinement](https://manu.sridharan.net/files/pldi06.pdf) supports paying for
  context sensitivity only where a query requires it—the same rationale for separate lookup and
  analysis lanes.
- [IncA](https://szabta89.github.io/publications/inca-ase.pdf) compiles analyses to graph patterns
  and prunes change propagation for real-time incremental feedback.
- [QL](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.ECOOP.2016.2) demonstrates that
  recursive declarative code queries can scale on relational storage.
- [Shared Arrangements](https://arxiv.org/abs/1812.02639) shows why maintained reusable indexes beat
  rebuilding query-local state for interactive workloads.
- [Glean's indexing architecture](https://engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/)
  reports millisecond prefix-indexed fact queries and O(changes) incremental indexing.
- Modern agent studies—[RepoGraph](https://arxiv.org/abs/2410.14684),
  [CodexGraph](https://arxiv.org/abs/2408.03910), and
  [DraCo](https://arxiv.org/abs/2405.19782)—independently support structural/dataflow retrieval for
  repository-scale model tasks rather than similarity-only context.

Focused relation, CLI/MCP, machine-contract, and module-boundary tests pass. The always-visible MCP
schema remains gated at 10,400 characters / 2,600 proxy tokens for all 23 tools; the new capability
adds 137 proxy tokens to that recurring contract, while avoiding much larger context packets on
every exact relation query. The 7.4 fixture score above is not recomputed from this feature-only
benchmark. Final integration validation also passes: the full pytest suite (80.3 s), repository-wide
Ruff lint, scoped Ruff formatting, `git diff --check`, generated-artifact integrity, and refreshed
self-graph structural validation. Repository-wide format checking still reports pre-existing drift
in 122 unrelated files; those files were not mechanically rewritten for this slice.

A final environment differential exposed one more frontend-contract issue: aggregate Tree-sitter
availability was true while the installed language pack lacked Swift. The multi-language regression
now exercises each installed optional grammar independently instead of assuming one available
grammar licenses every language; production `describe_frontends` already exposes the matching
`ready_languages`/`unavailable_languages` receipt, and explicit requests for a missing grammar still
fail rather than silently pretending Tree-sitter coverage.

---

## Controlled rebuild delta

Exact rebuild command, unchanged from the baseline:

```text
graphgraph scan --directory . --depth symbols --frontend auto --docs --history \
  --no-incremental --exclude graphify-out .code-review-graph --force
```

The audit retained `src`, `tests`, `docs`, `examples`, and project metadata. It honored the same
three root/nested ignore files and explicitly excluded `graphify-out` and `.code-review-graph`.
The Flask tracked worktree was clean and the commit was unchanged.

| Rebuild metric | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| Nodes | 5,868 | 5,868 | 0 |
| Edges | 15,443 | 16,083 | **+640 (+4.1%)** |
| Saved bytes | 2,225,204 | 2,261,596 | +36,392 (+1.6%) |
| Selected files | 231 | 231 | 0 |
| Source / docs / other | 1,437 / 4,351 / 80 | 1,437 / 4,351 / 80 | 0 |
| Frontend fallback / failure | 0 / 0 | 0 / 0 | 0 |
| Full scan + validation | 23.3 s | 3.7 s | **6.3× faster** |
| Document phase | 11.43 s | 1.42 s | **8.0× faster** |
| Concept phase | 777.6 ms | 89.4 ms | **8.7× faster** |
| Truncated docs | 32 / 115 | 32 / 115 | unchanged |

The independent live harness rebuilt a separate graph with its own audited exclusions and no
history. It again matched the active graph exactly: 5,868 nodes, 16,083 edges, and zero categorized
node/edge delta. Reproducibility remains excellent.

---

## Extraction and topology delta

| Metric | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| Resolved member calls | 327 | 847 | **+520 (+159%)** |
| Unknown receiver | 855 | 537 | **−318 (−37.2%)** |
| External/unmatched | 1,230 | 1,038 | −192 (−15.6%) |
| Receiver resolution | 27.7% | 61.2% | **+33.5 points; 2.21×** |
| Global call coverage | 13.6% | 35.0% | **+21.4 points; 2.58×** |
| `calls` edges | 536 | 1,023 | **+487 (+90.9%)** |
| `calls_per_symbol` | 0.3959 | 0.7555 | **+90.8%** |
| `make_response` helper callers | 0 | 7 | **recovered** |

Unknown receiver shapes localize the next extraction work:

| Shape | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| `named_local` | 639 | 329 | −310 (−48.5%) |
| `complex_expression` | 155 | 22 | −133 (−85.8%) |
| `field_chain` | 15 | 140 | +125 |
| `short_local` | 26 | 26 | unchanged |
| `call_result` | 20 | 20 | unchanged |

The `field_chain` increase should not be called a regression without a labeled edge oracle. Because
total unknown receivers fell sharply while classification became more specific, the most plausible
interpretation is re-bucketing of formerly broader failures. It is now the second-largest explicit
frontier after `named_local` and deserves its own stratum in the next fixture.

The +640 edge delta is user-visible. `profile` reports +487 call edges and 149 `reads` edges, and
the normal affected-test packet now carries a typed `writes` edge from
`test_session_using_application_root` to `Flask::wsgi_app` with provenance
`python_ast_typed_attribute_use`. That is exactly the evidence missing in the baseline.

---

## Phase 0 — instrument validation after the updates

### Explicit negative control: still healthy

The impossible quantum/blockchain/GPU query with explicit `negative_query` returned
`unanswerable`, zero packet nodes/tokens, and both missing concepts. Before the rebuild it also
correctly reported extractor incompatibility; after the rebuild freshness was healthy.

### Automatic negative control: repaired

The normal user query:

```text
How does Flask implement quantum blockchain consensus and GPU transaction rollback?
```

still routes to `reverse_lookup`, but now returns:

- `status=unanswerable`
- confidence `0.0`
- zero anchors, nodes, edges, and tokens
- both requested facets explicitly unfulfilled
- reason: no code/structural evidence covers any required facet

The route label is less important than the outcome. The prior plausible-but-irrelevant 16-node
packet is gone. Automatic absence calibration now passes this red control.

### Cache counters: still fail the red test

Two identical queries returned byte-identical packets and identical anchors, each reporting
`workflow.cache.state=hit`, with internal query times of 156 and 157 ms. Bare cache telemetry then
reported:

```text
Cache: 63/256 entries  hits=0  misses=0  hit_rate=0%
```

The entries count moves; hit/miss counters do not. The cache surface still does not measure the
query path that emits hit receipts, or the namespaces remain undisclosed and incomparable.

### New receipt contradiction: one packet, two budgets

For the default multi-hop query, structured retrieval reports `node_budget=80`, packet validation
reports 80 nodes, and the packet contains 80 nodes. The compact control line simultaneously says
`budget=52 actual=80/156`. `profile` calls 52 the recommended candidate budget, but it is not the
executed budget in the structured receipt.

The packet itself respects the executed 80-node bound. The defect is telemetry identity: an agent
cannot know whether `budget` in the control line means recommendation, execution cap, or something
else.

### Existing metric-definition differences remain

- Scan/status: 4,351 doc nodes; `profile`: 4,331 `doc_nodes`.
- `profile.frontend_quality.unresolved=1038` corresponds to status
  `external_or_unmatched=1038`, while unknown receivers are a separate 537.
- Receiver resolution is 61.2%, while global call coverage is 35.0%; both denominators are valid,
  but they need canonical names and paths.

**Instrument verdict:** automatic abstention and answerability for the canonical path improved
substantially. Cache telemetry, count naming, and compact-control budget semantics are still unsafe
as unqualified CI inputs.

---

## Retrieval differential

## R1 — affected-test retrieval repaired; command closure fixed post-evaluation

### Observed improvement

The narrowed helper query moved from zero tests to:

- seven direct candidates across `tests/test_basic.py`, `tests/test_helpers.py`, and
  `tests/test_views.py`;
- three transitive candidates;
- `status=answerable`, confidence 0.704;
- one emitted command: `python -m pytest tests/test_helpers.py`.

The known direct-oracle functions `test_make_response`,
`test_make_response_with_response_instance`, and `TestHelpers::test_make_response` are present.
The whole-graph `select` surface moved `src/flask/helpers.py::make_response` from zero callers to
seven callers. This is a genuine extraction/retrieval repair.

The compound `wsgi_app` query now returns `test_session_using_application_root` as a direct test,
with a two-node proof path rooted at `wsgi_app` and a typed `writes` edge. The command
`python -m pytest tests/test_basic.py` covers that direct test. This exact baseline miss is fixed.

### Original remaining problem (fixed by the post-evaluation receipt above)

The helper query's command selector explicitly reports six uncovered direct candidates:

- three in `tests/test_basic.py`;
- `add_x_parachute`, `new_function`, and `test_view_decorators` in `tests/test_views.py`.

Only `tests/test_helpers.py` is emitted. Nevertheless top-level answerability is `answerable` with
an empty reason.

Bounded source proves `add_x_parachute` and `new_function` are nested helpers inside
`test_view_decorators`, not independently runnable pytest tests. Reporting all three as separate
“direct tests” inflates precision and causes the command-coverage ledger to count two impossible
standalone test targets.

**Floor.** Collapse nested helpers to their owning runnable test for recommendation purposes;
retain helper→target edges as proof. Emit a minimal command cover for every runnable direct test
file, or mark the answer incomplete with the exact uncovered set.

**CI gate.** `covered_runnable_direct_tests / runnable_direct_tests = 1.0`, with nested helpers
attributed to their owning test rather than counted independently.

## R2 — exact path closure and budget monotonicity are repaired (P0 fixed)

The exact packet now contains and grounds:

```text
Flask::__call__ → Flask::wsgi_app → Flask::full_dispatch_request → Flask::dispatch_request
```

At explicit budgets 10, 52, and 100:

- actual nodes are exactly 10, 52, and 100;
- status stays `answerable`;
- confidence stays 0.9951;
- the 10-node set loses zero nodes at 52;
- the 52-node set loses zero nodes at 100.

A separate `query` transport rerun at 10→100 also loses zero nodes. This independently re-derives
the fix and retracts the prior active finding. The known-anchor `final` packet now includes all four
path nodes; it previously omitted `full_dispatch_request`.

**Protect this.** Stable-prefix selection plus path closure is now at the intended floor on the
control. Add the exact 10→52→100 relation as a permanent regression gate.

## R3 — packet stability is fixed, answerability stability is not (P0/P1)

Two semantically equivalent path questions now produce:

- identical two-anchor sets (Jaccard 1.0, up from 0.455);
- identical 80-node packets (Jaccard 1.0, up from 0.472);
- the same exact four-node core path.

But their judgments diverge:

| Query form | Status | Confidence | Missing facets |
| --- | --- | ---: | --- |
| “Trace the call path from A to B” | `answerable` | 0.9951 | none |
| “Show the invocation chain … starting at A and ending at B” | `incomplete` | 0.2483 | `invocation carries wsgi flask`, `starting flask`, `ending flask` |

This is a powerful pseudo-oracle: the evidence is byte-equivalent, so a 4× confidence swing and
opposite actionability cannot be caused by graph coverage. It is caused by obligation/facet
interpretation.

The same pattern appears in five unique latency-sample paraphrases: every packet contains 52 nodes
and is fast, but boilerplate words added to make the query unique become missing facets and force
confidence 0.2483.

**Floor.** If required endpoint/relation obligations and the resulting packet are identical,
answerability and confidence must be identical within a tiny deterministic tolerance.

**CI gate.** For evidence-equivalent executions,
`status_equal && abs(confidence_a-confidence_b) < 0.01`.

## R4 — direct lookup is usable, but its receipt remains internally awkward (P1)

`Locate the definition of Flask.make_response` moved from `incomplete`, confidence 0.678 to
`answerable`, confidence 0.95, with the exact `Flask::make_response` anchor.

However, `missing_evidence` and facet coverage still report `definition flask` as unfulfilled.
An exact-symbol override apparently makes the result answerable despite a declared missing required
phrase. That may be the right product judgment, but the receipt needs to say the phrase was
non-required/ignored rather than leaving both states true.

## R5 — strict containment passes; scope-subset stability remains unchanged (P2)

The strict `src/flask/app.py` blast-radius query again returns zero out-of-scope nodes. This safety
invariant remains healthy.

The scoped packet still contains 15 of 31 nodes absent from the unrestricted 32-node packet, exactly
the baseline result. Scope restriction therefore reranks a new candidate pool rather than filtering
a stable unrestricted ordering. This is not a containment failure, but it limits reproducibility.

## R6 — scoped docs improved; unscoped truncation poisoning remains (P1)

The strict `docs/testing.rst` query moved from `incomplete`, confidence 0.15 to `answerable`,
confidence 0.234. The bad synthetic facet `client work` became the useful facet `client`, and all
three requested facets are fulfilled.

The unscoped query remains `partial` because the tangential `docs/api.rst` anchor is one of the 32
truncated documents. The official harness's only remaining invalid query is this unscoped doc case.

Confidence 0.234 for an answerable, fully facet-covered, scoped document packet is also poorly
calibrated in absolute terms. Status improved; confidence semantics did not become intuitive.

## R7 — history behavior is unchanged (P2)

The one-commit clone provides no qualifying fix history. A query explicitly asking for bug-fix
commits still returns release-note/document paragraphs, `history=null`, and `partial` due truncated
`CHANGES.rst`, rather than `unanswerable` for commit evidence with a labeled release-note fallback.

---

## Latency differential

| Operation | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| Full rebuild | 23.3 s | 3.7 s | **6.3× faster** |
| `validate-graph` wall | 4.1 s | 0.7 s | **5.9× faster** |
| `status --probe` wall | 5.5 s | 1.0 s | **5.5× faster** |
| `profile` wall | 2.4 s | 0.6 s | **4.0× faster** |
| Hot internal query | 172 ms best | 156–157 ms | modest improvement |
| Worst observed structural miss | 28.985 s | 1.141 s across five fresh samples | **25.4× lower worst case** |

Five unique structural cache misses on the same multi-hop class measured 968, 969, 984, 1000, and
1141 ms internal; total times were 1031–1219 ms. Every source receipt said semantics were not
requested. The prior 18–29 s cliffs did not reproduce anywhere in the current run.

This is excellent progress, but the theoretical floor remains below current miss latency. Graph
load plus bounded traversal over a 2.3 MB/5.9k-node graph should target <500 ms internal, and a
resident repeat should target <50 ms. The hot cached path is already evidence that another order of
magnitude is plausible in a resident process.

The cache counter defect prevents trustworthy hit-rate attribution, so the next performance gate
must pair stage timing with a canonical cache ledger.

---

## Unchanged CLI and telemetry defects

### Two advertised packet formats still fail

All ten advertised formats were rendered through `context --json --details --validate`.

- Valid: `lowlevel`, `sql`, `semantic_arrow`, `gg`, `gg_hybrid`, `gg_lex`,
  `gg_lex_hybrid`, `doc_summary`.
- Exit 1 / `unknown packet format`: `hybrid`, `svo`.

This is unchanged: 20% of the advertised packet enum remains dead.

Token proxy comparability is also unchanged. On the same four-node evidence:

- `lowlevel`: 515 characters, 64 proxy tokens;
- `gg`: 514 characters, 140 proxy tokens.

The installed real tokenizer should replace or validate format-specific proxies.

### CPG capability identity and selection remain split

`frontends` still calls CPG planned, unavailable, and unselectable. `platform capabilities` still
advertises a version-1 CPG provider, and `platform compile` executes it.

On the `wsgi_app` affected-test compile, the provider again emitted 5,772 nodes / 7,335 edges and
accepted 600 / 545, truncating 5,172 nodes and 6,790 edges. The final packet contains a `writes`
relation but still omits `test_session_using_application_root`, while the normal scanner/query path
now finds that exact test.

The advanced evidence path is therefore less query-effective than the normal graph for this
control. Query-conditioned provider selection remains the right theoretical improvement.

### Runtime probe and artifact drift remain

`status --probe` still infers module `Flask` from the display name and fails uppercase raw/src
imports, despite the console target `flask.cli:main` and target package `src/flask`.

`doctor` still reports the user Codex skill contract stale and project skill/plugin artifacts
missing. `artifacts --check` exits 1 and enumerates those missing/stale generated paths. These are
operational findings, not retrieval failures.

---

## Updated layered scorecard

| Layer | Weight | Baseline | Current | Ceiling | Why it moved or stayed |
| --- | ---: | ---: | ---: | ---: | --- |
| Build, exclusion, freshness, reproducibility | 10% | 8.8 | **9.5** | 10.0 | 6.3× scan speedup; independent identity still exact |
| Extraction and topology | 18% | 5.0 | **7.3** | 9.7 | Receiver resolution 27.7→61.2%; typed read/write evidence |
| Retrieval, anchoring, path selection | 18% | 5.6 | **8.7** | 9.8 | Exact path, final closure, monotonicity, and packet paraphrase stability fixed |
| Tests, blast radius, docs, history | 15% | 3.8 | **6.2** | 9.6 | Direct tests recovered; commands/docs/history remain partial |
| Answerability, confidence, abstention | 15% | 3.2 | **5.8** | 9.8 | Auto negative and canonical path fixed; equivalent evidence still diverges |
| Latency and cache | 10% | 4.4 | **7.8** | 10.0 | Large latency wins; cache counters still inert |
| CLI/packet/capability surface | 7% | 5.2 | **5.2** | 10.0 | Dead formats, token proxy, and CPG naming unchanged |
| IR, receipts, advanced compiler | 7% | 8.0 | **8.5** | 9.8 | Normal typed edges improved; advanced CPG selection did not |
| **Weighted fixture score** | **100%** | **5.2** | **7.4** | **9.8** | Core graph/retrieval advanced; trust contract now caps |

---

## Priority path from 7.4 to 10

1. **Completed post-evaluation — make answerability a function of evidence closure, not query
   wording.** The identical-packet paraphrase differential is now a permanent CI fixture.
2. **Completed post-evaluation — close runnable test commands, not raw test-file symbols.** Nested
   helpers are attributed as structural witnesses and runnable direct-test command coverage is 100%
   on the frozen Flask control.
3. **Completed post-evaluation — add a low-level exact relation lane.** MCP `query_relations` and
   CLI `relations` return caller/callee tuple IR in 1.3–1.8 ms warm on the self graph, with explicit
   truncation/topology/freshness gates, deterministic recovery opcodes, optional fused Git sync,
   and tests opt-in.
4. **Persist the relation index for cold queries.** Avoid materializing the full native graph when
   an exact one-hop lookup needs only symbol and adjacency records; retain transactional delta and
   manifest identity.
5. **Unify the quality/cache receipt schema.** One canonical budget, doc-count definition,
   topology denominator, cache namespace, and hit/miss ledger.
6. **Remove or implement dead advertised formats and use real token counts.** This remains a cheap,
   pure contract-correctness win.
7. **Hydrate requested doc spans on demand and isolate tangential truncation.** This would close the
   remaining unscoped documentation weakness without relying on the now-fixed path-query gate.
8. **Push typed obligations into advanced providers.** The normal path now proves the value of
   focused writes/reads; the global CPG path should return the same witness without discarding ~90%.
9. **Finish operational polish.** Correct import-module inference and synchronize generated skill
   artifacts.

### Single scalar to adopt now

The prior report proposed:

```text
required_obligation_closure = proven_required_obligations / required_obligations
```

The updates make this even more compelling. The graph and packet can now remain identical while
confidence changes 0.995→0.248 because wording creates extra lexical obligations. A typed closure
scalar would stay 1.0 for both endpoint/path-equivalent queries and 0.0 for the fantasy query.

Gate exact lookup/path/affected-test fixtures at 1.0 and require that evidence-equivalent runs have
identical closure and answerability.

---

## What is now at or near the floor

Protect these with regression gates:

1. **Full-scan reproducibility:** active and independent graphs are byte-semantically identical by
   categorized node/edge comparison.
2. **Exclusion receipts:** ignored/default/explicit prunes, frontend fallback/failure, document
   truncation, and phase timings remain excellent.
3. **Exact qualified anchoring:** the canonical endpoints anchor directly and stably.
4. **Path closure:** the four-node Flask request chain is present at the smallest tested budget and
   in known-anchor `final`.
5. **Budget monotonicity:** both `context` and `query` preserve smaller packets at larger budgets.
6. **Packet validation:** 4/4 official packets and 8/8 implemented formats validate.
7. **Explicit and automatic negative behavior:** impossible queries now become honestly empty and
   unanswerable.
8. **Typed affected-test evidence:** the exact `wsgi_app` write relationship and known direct test
   are recovered with provenance.
9. **Idempotence:** identical commands produce identical packets/anchors.
10. **Topology caveats:** `select` still states that zero callers are an upper bound and prints the
    exact 61.2% receiver-resolution denominator.

---

## Coverage and non-claims

Tested: rebuild, validation, doctor/status/profile, exact and compound context, every main query
class used in the prior run, explicit and auto negative controls, affected tests, known-anchor final,
snippets, select, budgets through both CLI paths, paraphrases, strict scope, packet formats, cache
telemetry, provider capabilities/compile, artifact check, and the official live harness.

Not tested: source implementation, GraphGraph Git history, MCP transport, full GraphGraph or Flask
tests, eval task files, incremental update/remove equivalence, mutation commands, semantic rebuild,
HTTP resident service, federation, memory, temporal episodes, trace ingestion, install/hooks, or
security. These are **not passes**.

The existing `docs/findings/fixtures/flask_suite.json` was deliberately not read or used as evidence;
the direct source oracle and prior frozen commands were sufficient.

---

## Artifacts

Created or replaced:

- `resources/flask/.graphgraph/graph.gg`
- `resources/flask/.graphgraph/graph.gg.manifest.json`
- `resources/flask/.graphgraph/kv_cache.json`
- `resources/flask/.graphgraph/skill-validation/live.graph.gg`
- `resources/flask/.graphgraph/skill-validation/report.md`
- this report

Delete only `.graphgraph/skill-validation` to remove harness artifacts. Deleting all of
`.graphgraph` removes the rebuilt active graph and caches. No Flask source file changed.

Historical findings were intentionally removed by the user to keep the findings directory fresh.
This document is therefore self-contained. The GraphGraph worktree also contained unrelated user
implementation changes and an untracked source file before this report was added; this run did not
modify any of them.

---

## Bottom line

The updates moved GraphGraph from “strong substrate with unreliable task closure” to “strong Python
context graph with credible exact retrieval and incomplete trust semantics.” The hard wins are real:
twice the call density, more than double receiver resolution, direct affected-test recovery, stable
path packets, correct automatic abstention, and a sixfold faster rebuild.

The next cycle should not chase more raw edges first. It should preserve the new two-lane rule:
exact adjacency stays indexed and minimal; ambiguous/multi-hop work keeps full evidence planning.
Across both lanes, one semantic rule must remain universally true:

> **The same evidence must produce the same obligation closure, confidence, answerability, and
> runnable action set—regardless of harmless query wording or which CLI receipt renders it.**

When that rule holds, the current graph quality is sufficient to support a much higher agent-trust
score. Until then, 7.4/10 is the honest place to stand.

## Addendum — global-project-attention Phase 0 (2026-07-28)

This cycle converted the new global-project-attention proposal from prose into
an evaluator-only research substrate. It does **not** change production
retrieval and does **not** support H1–H8.

Implemented artifacts:

- `src/graphgraph/research/attention_field.py`: hierarchy/cover invariants,
  exact small-graph PPR, an exact budgeted tree-DP ceiling, greedy candidate,
  top-k baseline, effective-influence receipt, and GRC/EAMC/RWC/error metrics;
- `eval/context-system-research.json`: validated atomic claims, candidates,
  experiments, evidence, and promotion state;
- `tests/test_attention_field_research.py`: deterministic invariants,
  counterexamples, and independent brute-force checks of the tree DP; and
- `benchmarks/context_graph/global_attention_phase0.py`: reproducible Phase 0
  receipt included by the context-graph benchmark runner.

Measured boundaries:

1. Positive mass on every node is mechanically true for the exact PPR fixture,
   so “nonzero influence” is not an operational GPA definition.
2. GRC=1 is a cover identity, not a utility result.
3. Under uniform-within-cell reconstruction, exact L2 error is nonincreasing
   with budget and reaches zero at leaf resolution.
4. One-step greedy is not generally optimal: a deterministic six-leaf,
   five-unit case has 42.67% more L2 regret than the exact tree-DP optimum.
5. Monotonicity is objective-specific: an L2-optimal budget increase lowers L2
   while increasing L1 on a deterministic counterexample.
6. Sparse residual entities count as exact mass in both EAMC and RWC; the prior
   prose RWC formula omitted this term and has been corrected.

The promotion contract now also distinguishes adapter-independent invariants
from cross-model empirical performance. Global-default claims require a
preregistered transfer matrix spanning unrelated closed and open-weight model
families, context regimes, prompt/tool protocols, and tokenizers. A
single-provider win remains provider-scoped.

Current decision: retain the exact oracle and formula-first tournament
infrastructure; reject one-step greedy *optimality*; keep every downstream and
cross-model hypothesis pending until equal-cost held-out experiments exist.

## Addendum — global-project-attention Phase 1 (2026-07-28)

The first static multiresolution candidate was implemented behind the research
boundary, not production retrieval. `C1-PATH-L2MASS-001` builds a deterministic
bounded-arity directory/file/entity hierarchy and greedily minimizes

$$
J_{0.01}(P)=
\sum_{K\in P_{\mathrm{aggregate}}}
\left[
\sum_{v\in K}\left(a_v-\frac{m_K}{|K|}\right)^2
+0.01m_K
\right].
$$

Candidate compilation received only task starts and full PPR. Gold topology
evidence entered after candidate and flat packets were frozen. The baseline
received the same compact exact-node renderer and no greater serialized token
budget.

Across 24 tasks on frozen GraphGraph, Chess, Express, and Requests graphs, the
64-unit aggregate result was:

- C1 exact recall: `0.482`;
- C1 resolution-weighted recall: `0.491`;
- equal-token flat exact recall: `0.469`;
- resolution gain: `+0.022`; and
- exact-recall loss: `-0.013` (C1 was better).

The aggregate hid a transfer failure. GraphGraph (`+0.139`) and Requests
(`+0.060`) cleared the `+0.02` resolution-gain gate. Chess (`-0.129`) and
Express (`+0.017`) did not. The registered result is therefore **no champion**
and the exact formula/weight is rejected as a cross-project default.

The experiment also found an implementation limit before scoring: an
unbounded directory fanout can make a hierarchy cell impossible to refine
under the entire packet budget. Deterministic range cells now cap refinement
arity at eight. Incremental token accounting replaced an initially quadratic
flat-baseline selector and is proved equivalent to brute-force rendering in
tests. Mean full PPR was about `46 ms`; warm candidate compilation ranged from
roughly `0.19–0.24 s`, while the first cold hierarchy materialization remains a
separate optimization target.

Decision: retain the tested hierarchy, receipts, renderer, exact formula
oracle, and equal-token harness. Do not alter the production default. Any
weight/formula tuning must use these four projects as development/validation
data and then face a newly frozen repository holdout set.

### Phase 1 formula-family stop result

A four-weight mass-penalty sweep and a four-weight normalized-log-resolution
sweep were run at 32 and 64 units using worst-project selection. Neither
produced a formula champion.

The mass sweep confirmed an algebraic limitation: when an internal cell is
replaced only by internal children, $\sum_i m_{K_i}=m_K$, so the term
$\lambda m_K$ cancels and cannot steer the early choice. A deterministic test
now fixes that limit. The normalized log-size term does produce positive
internal refinement value, but its least-bad configuration still had
worst-project gain `-0.090` and maximum exact-recall loss `+0.258`. At 64 units
the exact-loss maximum reached `+0.347`.

Decision: stop tuning coefficients in the current soft objective family. The
next candidate must guarantee an exact frontier structurally, using sparse
exceptions subtracted from the aggregate far field, before spending the
residual token budget on resolution.
