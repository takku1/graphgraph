# Fresh gray-box analysis: GraphGraph on Express and the theoretical ceiling

Date: 2026-08-01  
Target: `C:\Users\dcarn\aiprojects\resources\express` (Express 5.2.1)  
GraphGraph: 0.1.0  
Method: gray-box execution plus GraphGraph's own telemetry, checked against Express source as the direct oracle

## Post-implementation verification (same-day update)

The baseline below is retained as the reproducible pre-fix observation. The
implementation work driven by it has now landed locally and was re-run against a
clean, non-incremental Express scan at `C:\tmp\express-cpg-final.gg`.

### Important measurement correction

The baseline denominator of 6,336 receiver sites was inflated by attributing
nested callback calls to every enclosing callable. Correct innermost-callable
ownership yields 1,510 internal receiver sites. This is a source-attribution
correction, not a filtering trick: the new graph contains more call edges and
each resolved receiver retains its evidence string. On the corrected denominator,
the final scan reports 1,315 resolved and 195 unknown receivers, or **87.09%**.
The tool reports 100% trusted resolution among emitted resolved edges, but that
self-reported precision is not an independent hand-labelled 98% oracle; positive
and adversarial fixtures are the available corroboration.

### Final receipts

| Gate | Baseline | Post-fix result |
|---|---:|---:|
| Express nodes / edges | 3,439 / 5,546 | 3,486 / 12,139 |
| Internal receiver evidence | 180 / 6,336 (2.84%, inflated denominator) | 1,315 / 1,510 (87.09%) |
| Unknown internal receivers | 6,156 | 195 |
| Golden request path | incomplete | answerable, 5 nodes / 4 edges / 116 proxy tokens |
| Equivalent-query core overlap | 5.26% | 100% (same 5 nodes and 4 edges) |
| `affected_tests(app::handle)` | no evidence, no command | answerable; 80 proven static file units, 4 isolated conservative candidates, 0 proven units omitted |
| Package status | empty | npm, `express` 5.2.1, manifest-derived test script |
| Packet choice | static `gg` floor claim | exact rendered minimum among identity-safe valid candidates |
| Semantic sidecar consistency | node-text signature only | atomic v4 sidecar coupled to full active node/edge graph version |
| Repository regression suite | not run | full suite passes; Ruff reports zero lint errors |

The exact and paraphrased path queries both recover:

`createApplication --contains--> app --calls--> app.handle --calls--> Router::handle`

with the bounded lifecycle prerequisite
`createApplication --calls--> app.init`. The constraint selector reports
`minimum_directed_facet_connector_v1`, and packet/receipt semantic validation
passes.

Affected-test retrieval now separates graph callables from executable test
units. The 1,178 reverse-reachable callable nodes collapse to 80 distinct test
file commands with static paths to `app::handle`; four additional package-import
witnesses are isolated as conservative candidates rather than promoted to the
affected set. The receipt is `answerable`, reports zero omitted proven units,
keeps the strongest 12 expanded paths, and exposes a complete compact inventory
for the remaining units. An adversarial callable in the same test file but with
no evidence path is not absorbed into the unit's membership.

Command generation also checks the package script. Express hardcodes `test/`
and `test/acceptance/` in `npm test`, so appending a file would still run the
whole suite. The focused command is instead compiled from the manifest runner
while replacing its positional targets, for example:

`npm exec -- mocha --require test/support/env --reporter spec --check-leaks test/app.request.js`

The remaining precision frontier is runtime coverage and test-dependence
provenance, not static inventory completeness. Static paths establish change
impact; they do not prove that every path executes in a particular run.
The repository validation after this change is 1,098 passing tests plus 124
passing subtests; Ruff is clean on every touched Python file.

### Design decisions checked against prior research

- Demand-driven refinement is preferable to an always-maximal whole-program
  analysis. Reps, Horwitz, and Sagiv formulate precise interprocedural analysis
  as realizable-path graph reachability, while Sridharan and Bodík show how
  client-driven refinement can concentrate context-sensitive points-to cost on
  queried variables: [IFDS graph reachability](https://www.cs.tufts.edu/comp/150CMP/papers/reps95reachability.pdf),
  [refinement-based points-to analysis](https://manu.sridharan.net/files/pldi06.pdf).
- JavaScript call graphs remain sensitive to language and module coverage; a
  recent comparative study found that only a minority of evaluated tools could
  process current multi-file Node modules. That supports GraphGraph's explicit
  package summaries, abstention, and evidence provenance rather than a claim of
  universal static soundness: [Static JavaScript Call Graphs](https://arxiv.org/abs/2405.07206).
- Minimal connected evidence is a better objective than a union of lexical
  neighborhoods. G-Retriever explicitly casts graph retrieval as a
  prize-collecting Steiner-tree problem; GraphGraph uses a deterministic bounded
  connector specialized for code evidence instead of importing its learned
  model: [G-Retriever](https://arxiv.org/abs/2402.07630).
- Elastic-style hybrid retrieval is useful as a candidate generator, not as the
  proof layer. Reciprocal-rank fusion combines incomparable ranked lists without
  score calibration, but structural claims still require typed edges and
  receipts: [original RRF publication record](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/),
  [Elasticsearch RRF contract](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).
- Static and dynamic test evidence should remain distinct. A large-scale study
  found materially different fault-detection sets between static and dynamic
  techniques, supporting explicit `transitive_static` / `runtime_observed`
  tiers rather than treating either as a substitute for the other:
  [Luo, Moran, and Poshyvanyk](https://arxiv.org/abs/1801.05917).
- A minimal affected set can still be unsafe when tests depend on order or
  shared state. Dependent-test-aware selection may add prerequisite tests with
  little average runtime cost, so future runtime provenance should model
  test-to-test dependencies as well as test-to-code coverage:
  [Lam et al., ISSTA 2020](https://homes.cs.washington.edu/~mernst/pubs/dependent-tests-issta2020-abstract.html).

Updated overall assessment: **8.6/10 today**, with the same credible **9.4/10
ceiling**. The concentrated blocker moved from call-path extraction and static
affected-test completeness to independent cross-language validation, runtime
coverage, and test-dependence provenance.

## Baseline executive verdict (pre-fix)

GraphGraph is already a disciplined graph lifecycle and evidence-calibration system, but on this JavaScript target it is not yet a dependable program-understanding system for multi-hop call paths or affected-test selection.

The hard operational foundation works well: two independent scans were structurally identical, graph and packet validation passed, exact lookup was concise, no-op update avoided a write, budget growth was monotone, and the negative control produced a calibrated abstention rather than a plausible hallucination. The telemetry is unusually candid about limitations.

The layer that caps everything above it is JavaScript value-flow extraction. Only 180 of 6,336 receiver-bearing member-call sites had receiver evidence (2.84%); the selected multi-hop packet reported just 1.6% global call-edge coverage. Express's central request path is present in source and all endpoint symbols are indexed, but the graph does not connect `createApplication`, the callable `app`, `app.init`, lazy `Router` construction, `app.handle`, and `this.router.handle`. A test query consequently returned zero affected tests and zero commands even though `test/app.router.js` imports Express and drives the app through Supertest in 66 test cases.

Current score: **6.2/10**. Credible ceiling with the existing lifecycle, telemetry, and ontology: **9.4/10**. The ceiling is credible because the surrounding design is already strong; the missing capability is concentrated in extraction, provenance, and retrieval selection rather than persistence or graph integrity.

## Scope and evidence discipline

This was a fresh evaluation. I did not read GraphGraph implementation source, version-control history, or prior findings reports. I used GraphGraph as an end user through MCP and CLI. I read only the Express target source, bounded GraphGraph-produced snippets, ignore rules, and package manifest to establish ground truth.

The required exclusion audit retained source, tests, examples, and documentation. Explicit scan exclusions were `.code-review-graph` and `.graphgraph`; built-in exclusions pruned three directories. The scan honored `.gitignore`. `semantic.json` remained in the corpus and appeared as a dirty JSON node; it was pre-existing and was not opened or treated as authoritative evidence.

Artifacts created by this run:

- `resources/express/.graphgraph/graybox-20260801.gg`
- `resources/express/.graphgraph/graybox-rebuild-20260801.gg`
- this report

No Express source file was changed. To remove only the generated evaluation graphs:

```powershell
Remove-Item -LiteralPath 'C:\Users\dcarn\aiprojects\resources\express\.graphgraph\graybox-20260801.gg'
Remove-Item -LiteralPath 'C:\Users\dcarn\aiprojects\resources\express\.graphgraph\graybox-rebuild-20260801.gg'
```

## Instrument validation: the red test

Before trusting answerability or quality telemetry, I asked an explicit negative query:

> Where does Express implement its PostgreSQL ORM schema migration engine and generated SQL migration planner?

Observed:

- status: `unanswerable`
- answerability confidence: 0.1
- packet: 0 nodes, 0 edges, 0 tokens
- all three requested facets were reported unfulfilled
- response explicitly abstained
- receipt-consistency validation remained `ok`

This is internally consistent. Semantic validation checked packet/receipt consistency while answerability separately declined the question. The instrument therefore demonstrated that it can produce a bad/empty value and did not emit contradictory green metrics. Downstream telemetry is usable, subject to the specific caveats below.

## Baseline receipts

### Fresh scan

| Metric | First scan | Independent rebuild |
|---|---:|---:|
| Nodes | 3,439 | 3,439 |
| Edges | 5,546 | 5,546 |
| Source nodes | 3,092 | 3,092 |
| Documentation nodes | 231 | 231 |
| Wall time reported by scanner | 3,044 ms | 3,153 ms |
| Symbol extraction | 1,907 ms | 2,041 ms |
| Documentation extraction | 450 ms | 468 ms |
| Concept linking | 265 ms | 290 ms |
| Validation | pass | pass |
| Frontend fallbacks/errors | 0 | 0 |

The attributed phase totals covered 99.96-99.97% of reported scan wall time. `graph_change` between the independent builds reported no added, removed, or changed node or edge. This is strong determinism evidence.

Three documentation files were explicitly reported as truncated: `History.md`, `Readme.md`, and `examples/README.md`. No absence claim in this report relies on their truncated content.

### Installation and transport surface

`graphgraph doctor` reported:

- Python 3.12.10 and tree-sitter available
- 15 ready tree-sitter languages, including JavaScript
- real FastEmbed embeddings configured
- tiktoken installed
- the installed Codex skill contract is `STALE`
- the target's project-local skill artifacts are missing

Three isolated CLI `status --probe` runs took 475.7, 467.1, and 444.5 ms. Several surrounding MCP/harness calls experienced roughly 70 seconds of delay that was absent from GraphGraph's internal phase receipts and absent from the isolated CLI runs. This evaluation cannot attribute that delay to GraphGraph core; it should be treated as transport/harness overhead until traced across the MCP boundary.

## Findings

### F1 — Critical: JavaScript receiver/value-flow coverage caps structural retrieval

**Symptom.** A `multi_hop_path` query for the central Express request path returned an incomplete packet. At a 20-node budget it selected 20 nodes and 23 edges but did not produce the requested path. Raising the budget to 80 expanded the packet to 28 nodes and 31 edges without completing the path.

GraphGraph's own extraction telemetry explains the ceiling:

- receiver sites: 6,336
- resolved: 180
- unknown receiver: 6,156
- receiver evidence ratio: 2.84%
- selected-packet global call-edge coverage: 1.6%
- candidate edges: 0
- concept support: 27 of 3,207 eligible nodes, or 0.84%, below the declared 20% supported threshold

**Direct oracle.** Bounded Express source shows the path:

1. `lib/express.js:36` defines `createApplication`.
2. Its callable `app` invokes `app.handle(req, res, next)` at line 38.
3. `mixin(app, proto, false)` adds the application methods and `app.init()` is called at line 54.
4. `lib/application.js:59` lazily constructs `new Router(...)` through `this.router`.
5. `lib/application.js:152` defines `app.handle`.
6. `app.handle` invokes `this.router.handle(req, res, done)` at line 177.

GraphGraph indexed `createApplication`, `app`, `app::init`, `app::handle`, and `app::use` as exact nodes. It therefore has the endpoint facts but lacks the value/property-flow edges needed to connect them.

**Inferred cause.** This is consistent with a syntax-first CST extractor that recognizes declarations and only resolves member calls when receiver evidence is already local and unambiguous. Express stresses precisely the missing analyses: callable objects, prototype mixins, property assignment, lazy getters, `this` binding, and an external `Router` package. This is an inference from observed behavior and telemetry, not a source-level diagnosis of GraphGraph.

**Floor.** The answer is a bounded evidence subgraph of roughly 5-7 nodes and 4-6 typed edges. Once receiver summaries exist, retrieval should be an indexed path query measured in milliseconds and should emit no unrelated sibling methods.

**Gap.** Receiver evidence is approximately **35.2x below full coverage** (`1 / 0.0284`). Task utility is worse than the ratio suggests: path completion is 0/1 despite all endpoint symbols being extracted. The 20-node packet spent 482 proxy tokens and remained unanswerable; an ideal path packet should fit in roughly 150-250 tokens.

**What if.** Add a demand-driven JavaScript code-property graph pass with object-shape and points-to facts. A practical progression is:

1. Represent function-objects and property writes explicitly.
2. Propagate properties across known mixin/copy helpers.
3. Add flow-sensitive local points-to and `this`/getter resolution.
4. Store external package API summaries for `Router`.
5. Use bounded, query-driven refinement around anchors instead of whole-program maximum precision.

The relevant theoretical families are abstract interpretation, points-to analysis, object-sensitive call graphs, SSA/value-flow, and IFDS/IDE-style demand-driven dataflow. Full soundness is unnecessary; provenance and calibrated confidence allow useful partial results without inventing hard edges.

### F2 — High: affected-test provenance and package metadata are disconnected

**Symptom.** An explicit `affected_tests` query for `app.handle` in `lib/application.js` returned:

- direct tests: 0
- transitive tests: 0
- structural witnesses: 0
- test commands: 0
- uncovered roots: `app::handle`, `app::enabled`
- status: `incomplete`, reason `no affected-test evidence was found`

Fresh `project_status` also reported an empty package object: no ecosystem, name, version, scripts, or runtime probes.

**Direct oracle.** The graph itself indexes `package.json`. Its source states:

- name `express`, version `5.2.1`
- dependency `router ^2.2.0`
- dev dependencies `mocha` and `supertest`
- test command `mocha --require test/support/env --reporter spec --check-leaks test/ test/acceptance/`

`test/app.router.js` imports Express through `require('../')`, imports Supertest, and invokes `request(app)` repeatedly. It contains **66 `it(...)` cases**. `test/Router.js` contains another 39 cases and directly invokes `router.handle(...)` many times. Returning no evidence or runnable command is therefore a false negative for practical regression selection, even if exact per-line coverage is unavailable.

**Inferred cause.** Package-manifest normalization is not feeding the status/test-command layer, and static topology cannot bridge the callable app through Supertest into request dispatch. The absence of package metadata and call evidence compounds: the selector has neither provenance edges nor an execution command from which to derive dynamic evidence.

**Floor.** Reading one root `package.json` is O(file size), about 100 lines here. A conservative test selector could immediately return `test/app.router.js` as an import/behavior witness and the manifest-derived Mocha command, clearly marked as transitive or file-level rather than line-level proof.

**Gap.** Observed result is 0 recommendations versus at least one high-confidence behavior file and one directly executable project command. This is a categorical 0% stratum, not a tuning gradient.

**What if.** Treat test selection as provenance fusion rather than only reverse calls:

- normalize package/workspace manifests into first-class ecosystem and command nodes;
- add import-to-entrypoint and framework-semantic summaries (`supertest(requestableApp)` invokes the app callback);
- ingest coverage/runtime traces as `observed_calls` edges, which GraphGraph's ontology already declares;
- preserve the evidence mode on every recommendation: direct static, transitive static, runtime observed, or conservative import witness;
- solve command selection as weighted set cover over changed roots and witnessed tests.

This would make GraphGraph useful before perfect static analysis arrives and allow dynamic evidence to validate or refute candidate static edges.

### F3 — High: semantic equivalence is not stable in the current effective retrieval path

**Symptom.** Two semantically equivalent structural-only queries at the same 20-node budget produced only 2 common node descriptors out of 38 unique descriptors: **5.26% Jaccard overlap**. Their path-descriptor overlap was also 5.26%.

Base query:

> Trace the path from createApplication through app.handle to Router dispatch.

Paraphrase:

> Show how application creation reaches request handling and router dispatch.

The exact phrasing anchored `app::handle` and expanded mostly across `lib/application.js`. The paraphrase shifted into acceptance and request tests plus documentation containment. Neither completed the path.

Default source planning did not repair this. It reported a stale semantic index, zero semantic seeds, no semantic rebuild, and lexical/structural fallback. Concept linking was independently reported as sparse at 0.84%.

**Evidence.** This violates the metamorphic expectation that equivalent path requests over a fixed graph should substantially overlap in their core evidence. The comparison used complete 20-node packets, not truncated prefixes.

**Inferred cause.** Independent lexical anchor ranking dominates because the semantic index is not transactionally fresh and the concept registry covers almost none of the eligible graph. Broad expansion then follows containment from whichever lexical anchor wins.

**Floor.** Once a query is normalized into the same facet constraints, both phrasings should resolve the same terminal set and differ only in low-ranked optional context. Core-node Jaccard should approach 1.0.

**Gap.** 5.26% observed overlap versus a proposed 70% minimum gate is a 64.74 percentage-point shortfall.

**What if.** Couple the lexical graph, embedding index, and concept facts under one graph version and atomically refresh them. Normalize each query into typed terminals and constraints, then retrieve a minimum connecting subgraph rather than unioning neighborhoods around independently ranked anchors. The theoretical model is a prize-collecting Steiner tree or constrained shortest-path problem with provenance-aware edge costs. Semantic embeddings choose terminals; graph structure proves connections; neither substitutes for the other.

### F4 — Medium: the declared packet token floor is not the observed floor

**Symptom.** `describe_formats` declares `gg` as the measured token floor for non-empty structural packets and describes SVO as approximately 1.1x. On two independently sized packets over the same node/edge sets, SVO was smaller:

| Shape | `gg` tokens | SVO tokens | SVO advantage |
|---|---:|---:|---:|
| 2 nodes / 1 edge | 50 | 32 | 36.0% |
| 20 nodes / 23 edges | 482 | 396 | 17.8% |

Both `gg` and SVO packets validated with exactly the same node and edge counts. Hybrid was substantially larger (85 and 1,149 tokens respectively), as declared.

**Evidence.** The striking result was re-derived on a small and a larger stratum and validated independently. It is not an absence claim or a truncated comparison.

**Inferred cause.** A global format ranking is being presented as if it were invariant across packet shapes. Schema overhead, label repetition, edge density, and identifier length change the crossover point.

**Floor.** For a known packet, render candidate encodings or estimate their exact token cost and choose the minimum that preserves the requested semantics. Since rendering is linear in an already bounded packet, selection cost should be negligible.

**Gap.** Static `gg` selection spent 22-56% more tokens than the observed minimum in these two cases (`50/32` and `482/396`).

**What if.** Use minimum-description-length packet selection: choose format per packet shape and model tokenizer, with semantic-feature constraints. Rewrite the declaration from “one universal floor” to a measured envelope by node count, edge density, fact density, and tokenizer.

### F5 — Medium: installation self-diagnosis is good, but the active contract is stale

**Symptom.** `doctor` accurately reports a stale global Codex skill contract and missing target-local artifacts while the MCP tools remain callable.

**Evidence.** This is a self-reported caveat and should be preserved. It explains a real operational hazard: agents may use an older workflow contract against a newer CLI/MCP implementation.

**Floor.** Installed contract version/hash should match the executable version at startup, or the client should refuse ambiguous instructions with one repair command.

**Gap.** One stale global contract; no project-local contract. The core tool still ran, so this is an operational consistency risk rather than a retrieval failure.

**What if.** Negotiate a machine-readable capability/contract version during MCP initialization and include it in each receipt. Skills can then be generated or selected by protocol version instead of relying on separately cached files.

## Metamorphic and invariant results

| Test | Relation | Result |
|---|---|---|
| Negative/null | Missing feature must abstain or lower confidence | Pass |
| Full-build determinism | Same source and options produce same graph | Pass: zero graph delta |
| Query idempotence | Same cached query produces same packet, anchors, quality, and control receipt | Pass |
| Budget monotonicity | Raising 20 to 80 nodes must preserve the smaller result set | Pass; 20 nodes expanded to 28 |
| No-op update safety | Unchanged exact path must not rewrite graph | Pass: `write_performed=false` |
| Packet validation | Summary counts match parsed packet | Pass for `gg` and SVO |
| Semantic equivalence | Paraphrase preserves core evidence | Fail: 5.26% Jaccard |
| Package consistency | Indexed manifest populates package/status metadata | Fail: manifest present, metadata empty |
| Test evidence | Known behavior tests yield witnesses/commands | Fail: zero evidence and commands |
| Claimed token floor | Declared floor is smallest for equivalent packet | Fail in both tested size strata |

Not tested:

- true-change incremental equivalence against a fresh rebuild
- deletions and rename repair
- history/as-of behavior
- multi-repository federation
- memory and episode retrieval
- runtime trace ingestion
- non-JavaScript language strata
- full test-suite execution
- large-corpus scaling

These areas are not passes.

## What is already near the floor

Do not destabilize these while fixing extraction:

- **Scan determinism:** independent builds were graph-identical.
- **Attribution:** scan receipts accounted for more than 99.9% of internal wall time.
- **Validation:** graphs and packets validated with consistent counts.
- **Calibrated abstention:** the red query returned no packet and a precise reason.
- **Honest caveats:** call coverage, semantic sparsity, documentation truncation, freshness, and stale installation state were explicitly surfaced.
- **No-op behavior:** exact unchanged update avoided persistence.
- **Bounded output:** all queries respected node budgets and exposed proxy-token counts.
- **Exact lookup:** `createApplication` was found unambiguously and answered in a 2-node/1-edge packet.

These are valuable and difficult foundations. The report's low multi-hop verdict should not be misread as a need to rewrite the lifecycle or telemetry layers.

## Architecture for maximum practical potential

The highest-leverage design is one evidence graph with progressively stronger facts, not parallel stores that disagree.

### 1. Transactional, versioned evidence IR

Each graph version should atomically identify:

- syntax/declaration graph version;
- module/package manifest version;
- points-to/value-flow summary version;
- semantic embedding/concept index version;
- runtime trace/coverage version;
- extraction and policy version.

Queries should know exactly which layers are fresh. A stale semantic index should be rebuilt, explicitly disabled, or produce a hard capability downgrade before routing—not silently behave as lexical retrieval while a real embedding backend is advertised.

### 2. Demand-driven JavaScript CPG

Build cheap whole-repo facts first, then refine only the cone around query terminals:

- module and export/import graph;
- function-object and object-shape facts;
- property definitions, getter/setter facts, prototype and mixin propagation;
- local SSA/value-flow and context-sensitive `this` facts;
- demand-driven points-to sets and candidate member calls;
- external package summaries.

Keep uncertain `calls_candidate` edges non-traversable by default, as the ontology already specifies, but make them available to a refinement pass. A query can pay extra analysis cost only where candidate disambiguation would connect required facets.

### 3. Provenance semiring and evidence fusion

Every edge should carry provenance and confidence: syntax exact, type-inferred, points-to inferred, package summary, documentation, runtime observed, or user memory. Path confidence should compose explicitly rather than collapse to a single global “trust” label.

Dynamic `observed_calls` should confirm paths and affected tests without replacing static evidence. Coverage can establish that `test/app.router.js` reaches `app.handle`; static imports preserve usefulness when coverage is absent.

### 4. Constraint-first retrieval

Parse the question into required terminals, relation constraints, scope, and output intent. Solve for a minimal connected evidence subgraph. This prevents sibling explosion, makes paraphrases invariant after terminal normalization, and provides a proof of incompleteness when no path exists under trusted edges.

For compound questions, use facet-wise terminal sets and a prize-collecting Steiner-tree/set-cover objective. Penalize containment-only branches when the requested relation is execution. Require each selected branch to pay rent by covering a facet or connecting terminals.

### 5. Adaptive encoding

Select packet encoding after retrieval using exact tokenizer cost and semantic requirements. Small or edge-dense packets may favor SVO; other structural packets may favor `gg`. The optimum is an envelope, not one permanent format.

### 6. First-class test command graph

Normalize manifests before symbol retrieval. Represent commands, test roots, workspaces, filters, and coverage artifacts as graph nodes. Select test commands by coverage of changed roots, with explicit receipts for each chosen test and command.

## Scores by layer

| Layer | Today | Credible ceiling | Rationale |
|---|---:|---:|---|
| Graph lifecycle, persistence, validation | 8.8 | 9.6 | Deterministic builds, honest validation, safe no-op update |
| Telemetry and calibration | 8.4 | 9.5 | Excellent caveats/red-test behavior; format and package contradictions remain |
| Symbol/document extraction | 7.2 | 9.2 | Rich symbol graph, no frontend fallbacks; docs truncate and concepts are sparse |
| Call/value-flow extraction | 2.8 | 9.0 | 2.84% receiver evidence is the binding constraint |
| Retrieval and routing | 5.4 | 9.4 | Exact lookup/abstention strong; path and paraphrase weak |
| Test impact/commands | 2.5 | 9.2 | Zero result on a well-tested path and empty manifest metadata |
| Packet efficiency | 7.5 | 9.7 | Compact and validated, but static format choice misses observed floor |
| **Weighted overall** | **6.2** | **9.4** | Extraction currently caps downstream layers |

## Proposed CI gates

The single scalar to watch first is **trusted receiver evidence ratio on the frozen Express fixture**, currently 2.84%. It directly measures the layer that caps path and test retrieval. The first milestone should be at least 50% with trusted-resolution precision held at or above 98%; the credible mature target is at least 80%. This scalar must be paired with golden-path correctness so it cannot improve by relabeling unknown calls as confident.

Concrete gates:

1. Negative control remains `unanswerable`, confidence <= 0.2, and packet nodes = 0.
2. Express golden path connects `createApplication`, `app.init`, `app.handle`, and `router.handle` in <= 12 nodes and <= 250 proxy tokens.
3. Equivalent path paraphrases have normalized core-node Jaccard >= 0.70.
4. Trusted receiver evidence ratio >= 0.50 initially, with trusted precision >= 0.98.
5. `affected_tests(app::handle)` includes `test/app.router.js` as at least a transitive/runtime witness and emits a runnable Mocha command.
6. Fresh status reports package name `express`, version `5.2.1`, ecosystem `npm`, and the manifest test script.
7. Chosen packet format costs no more than 1.05x the minimum valid candidate format for the same packet.
8. Independent full builds have zero graph delta.
9. Exact unchanged update performs no write.
10. CLI `status --probe` p95 < 750 ms on this machine; MCP receipts separately expose server, queue, serialization, and client overhead.
11. Documentation truncation and semantic/call coverage warnings remain explicit; they must never be converted into silent success.

## Bottom line

GraphGraph is functioning well as a deterministic, bounded, self-aware graph substrate. It is not currently near its theoretical potential as a JavaScript reasoning engine because the graph has names without enough value-flow, test provenance, or fresh semantic terminal mapping to connect them.

The shortest route to maximum practical potential is not broader lexical retrieval. It is a demand-driven JavaScript CPG joined transactionally with package metadata, semantic indexes, and runtime evidence, followed by constraint-based minimal-subgraph retrieval and adaptive encoding. If that one extraction/provenance spine is added while preserving the existing abstention and receipt discipline, the system can plausibly move from 6.2/10 to the low-to-mid 9s without replacing its core lifecycle.
