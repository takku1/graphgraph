# Critical gray-box evaluation: GraphGraph as a universal, snap-context graph tool

Date: 2026-07-30
Evaluator: Codex, using GraphGraph only through its public MCP/CLI interfaces and self-reported telemetry
Verdict: **6.2/10 today; credible 9.6/10 ceiling; not yet a hands-off 10/10 graph tool**

## Corrections made during the run

Two dramatic-looking observations were retracted after independent checks. They are recorded first so they cannot survive as false findings.

1. **Retracted: “Graphify took 202 seconds.”** The 202 seconds included approval and host-runner wait. The command itself reported 1.6 seconds. The valid Graphify comparison is output quality and boundedness, not that apparent latency.
2. **Retracted: “`graph_change` produced a path-sensitive false positive on identical graph bytes.”** Exact-file updates are persisted in `.gg.delta` sidecars. Hashing only the base `.gg` ignored the effective delta state. `graph_change` was reading the active base-plus-delta graph. The corrected finding is that no-op exact-file refreshes changed effective graph state.

These corrections materially change the diagnosis and are part of the evidence discipline of this run.

## Executive verdict

GraphGraph is already the best of the three tested tools for **natural-language structural retrieval with explicit trust receipts**. It is especially strong when the caller already has an exact node ID: the one-hop relation API returned the verified Flask caller in 0.57 ms and explicitly said why the result was complete within the graph but not complete in reality. Compact `gg` packets are useful, deterministic on repeat, budget-monotone in the tested case, and substantially less noisy than the Graphify traversal baseline.

It is not yet safe to use as an invisible, universal context reflex. The layer that decides what the user meant and whether the answer is sufficient is weaker than the graph packet itself. Across the 14 positive hand-labeled tasks, mean node recall was **0.779**, MRR **0.714**, NDCG@10 **0.479**, and **10/14 (71.4%)** tasks achieved complete node recall. However, **6/10 (60%)** of those complete-recall tasks were still labeled incomplete. Conversely, an Express request-path query was labeled answerable even though the returned packet contained **zero call edges** and only file containment/import structure.

The most important conclusion is therefore layered:

- The compact structural substrate is often excellent.
- Extraction quality is sharply language- and boundary-dependent.
- Automatic intent routing, facet construction, and sufficiency decisions currently cap the end-to-end experience.
- Incremental update equivalence is not yet a safe invariant.
- The system can become exceptional without changing its core identity, but a 10/10 claim would be premature.

## Scope and fixtures

GraphGraph source and version history were not read. Public help, documentation packets, graph outputs, telemetry, and target-repository source were permitted. Target source was read only to establish direct ground truth.

| Fixture | Commit | Stratum | Fresh graph | Build receipt |
| --- | --- | --- | ---: | --- |
| Flask | `954f5684e4841aad84a8eec7ace7b81a0d3f6831` | Python, documentation-heavy | 5,868 nodes / 16,086 edges | 41.62 s |
| Express | `18e5985b8a9d5e8423db0a9121f22bdaecd5b120` | JavaScript, external router boundary | 3,434 nodes / 5,186 edges | 24.96 s |
| ripgrep | `227381db0ee83dfa4341f1e27ff9617c0f5ad992` | Rust, multi-crate workspace | 4,866 nodes / 14,062 edges | 32.23 s |

All three builds used the current `tree_sitter` frontend, symbol depth, documentation extraction, audited ignore rules, explicit graph/tool-output exclusions, and separately named graph files. All three validated successfully with zero frontend fallbacks, parse errors, grammar errors, or timeouts.

The committed hand-labeled task fixtures are:

- `docs/evaluation/graybox-cycles/2026-07-30-flask-graybox-tasks.json`
- `docs/evaluation/graybox-cycles/2026-07-30-express-graybox-tasks.json`
- `docs/evaluation/graybox-cycles/2026-07-30-ripgrep-graybox-tasks.json`

## Instrument validation

The evaluation instrument passed its primary red control. The committed nonexistent-symbol task scored node recall 0.0, MRR 0.0, and NDCG 0.0. A malformed packet also produced `ok=false` with `unknown packet format`. The metrics can therefore move to a bad value and are not decorative.

The self-eval calibration result is weaker evidence than its headline suggests. Its red task is excluded from calibration because its expectations do not resolve, leaving four positive tasks and a positive base rate of 1.0. The new fixtures include explicit `expected_answerable=false` tasks, producing negative calibration bins in all three repositories.

Cross-fixture calibration, weighted over 17 labeled tasks, was approximately:

- Brier score: **0.155**
- ECE: **0.249**
- Worst observed MCE: **0.95**

The sample is intentionally small and diagnostic, not a production benchmark.

## Scorecard

| Category | Today | Credible ceiling | Current limiter |
| --- | ---: | ---: | --- |
| Build safety and validation | 7.5 | 9.8 | 95–97% of build wall time is outside reported timed phases |
| Exact lookup and one-hop relations | 8.5 | 10.0 | Human-qualified labels do not reliably resolve without an ID lookup |
| Natural-language retrieval | 7.0 | 9.8 | Mean recall 0.779; large language/query-class variance |
| Multi-hop paths | 5.5 | 9.7 | Rust trace recall 0.4; Express false-answerable path with zero call edges |
| Architecture synthesis | 4.5 | 9.5 | Anchor bias and no facet accounting for broad architecture prompts |
| Blast radius | 5.5 | 9.6 | Relevant neighborhoods, but partial topology and weak test integration |
| Affected tests and commands | 6.0 | 9.8 | Excellent Rust command; incomplete Flask/Express coverage |
| Documentation grounding | 6.0 | 9.7 | Honest warnings, but systematic truncation and routing/facet failures |
| Incremental freshness/equivalence | 4.0 | 10.0 | 0/3 no-op updates were structurally empty deltas |
| Abstention and calibration | 5.5 | 9.8 | Negative behavior depends on query class; 60% false-incomplete rate |
| Packet/token efficiency | 8.0 | 9.9 | Compact normal path; audit envelope is 2.1–22× packet characters |
| Warm latency and workflow fluidity | 7.0 | 9.9 | Fast warm core, but cold outliers and multi-step ID/class selection remain |
| Format/interoperability contract | 6.0 | 10.0 | Only 6/10 advertised formats generated and validated end-to-end |

Unweighted mean: **6.2/10**. This is not a claim of scientific precision; it is a decision aid. Universal use is capped by the weakest required layer, not rescued by the average.

## Retrieval results by language

| Fixture | Positive tasks | Mean recall | Complete recall | Mean MRR | Mean NDCG@10 | Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flask | 4 | 1.000 | 4/4 | 0.875 | 0.697 | 0.025 |
| Express | 4 | 0.625 | 2/4 | 0.375 | 0.145 | 0.162 |
| ripgrep | 6 | 0.733 | 4/6 | 0.833 | 0.557 | 0.244 |
| Combined | 14 | **0.779** | **10/14** | **0.714** | **0.479** | — |

The strata are categorically different, not merely noisy. Full-scan receiver-resolution telemetry was 61.4% for Flask Python, 34.0% for ripgrep Rust, and 2.24% for Express JavaScript. GraphGraph correctly labels these global topology states partial or low. The end-to-end sufficiency gate does not always act on those caveats.

## Findings

### F1 — The graph packet can be right while the answerability gate says it is wrong

**Symptom.** The Flask lifecycle packet contained all six source-verified nodes—`wsgi_app`, `full_dispatch_request`, `preprocess_request`, `dispatch_request`, `finalize_request`, and `process_response`—and the exact call edges between them. The response was nevertheless `incomplete` and abstained because the generated facet `flask request dispatch view execution` was unfulfilled. Three of four complete-recall Flask tasks were labeled incomplete. Across all fixtures, 6/10 complete-recall tasks were labeled incomplete.

**Evidence.** Direct source lines confirmed the chain: `wsgi_app -> full_dispatch_request`, then preprocessing, dispatch, exception handling, finalization, and response processing. The eval harness independently scored node recall 1.0.

**Inferred.** Facet construction and facet-to-evidence matching are less robust than graph retrieval. This is an inference about layer boundaries, not implementation.

**Floor.** A sufficiency decision should agree with complete labeled retrieval and should never discard a packet that already contains every required node and edge.

**Gap.** 60% false-incomplete rate on complete-recall tasks.

**What if.** What if sufficiency were judged from the actual evidence needed to complete the user’s task, with paraphrase-tolerant facets and an automatic second look before abstaining?

### F2 — Automatic routing does not yet make query-class expertise disappear

**Symptom.** An implementation prompt asking to add a hook, identify change points, helpers, and focused tests was classified as `reverse_lookup`. It returned four nodes, omitted response processing, and recommended one transitive session test. Forcing `subsystem_summary` recovered the main lifecycle packet. A query explicitly beginning “According to GUIDE.md” was routed to `subsystem_summary` with confidence 0.147 instead of `doc_summary`. Natural nonexistent-feature questions were routed to `direct_lookup`, producing “partial result” rather than the explicit `unanswerable` behavior obtained when `negative_query` was forced.

**Evidence.** Routing receipts, facet receipts, and forced-class differential runs.

**Inferred.** Keyword-level intent signals are dominating compound task structure in some prompts.

**Floor.** One natural request should be enough. The user should not need to know query classes or retry strategies.

**Gap.** Manual class selection changed both evidence quality and abstention semantics in three critical workflows.

**What if.** What if every request automatically decomposed into lookup, path, documentation, change-point, and test facets, ran each only as far as needed, then returned one merged packet?

### F3 — Semantic equivalence is not invariant enough for invisible context retrieval

**Symptom.** Two natural paraphrases of the Flask lifecycle request had a packet-node Jaccard of 0.459. The first contained all six expected lifecycle nodes; the paraphrase retained five and lost `process_response`.

**Evidence.** Same graph, same explicit query class, same 36-node budget, source mode off. Exact-query repeats were byte-identical.

**Inferred.** Anchor/facet selection is sensitive to wording even after query-class control.

**Floor.** Equivalent task wording should preserve all task-critical evidence even if noncritical neighborhood nodes differ.

**Gap.** Critical-node recall changed from 6/6 to 5/6.

**What if.** What if task-critical evidence were invariant to paraphrase, while only optional context varied?

### F4 — Exact ID-based relations are close to the floor; label resolution is the remaining friction

**Symptom.** `query_relations` on the exact Flask node ID returned the sole verified caller, provenance, confidence, and topology caveat in 0.57 ms. The equivalent ripgrep call returned the one resolved caller in 0.53 ms. Passing documented human qualifications such as `Flask::full_dispatch_request` and `WalkBuilder::build` returned `not_found`. `search_nodes("WalkBuilder::build")` ranked the `WalkBuilder` struct above the exact `build` method.

**Evidence.** Direct relationship calls plus source `rg` ground truth.

**Inferred.** The low-level traversal is strong; human-to-ID resolution is the bottleneck.

**Floor.** The measured sub-millisecond exact traversal is effectively at the useful floor and should be protected.

**Gap.** A normal user must perform an extra search and sometimes still choose between ambiguous results.

**What if.** What if every human-qualified symbol resolved as reliably as an exact node ID, including overloaded and external members?

### F5 — JavaScript and external dependency boundaries are a categorical weak stratum

**Symptom.** Express full-scan telemetry reported 143 resolved member calls and 6,246 receiver sites without evidence, for a 2.24% receiver-resolution ratio. A request-path query was labeled answerable with confidence 0.665 even though its packet had zero call edges. `Route.dispatch` lives in the external `router` dependency, while `test/Route.js` contains 13 direct invocations. The caller query scored recall 0.0, and affected-tests retrieval returned no test command.

**Evidence.** Graph telemetry plus direct source search in `lib`, `package.json`, and `test/Route.js`.

**Inferred.** The graph does not carry enough external package topology or receiver evidence to close this execution path.

**Floor.** When a requested path crosses an unmodeled dependency, the answer must either traverse that dependency or explicitly stop at a named boundary. It must not call containment/import context a completed execution path.

**Gap.** Zero call edges in an answerable path packet; 0.0 recall for a source-confirmed caller/test file.

**What if.** What if dependency boundaries were first-class, so every path either continued across them or ended with a precise, low-cost abstention receipt?

### F6 — No-op incremental refresh is not structurally invariant

**Symptom.** Re-extracting one unchanged source file into an isolated graph copy produced valid, fresh graphs, but none of the three effective deltas was empty:

- Flask: `semantic_operator_equality_comparison` changed.
- Express: `semantic_operator_equality_comparison` changed.
- ripgrep: one import edge added and five cross-file reference edges removed.

Update latency was 2.16 s for Flask, 4.15 s for Express, and 1.74 s for ripgrep.

**Evidence.** Full build versus exact-file refresh, with source untouched and active base-plus-delta comparison through `graph_change`. The initial base-file-only hash interpretation was retracted above.

**Inferred.** Some derived or cross-file evidence is not reconstructed identically by the full and incremental paths.

**Floor.** An unchanged-file update must produce an empty effective graph delta. This is a strict invariant, not a tuning goal.

**Gap.** 0/3 no-op fixtures passed exact structural equivalence.

**What if.** What if any refresh—full, incremental, watched, or agent-triggered—always converged to the same graph state, making freshness invisible and trustworthy?

### F7 — Architecture synthesis is anchor-driven rather than coverage-driven

**Symptom.** A Flask architecture prompt explicitly named eight subsystems. The 80-node packet anchored heavily on testing and CLI symbols, omitted a facet receipt, and was labeled answerable at confidence 0.242. The evidence/change-point list centered on `FlaskCliRunner`, `FlaskClient`, and routing exceptions rather than a balanced architecture map. Adding evidence and hierarchy compiler passes produced a valid packet but retained the same anchor bias.

**Evidence.** `query_context` and `compile_context` differential outputs. The code-review-graph baseline had no communities in its current graph and therefore did not provide a superior architecture oracle.

**Inferred.** Broad architecture questions are being satisfied by a dense local neighborhood rather than explicit subsystem coverage.

**Floor.** Every named subsystem should have at least one representative node, its role, and its principal cross-subsystem relationship—or be listed as missing.

**Gap.** The response was answerable without proving coverage of the requested architecture dimensions.

**What if.** What if architecture packets were balanced maps of responsibilities and boundaries, with coverage visible at a glance and no subsystem able to crowd out the rest?

### F8 — Affected tests are strong in one Rust case but incomplete and weakly calibrated overall

**Symptom.** For `WalkBuilder::build`, GraphGraph returned focused `ignore` crate tests and the command `cargo test -p ignore walk::tests --lib`; it executed successfully with 15 passing tests. For Flask `full_dispatch_request`, it repeatedly returned only `test_session_using_application_root`, which is relevant only transitively and is far from the behavioral coverage visible in `test_basic.py`. For Express `Route.dispatch`, it missed `test/Route.js` entirely. The Flask command could not be verified in the clone because the project and Werkzeug were not installed.

**Evidence.** Direct command execution for ripgrep, direct test-body inspection for Flask, and source counts for Express.

**Inferred.** Test selection is strongest when tests and implementation share an explicit in-repository type/module structure; it degrades across indirect client behavior and external dependencies.

**Floor.** Recommendations should separate direct contract tests, transitive regressions, and environment readiness, with precise coverage receipts for each.

**Gap.** One excellent stratum, one sparse stratum, and one total miss.

**What if.** What if every proposed change automatically arrived with the smallest runnable, environment-valid test set and an honest statement of what remained untested?

### F9 — Documentation handling is honest but not complete enough for seamless use

**Symptom.** Full builds reported document truncation in 32/115 Flask documents, 3/23 Express documents, and 6/23 ripgrep documents. GraphGraph correctly surfaced partial-document warnings. However, an explicit GUIDE question routed incorrectly, and forcing `doc_summary` still marked the verb phrase `ripgrep decide` as an unfulfilled entity facet. The forced mode returned more grounded document nodes but still abstained.

**Evidence.** Build receipts and auto-versus-forced documentation queries.

**Inferred.** Truncation and code-oriented facet parsing interact to make documentation answers appear incomplete even when relevant passages are present.

**Floor.** A named-document question should route deterministically, retrieve the exact relevant section, and distinguish corpus truncation from query misunderstanding.

**Gap.** 17–28% of documents were reported truncated in these fixtures, and the explicit named-document query did not route to the document mode.

**What if.** What if documentation felt like an exact extension of source: named sections appeared instantly, long files never hid relevant passages, and partial evidence was obvious but nonblocking?

### F10 — The packet-format capability declaration is broader than the working end-to-end surface

**Symptom.** `describe_formats` advertised ten formats. End-to-end generation plus `validate_packet` succeeded for `gg`, `semantic_arrow`, `gg_hybrid`, `gg_lex`, `gg_lex_hybrid`, and `doc_summary`. `lowlevel` and `sql` generated output but the validator reported unknown format. `svo` and `hybrid` were rejected by `final_packet` because the generated packet failed validation.

**Evidence.** Same graph, starts, class, and budget across all format calls.

**Inferred.** Capability description, renderer availability, and validator coverage are not using one effective contract.

**Floor.** Every advertised selectable format must generate and validate through the same public path.

**Gap.** 6/10 formats passed end to end.

**What if.** What if every declared capability were executable, self-validating, and impossible to advertise before it was ready?

### F11 — Build telemetry does not explain the dominant cost

**Symptom.** Full builds took 24.96–41.62 seconds. Reported documentation and source-concept phases accounted for only:

- Flask: 2.09 s of 41.62 s; approximately 95.0% unattributed.
- Express: 0.71 s of 24.96 s; approximately 97.2% unattributed.
- ripgrep: 0.98 s of 32.23 s; approximately 97.0% unattributed.

Warm natural queries generally took 0.1–3.1 seconds. One first-use Flask budget experiment took 39.9 and 53.8 seconds, then the same query at a repeated budget fell from 4.8 seconds to 1.3 seconds with a byte-identical packet. The long outlier did not reproduce after warm-up.

**Evidence.** MCP client timing, build receipts, cache hit receipts, and exact packet comparison.

**Inferred.** A substantial cold or query-shape-dependent cost exists, but current telemetry cannot localize it. No cause is asserted.

**Floor.** Dominant work must be visible before it can be optimized. Warm exact relations are already at the useful floor; full-build and cold-query cost are not.

**Gap.** 95–97% unattributed build time; a nonreproduced 40–54 second cold outlier.

**What if.** What if every request felt warm, every expensive phase named itself, and cost scaled only with the new evidence required for the answer?

### F12 — Packet compression is real; proof receipts are still too expensive in audit mode

**Symptom.** Normal MCP output returned compact packets directly. In audit mode, full JSON envelope size divided by packet size was:

- Direct lookup: 9.91× characters.
- Multi-hop path: 3.64×.
- Affected tests: 5.28×.
- Negative lookup: 21.95×.
- Architecture summary: 2.13×.

Packet proxy-token counts ranged from 80 to 2,294 in this sample. The exact Flask caller eval used 101 estimated tokens. The Graphify baseline spent its 2,000-token budget on a 221-node traversal beginning from three generic `Response` nodes and was truncated. The code-review-graph natural-language traversal found no matching start node, while its exact caller query was correct.

**Evidence.** Same-task tool outputs and measured string sizes. Character ratios are not claimed to be tokenizer-exact.

**Inferred.** GraphGraph has the strongest compact structural representation of the tested tools, but detailed receipts duplicate too much evidence for routine use.

**Floor.** A normal packet should carry enough proof to validate freshness, topology quality, missing facets, and next action without multiplying packet size.

**Gap.** Audit overhead of 2.1–22× packet characters.

**What if.** What if the smallest packet always carried a tiny, sufficient proof of why it was the right packet?

## Baseline comparison

| Same Flask task | Result |
| --- | --- |
| GraphGraph natural-language path | Retrieved the complete six-node lifecycle in a bounded structural packet; incorrectly labeled it incomplete |
| Graphify DFS, 2,000-token budget | Started from three generic `Response` nodes, found 221 nodes, and truncated before producing a focused path |
| code-review-graph free-form traversal | No node matched the full natural-language task |
| GraphGraph exact caller | Correct caller plus provenance and topology caveat in 0.57 ms |
| code-review-graph exact caller | Correct caller and extracted edge with confidence 1.0 |

GraphGraph’s differentiated advantage is not raw graph traversal alone. It is the combination of natural-language anchoring, compact topology, source locations, freshness, and caveats. The weaknesses are the decisions surrounding that packet.

## Invariants and gates for the next critical run

These are proposed fail/pass gates, not implementation prescriptions.

1. **No-op convergence:** 100% of unchanged-file refreshes produce zero effective node and edge changes across every supported language.
2. **Critical paraphrase invariance:** at least 0.95 recall of task-critical nodes across five paraphrases; optional-neighborhood Jaccard may vary.
3. **Answerability agreement:** at least 0.95 precision and recall against complete-retrieval labels; no answerable path packet with zero path-family edges.
4. **Automatic routing:** at least 0.95 intent accuracy on compound implementation, named-document, negative, path, blast-radius, and affected-test tasks.
5. **Language floor:** hand-labeled call/path recall at least 0.90 per supported language, or explicit abstention when topology evidence is below the threshold.
6. **External boundary honesty:** 100% of dependency-crossing path queries either continue across the boundary or name the exact stopping boundary.
7. **Affected-test utility:** at least 0.80 precision and 0.90 behavior-facet recall; every emitted command is environment-ready or explicitly marked not runnable.
8. **Format contract:** 10/10 advertised formats generate and validate end to end.
9. **Build attribution:** at least 90% of wall time assigned to named phases; no phase omitted if it exceeds 5%.
10. **Latency:** cached exact relation P95 below 10 ms; warm natural query P95 below 500 ms; one-file refresh P95 below 300 ms; no unexplained query above 2 seconds.
11. **Receipt cost:** default proof metadata no more than 15% of packet size or 100 proxy tokens, whichever is larger.
12. **Architecture coverage:** every requested subsystem represented or explicitly missing; no answerable architecture packet with uncovered requested dimensions.

The single most valuable CI scalar is **no-op effective delta size**. It is cheap, language-agnostic, assumption-free, and moves immediately when incremental equivalence improves. The gate is exactly zero.

## What if GraphGraph reached the practical limit?

What if asking a question was enough—no mode selection, no symbol hunting, no budget choice, no “try a broader query” instinct?

What if GraphGraph recognized the whole task behind the sentence: the facts to find, the path to prove, the boundaries to cross, the tests to run, and the uncertainty that still mattered?

What if every answer arrived as the smallest complete working set: exact change points, the few relationships that justify them, the relevant documentation, the smallest credible test set, and a tiny receipt proving freshness and coverage?

What if paraphrasing never changed the essential evidence, larger budgets only added optional context, and refreshing an unchanged repository changed absolutely nothing?

What if external dependencies, generated code, runtime behavior, documentation, history, and prior agent decisions all felt like one continuous graph—while still being visibly different kinds of evidence?

What if GraphGraph knew when a path ended at the edge of its knowledge and made that boundary more useful than a plausible guess?

What if it carried the current working set forward automatically: after research, the implementation packet was already waiting; after the edit, the affected tests were already selected; after the tests, the next likely task was already grounded?

What if cold starts disappeared from the user’s experience, expensive work happened only once, and every subsequent question felt like touching a thought already held in working memory?

What if the proof of correctness cost almost nothing—small enough to include every time—so speed and trust stopped competing?

At that point GraphGraph would not feel like a graph tool. It would feel like context had become ambient: snap your fingers, know the relevant world, act, verify, and continue.

## What is already near the floor

Do not lose these strengths while closing the gaps:

- Exact ID-based one-hop traversal is sub-millisecond and unusually honest about topology completeness.
- Valid `gg` packets are compact, deterministic on exact repeat, and budget-monotone in the tested relation.
- Source locations and bounded snippets were exact in the Flask lifecycle oracle.
- Freshness and extractor-compatibility receipts prevented stale legacy graphs from being mistaken for current evidence.
- Build exclusion receipts were explicit, and all fresh graphs validated with zero frontend fallback or parse failure.
- Forced negative-query behavior produced an empty packet, explicit abstention, and low confidence.
- Rust test-command derivation produced a real, focused command that passed 15 tests.

## Coverage ledger

Tested:

- Capability and format declarations
- Red/invalid instrument controls
- Full builds and exclusion receipts
- Graph validation and project status
- Direct lookup, reverse lookup, multi-hop, blast radius, affected tests, documentation, negative queries, subsystem summaries
- Source snippets and exact one-hop relations
- Automatic versus forced routing
- Idempotence, budget monotonicity, paraphrase equivalence, strict scope
- Full-versus-no-op incremental equivalence
- Graph change receipts
- Advanced evidence/hierarchy compilation
- Repair context
- Graphify and code-review-graph representative baselines
- One generated Rust test command

Not tested and therefore not passed:

- History/recent-change graphs built with `--history`
- Cross-repository federation quality
- Memory write/read isolation and long-session retention
- Temporal `graph_at_time` correctness
- Real changed-file incremental equivalence after a semantic edit
- File deletion/removal equivalence
- Watch mode and concurrent writer behavior
- Very large repositories above 15,000 active nodes with the current extractor
- C/C++, Java, C#, Go, Ruby, PHP, Kotlin, Scala, Swift, TSX
- Refactoring or autonomous source mutation, which was outside this evaluation’s authorization

## Artifacts

Persistent reproducibility artifacts created by this run:

- Fresh graphs and manifests under each fixture’s `.graphgraph/graybox-2026-07-30.gg*`
- The three task JSON files beside this report
- This report

Temporary evidence copies were created under `C:\tmp\gg-*-incremental-20260730.gg*`. The ripgrep test generated ignored Cargo build output under `target/`. Failed Flask test startup may have touched ignored pytest cache state. No target repository source file was edited.

## Final decision

Use GraphGraph today for:

- fast exact relations once an ID is known;
- compact, source-located structural orientation;
- freshness-aware retrieval;
- Rust/Python call-path assistance when topology receipts are acceptable;
- a first-pass packet that an agent verifies against source before editing.

Do not yet delegate without supervision:

- automatic compound research-to-implementation routing;
- JavaScript execution paths crossing package boundaries;
- complete architecture summaries;
- exhaustive affected-test selection;
- no-op-safe incremental graph maintenance;
- any workflow that treats `answerable` or `incomplete` as ground truth without reading the packet receipt.

GraphGraph’s hard and valuable part—the compact, evidence-bearing structural substrate—is real. The next leap is to make the orchestration as trustworthy and effortless as the packet core.
