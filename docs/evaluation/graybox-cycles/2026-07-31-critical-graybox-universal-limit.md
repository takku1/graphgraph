# Critical gray-box run: the green board is real, universality is not

Date: 2026-07-31  
Evaluator: Codex, using GraphGraph only through public MCP/CLI behavior and self-reported telemetry  
Verdict: **6.1/10 today; credible 9.8/10 ceiling; not yet a hands-off universal graph tool**

## Executive verdict

GraphGraph now clears its intended Locus acceptance board. With focused test execution enabled, all 13 cases passed, the two previously pending P0 cases selected real tests, and the board reported `release_ready=true`. Compact packet selection remains excellent: an exact Flask packet was deterministic, budget-monotone, and rendered in 37–56 ms; exact relationship traversal reported less than 1 ms of internal work. A repeated natural exact-caller query fell from 1.17 s to 172 ms with a byte-identical packet and an explicit cache hit.

That success is real but narrow. The expanded run found hard blockers outside the acceptance board:

- A direct, hand-known polyglot fixture contained 15 elementary call edges. GraphGraph extracted every important definition but only 1/15 call edges in the initial full graph.
- On the same initial fixture, code-review-graph found all 5/5 `Root -> Middle` edges. It was about 14x slower to build, but it proved these edges were practically extractable.
- A fresh C# graph returned zero exact callers for a method with many source-confirmed callers and a direct test. The low-level API caveated the zero correctly, but the natural-language layer still labeled a zero-call-edge packet answerable.
- All four no-op exact-file updates against valid fresh graph copies failed. MCP returned an empty `-32000`; the CLI exposed an `AssertionError`.
- Real edit and deletion splices converged exactly to full rebuilds, but a one-file edit took 10.19 s while the clean rebuild of the 10-file fixture took 4.70 s.
- Standalone scoped memory worked, but `query_context` consumed zero memories even after adding one to the default graph-local store.
- A historical view from before the fixture's first commit returned the same 42 nodes and 50 edges as a view after the commit. A `recent_changes` query returned only README text and was marked answerable.
- Exact search over a federated Flask + fixture graph found both repositories. A natural comparison named both but returned only Flask evidence and was still marked answerable.
- Only 6/10 advertised packet formats generated and validated end to end, unchanged from the prior run.

The conclusion is layered. The compact packet core and intended Locus workflow are strong. Extraction completeness, state continuity, temporal truth, cross-repository task coverage, and the sufficiency gate still prevent GraphGraph from becoming ambient context that can be trusted without supervision.

## Scope and evidence discipline

GraphGraph implementation source and version history were not read. Public help, doctor/status output, graph packets, manifests, receipts, benchmark artifacts, and target-repository source were allowed. Target source was read only to establish direct ground truth.

The instrument was red-tested before green metrics were trusted:

- An invalid packet returned `ok=false`, `format=unknown`, and `unknown packet format`.
- A nonexistent Kubernetes gRPC subsystem produced zero required-facet coverage, explicit abstention, confidence 0.15, and no affected-test command.
- The same negative task moved MRR and NDCG to 0.
- The sealed acceptance board dropped to 8/13 with five release blockers on an intentionally incompatible fixture, proving the board can report failure.

No absence claim in this report comes from truncated command output. Striking counts were re-derived using either the complete small graph, direct source search, a second implementation, or full-rebuild equivalence.

## Fixtures and fresh builds

All foreign-repository builds used the current `tree_sitter` frontend, symbol depth, documentation extraction, audited ignore rules, explicit graph-output exclusions, and isolated output under `C:\tmp\gg-critical-20260731`.

| Fixture | Stratum | Nodes / edges | Wall time | Named docs + concept time | Unattributed wall time | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Flask | Python, docs-heavy | 5,868 / 16,106 | 18.85 s | 3.19 s | 83.1% | valid, fresh |
| Express | JavaScript, package boundary | 3,439 / 5,224 | 43.20 s | 3.79 s | 91.2% | valid, fresh |
| ripgrep | Rust workspace + history | 4,900 / 14,141 | 58.91 s | 1.60 s | 97.3% | valid, fresh |
| UniGetUI | C#, 1,091 files | 6,903 / 15,131 | 96.81 s | 5.52 s | 94.3% | valid, fresh |
| Polyglot oracle | Python, JS, Rust, C#, Go | 43 / 52 | 1.81 s | 0.007 s | 99.6% | valid, fresh |

The build receipt is safe and useful, but it still does not explain the dominant cost. History makes the ripgrep timing non-comparable with the previous no-history build; no claim is made that extraction alone regressed by that full amount.

Documentation truncation remained material: Flask 32/115 files, Express 3/23, ripgrep 6/23, and UniGetUI 3/37.

## Frozen retrieval benchmark: no meaningful movement

The three hand-labeled task files from 2026-07-30 were rerun unchanged against fresh current graphs.

| Fixture | Positive tasks | Mean node recall | Complete recall | Positive-task mean MRR | Prior recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flask | 4 | 1.000 | 4/4 | 0.875 | 1.000 |
| Express | 4 | 0.625 | 2/4 | 0.375 | 0.625 |
| ripgrep | 6 | 0.733 | 4/6 | 0.833 | 0.733 |
| Combined | 14 | **0.779** | **10/14** | **0.714** | **0.779** |

The prior board therefore did not improve in recall. JavaScript member-call receiver resolution rose from 2.24% to 2.83%, but the labeled retrieval outcomes did not move. Current full-scan receiver-resolution ratios were Python 64.28%, JavaScript 2.83%, Rust 34.0%, and C# 8.27%.

One positive metamorphic result did improve: both controlled Flask lifecycle paraphrases retained all 6/6 critical nodes. Their full packet-node Jaccard was 0.511, so optional context still varied heavily, but critical recall no longer changed in this pair.

## Scorecard

| Category | Today | Credible ceiling | Current limiter |
| --- | ---: | ---: | --- |
| Build safety and validation | 7.0 | 9.9 | Valid outputs and good exclusions; 83–99.6% of wall time unattributed |
| Definition extraction and indexing | 8.5 | 10.0 | Simple definitions are strong; docs can truncate |
| Call and dependency topology | 4.0 | 9.9 | 1/15 direct-oracle call edges; severe JS/C# receiver gaps |
| Exact lookup and packet core | 8.5 | 10.0 | Fast and deterministic once the right node and edge exist |
| Natural-language retrieval and routing | 6.5 | 9.9 | Frozen recall unchanged; compound tasks still mis-focus |
| Multi-hop paths | 6.0 | 9.8 | Flask good; Rust path recall 0.4; cross-boundary paths incomplete |
| Architecture and blast radius | 4.5 | 9.8 | Named dimensions are not coverage-gated |
| Affected tests and commands | 6.5 | 9.9 | Excellent Locus/Rust board; C# direct test missed |
| Documentation grounding | 6.0 | 9.8 | Honest partial warnings; named-doc routing and truncation remain |
| Incremental freshness and equivalence | 5.0 | 10.0 | Edit/delete converge; no-op crashes and edit can be slower than rebuild |
| Memory, temporal, and federation continuity | 3.5 | 9.8 | Surfaces exist; end-to-end task integration is incomplete |
| Abstention and calibration | 6.0 | 9.8 | Negative controls good; zero-edge answerable cases remain |
| Packet and token efficiency | 7.0 | 9.9 | Compact packet floor; proof envelopes can dominate context |
| End-to-end latency and fluidity | 6.0 | 9.9 | Warm hits can be fast; class/repo variance and cold spikes remain |
| Format and transport contract | 6.5 | 10.0 | Transport parity passes; only 6/10 formats work end to end |

Unweighted mean: **6.1/10**. The precision is only a decision aid. Universal delegation is capped by the weakest required layer, not rescued by the average.

## Findings

### F1 — The intended acceptance board is green, but it does not establish universality

**Symptom.** On the Locus graph, all 13 sealed cases passed after enabling execution. Eight generated test commands each selected at least one test in the type-change case, two focused commands selected tests in the frontend case, and the board reported a clear release floor.

**Evidence.** Public `platform acceptance` output and real command execution.

**Counter-evidence.** `project_status` simultaneously reported the Locus graph as stale and extractor-incompatible. Acceptance controls displayed `fresh:-` but still passed. The board also does not cover the new polyglot direct oracle, C#, end-to-end memory, temporal reconstruction, federated compound coverage, or all packet formats.

**Inferred.** The board is an excellent regression suite for a known Locus-centered contract, not a universal product oracle.

**Floor.** A release-ready claim for universal use must be freshness-gated and must include every capability whose failure can corrupt or omit context.

**Gap.** 13/13 on the intended board; multiple total failures immediately outside it.

**What if.** What if the green board meant every supported workflow, language, repository boundary, and continuity feature had crossed the same evidence bar?

### F2 — Elementary call topology is missing even when every definition is present

**Symptom.** The known fixture implemented `Root -> Middle -> Leaf` plus a test calling `Root` in Python, JavaScript, Rust, C#, and Go. The complete initial 43-node graph contained 1/15 required call edges: only the Python test-to-root edge.

**Evidence.** The entire small graph was rendered, so truncation is impossible. Source was created as the direct oracle. After adding a second Python root callee, full rebuild and incremental update agreed, but GraphGraph retained only the new `root -> bonus` edge and still omitted `root -> middle`.

**Differential.** code-review-graph found all 5/5 initial `Root -> Middle` edges. Its caller resolution had its own same-name false associations, but it proved the missing same-file callees were extractable. GraphGraph built the fixture in 1.81 s versus 25.82 s for code-review-graph, about 14.3x faster.

**Inferred.** GraphGraph's speed advantage currently comes with a material extraction-completeness gap on elementary same-file calls.

**Floor.** Direct, unambiguous same-file call edges on a hermetic fixture should be 100% complete in every advertised ready language.

**Gap.** 6.7% initial call-edge recall; 0/5 same-file root callees.

**What if.** What if GraphGraph kept its build-speed advantage while never dropping an obvious relationship the source makes explicit?

### F3 — Exact relation honesty does not consistently constrain natural answerability

**Symptom.** Direct source search found many `TelemetryHandler.InstallPackage` callers and a test in UniGetUI. The exact relation call returned zero neighbors and correctly said the result was only complete within a partial graph. The natural query returned the method, its containing class, a sibling, and a lexically matching test name, contained zero call edges, and was labeled answerable at confidence 0.665.

**Evidence.** Direct source lines, exact relation receipt, and natural packet topology.

**Inferred.** The sufficiency layer can treat lexical/containment evidence as satisfying a relationship question even when the topology layer explicitly lacks the relationship.

**Floor.** A caller/path answer with zero relevant edges must abstain or explicitly name the missing evidence boundary.

**Gap.** Source-confirmed nonzero caller set versus graph zero; false answerable natural result.

**What if.** What if every answerability decision inherited the strongest caveat from the evidence it depended on?

### F4 — No-op incremental update regressed from wrong delta to hard failure

**Symptom.** Re-extracting an unchanged file into valid copied graphs failed for Flask, Express, ripgrep, and UniGetUI. MCP returned an empty `-32000`. The public CLI raised `AssertionError`. All four input graphs validated immediately before and after the failed call.

**Evidence.** Four-language repetition plus independent packet validation.

**Contrast.** A real Python edit succeeded and converged exactly to a clean rebuild. A real deletion also succeeded, removed the node, and converged exactly.

**Floor.** An unchanged-file refresh is the easiest incremental case: return a valid zero-delta receipt and mutate nothing.

**Gap.** 0/4 no-op cases completed. The real one-file edit took 10.19 s versus 4.70 s for a clean rebuild of the entire 10-file fixture; deletion took 1.40 s versus 7.40 s for rebuild.

**What if.** What if refresh became invisible: no work for no change, proportional work for real change, and identical state regardless of how it was reached?

### F5 — State surfaces exist but do not yet form ambient working memory

**Symptom.** `memory_context` could add, list, query, and isolate a memory by a disjoint scope. After adding the same kind of memory to the default graph-local store, `query_context` with the matching scope reported `memories: 0` and did not include the decision.

**Evidence.** Same graph, exact memory text, exact related nodes, matching scope, and a no-memory comparison.

**Floor.** A scoped memory that exactly matches a task and exact nodes should appear automatically in the working packet once and only in its allowed scope.

**Gap.** Standalone storage pass; end-to-end retrieval miss.

**What if.** What if the relevant decisions from the last turn were already present before the next question finished being asked?

### F6 — Temporal and recent-change answers can be confidently ahistorical

**Symptom.** The fixture's first commit was at 12:17:18. `graph_at_time` at 12:17:00 returned the same 42 nodes and 50 edges as 12:18:00. A `recent_changes` query returned README hierarchy only, no commit or fixes evidence, and was marked answerable.

**Evidence.** Git commit timestamp, before/after temporal calls, and complete query receipt.

**Floor.** Before the first recorded state, return no historical graph or an explicit unsupported-state response. A recent-change answer requires change evidence.

**Gap.** Zero temporal delta across the graph's creation boundary; false answerable recent-change packet.

**What if.** What if asking “what changed?” always meant the actual change, never text that merely contained the word “history”?

### F7 — Federation works as storage and exact search, not yet as compound task coverage

**Symptom.** A Flask + fixture federation validated at 5,912 nodes and 16,594 edges. Exact search found both `fixture::root` and `flask::full_dispatch_request`. A natural query explicitly asked to compare both, but anchors and packet evidence came only from Flask; the response was labeled answerable at confidence 0.8133.

**Evidence.** Federated build receipt, exact searches, and natural query packet.

**Floor.** Every named repository/task facet must be represented or explicitly missing before a cross-repository answer is complete.

**Gap.** 1/2 named projects represented in the natural packet.

**What if.** What if repository boundaries disappeared for retrieval without disappearing from provenance?

### F8 — Architecture and compound implementation requests remain coverage-blind

**Symptom.** A Flask architecture prompt named eight dimensions. The answer's evidence points covered only application context/factory documentation and had no dimension-by-dimension facet receipt. It was partial because two documents were truncated, not because most requested subsystems were unrepresented. A response-processing implementation prompt routed to affected tests and produced large sets centered on template and CLI helpers rather than the requested lifecycle.

**Evidence.** Auto-routing, evidence-point, facet, and affected-test receipts.

**Floor.** A broad task should decompose into explicit required facets and cannot be answerable until each is covered or declared missing.

**Gap.** Architecture coverage was not measured; compound routing changed the task rather than completing it.

**What if.** What if one sentence reliably expanded into the exact research, change-point, dependency, and test questions needed to finish the work?

### F9 — Test selection is excellent in its strong stratum and absent in weak ones

**Symptom.** The Locus acceptance board emitted focused Rust commands with coverage paths, and all 10 commands across the two P0 cases selected at least one real test. On ripgrep, GraphGraph still produced the focused `cargo test -p ignore walk::tests --lib` command. On C#, it retrieved a direct test method lexically but reported no affected-test evidence and no command.

**Evidence.** Executed Locus board, ripgrep receipt, C# source oracle and packet.

**Floor.** A direct in-repository test invocation should be recognized in every supported language, with an executable project-native command or an explicit environment limitation.

**Gap.** Strong Rust/Locus pass; total C# miss.

**What if.** What if every proposed change arrived with the smallest trustworthy test set, already checked for executability and coverage?

### F10 — Packet compression is strong; proof delivery is not close to the token floor

**Symptom.** Packet proxy tokens were 101 for exact caller, 1,244 for a path, 80 for the negative query, 1,464 for architecture, and 1,760 for affected tests. Full audit-envelope characters divided by packet characters were 25.7x, 3.57x, 21.85x, 2.59x, and 17.19x respectively. The affected-test envelope was 112,204 characters for a 6,528-character packet.

**Evidence.** Same MCP responses, measured without truncation.

**Floor.** Default proof should add at most the information needed to establish freshness, coverage, caveats, and next action—no repeated bulk evidence.

**Gap.** 2.6–25.7x character overhead in this sample.

**What if.** What if trust cost almost nothing, so the smallest response was also the safest response?

### F11 — The internal hot path is near the floor; end-to-end fluidity is not invariant

**Symptom.** Exact relationship telemetry was about 0.4–0.9 ms, and cached exact packet generation was 37–56 ms. A repeated natural exact lookup improved from 1.17 s to 172 ms. Yet the frozen Flask path task took 13.85 s in the evaluator, ripgrep warm-query P95 was 2.49 s, a negative query took 1.28 s, and an affected-test cache hit took 1.58 s. The Locus board reported warm P95 369 ms, close to its 400 ms ceiling.

**Evidence.** Internal timings, client wall time, cache receipts, evaluator strata, and acceptance-board latency gate.

**Inferred.** The graph operation itself is often cheap; task planning, receipt construction, process/transport work, and query-class-specific expansion dominate user-visible latency.

**Floor.** Repeated bounded context calls should feel instantaneous and have a tight tail independent of query class.

**Gap.** Sub-millisecond core versus 0.17–13.85 s end-to-end observations.

**What if.** What if every request felt warm and only genuinely new evidence could make it slower?

### F12 — Capability declaration, rendering, and validation still disagree

**Symptom.** Ten formats were advertised. End-to-end generation and validation passed for `semantic_arrow`, `gg`, `gg_hybrid`, `gg_lex`, `gg_lex_hybrid`, and `doc_summary`. `lowlevel` and `sql` rendered but validation rejected them as unknown. `hybrid` and `svo` failed generation because their generated packets failed validation.

**Evidence.** Same graph, start node, class, and budget across all formats.

**Floor.** Every selectable advertised format must generate and validate through the same public contract.

**Gap.** 6/10, unchanged from the prior critical run.

**What if.** What if a capability could not be advertised until every public path agreed it worked?

## Baseline comparison

| Dimension | GraphGraph | code-review-graph |
| --- | --- | --- |
| Polyglot fixture build | 1.81 s, 43 nodes / 52 edges | 25.82 s, 30 nodes / 48 edges |
| Definition discovery | All important fixture definitions found | All queried root definitions found |
| Initial `Root -> Middle` edges | 0/5 | 5/5 |
| Test-to-root callers | 1/5 | 3/5 correct, plus same-name false associations |
| Exact relation payload | Compact, sub-ms internal traversal, explicit completeness caveat | Correct callee payload on the tested exact roots |
| Natural-language task packets | Far stronger bounded packet and receipt surface | Primarily exact structural queries |

GraphGraph's real advantage remains the combination of natural-language anchoring, compact topology, provenance, freshness, and calibrated receipts. code-review-graph's differential value here is that it established a realistic extraction floor. Neither baseline is universally correct.

## Gates for the next critical run

The single most useful CI scalar is now **minimum direct-call recall across supported-language strata** on the hermetic polyglot fixture. It is cheap, deterministic, and extraction bounds every downstream graph feature. Current minimum: 0. Required gate: 1.0.

Additional hard gates:

1. **Polyglot topology:** 15/15 direct fixture calls, with zero cross-language false associations.
2. **No-op safety:** 100% of unchanged-file refreshes return success, zero effective delta, and no mutation; P95 below 100 ms.
3. **Edit proportionality:** one-file splice P95 below 300 ms and never slower than a clean small-fixture rebuild.
4. **Answerability/topology agreement:** no answerable caller/path result with zero required relationship edges.
5. **Cross-repo facet coverage:** every named project represented or explicitly missing.
6. **Temporal truth:** before-first-state queries return empty/unsupported; recent-change answers contain change evidence.
7. **Ambient memory:** exact scoped memory appears in the next relevant context packet and never leaks to a disjoint scope.
8. **Architecture coverage:** every named dimension represented or explicitly missing.
9. **Language floor:** hand-labeled path/caller recall at least 0.90 per supported language, not merely in aggregate.
10. **Format contract:** 10/10 advertised formats generate and validate end to end.
11. **Build attribution:** at least 90% of wall time assigned to named phases; every phase above 5% visible.
12. **Latency:** exact cached P95 below 50 ms, warm natural P95 below 300 ms, no unexplained request above 1 s.
13. **Receipt cost:** default proof no more than 15% of packet size or 100 proxy tokens, whichever is larger.
14. **Release freshness:** no green release board when its target graph is extractor-incompatible or stale.

## What if GraphGraph reached the practical limit?

What if asking once was enough—no mode choice, no symbol hunt, no retry instinct, no need to wonder whether the graph was fresh?

What if GraphGraph understood the whole job behind a sentence: what must be known, what must change, what might break, what proves the change, and what still is not known?

What if every answer arrived as the smallest complete working set, with nothing missing and nothing present merely because it shared a word?

What if equivalent questions always preserved the essential evidence, while extra context appeared only when it helped?

What if every supported language and repository boundary felt equally reliable, and every gap became an explicit boundary instead of a plausible substitute?

What if current decisions, recent discoveries, failed attempts, and verified facts stayed quietly available across turns, already scoped to the task that needed them?

What if research flowed directly into implementation context, implementation flowed directly into the smallest credible verification set, and successful verification flowed directly into the next grounded step?

What if unchanged work cost nothing, small changes cost almost nothing, and total repository size stopped affecting the feeling of momentum?

What if historical questions always returned the world as it actually was, and cross-repository questions felt like one continuous context without losing where anything came from?

What if the system knew the difference between “I found a nearby fact” and “I have enough evidence to act,” and that distinction was never negotiable?

What if proof was so small and automatic that speed, confidence, and transparency stopped competing?

At that limit, GraphGraph would stop feeling like a tool an agent invokes. Context would simply be present: know, act, verify, continue.

## What is already near the floor

Protect these strengths:

- Exact in-graph relationship traversal is extremely cheap and unusually honest about completeness.
- Compact `gg` packets are deterministic on repeat and budget-monotone in the tested Flask case.
- The cache produces byte-identical packets and materially improves repeat latency.
- Fresh current builds validated across Python, JavaScript, Rust, and C# without frontend fallbacks, parse errors, grammar errors, or timeouts.
- Real edit and delete splices converged exactly to clean rebuilds on the controlled fixture.
- Negative retrieval can abstain explicitly with low confidence and no invented test command.
- Locus-focused affected-test selection produced real commands, coverage receipts, and 10/10 commands that selected tests.
- Federation preserves namespaces and exact search provenance.
- The intended Locus acceptance board can go red and, with execution enabled, can reach a real 13/13 green.

## Coverage ledger

Tested:

- Doctor/status, frontend, ontology, traversal, format, cache, and acceptance telemetry
- Instrument red controls and invalid packets
- Fresh builds on Python, JavaScript, Rust/history, C#, and a five-language hermetic fixture
- Frozen direct/reverse/path/doc/negative retrieval tasks
- Exact search, relationships, full graph, packet rendering, and snippets/locations
- Determinism, budget monotonicity, critical paraphrase invariance, and cache equivalence
- No-op update, real edit, deletion, and full-rebuild equivalence
- Architecture, blast/affected-tests, repair, and advanced compilation
- Memory add/query/list/scope plus context injection
- Historical views and recent-change retrieval
- Two-project federation and compound query coverage
- All 10 advertised packet formats
- code-review-graph differential extraction baseline
- Locus acceptance board with focused test execution

Not tested and therefore not passed:

- Runtime trace ingestion accuracy
- Long-running watch mode and concurrent writers
- Hook lifecycle behavior
- Semantic service backed by real embeddings; doctor reported offline hash fallback with no paraphrase recall
- Real autonomous edit quality on an external software-engineering benchmark
- C/C++, Java, TypeScript/TSX, Ruby, PHP, Kotlin, Scala, and Swift direct-oracle topology
- Multi-day memory retention and supersession behavior
- Very large graphs beyond the 14,550-node saved Locus graph

## Artifacts and side effects

Persistent report:

- `docs/findings/2026-07-31-critical-graybox-universal-limit.md`

Reproducibility fixture:

- `C:\Users\dcarn\aiprojects\graphgraph-graybox-fixture-20260731`
- The fixture intentionally remains dirty relative to its initial commit: `python/flow.py` was edited and `javascript/flow.test.js` was deleted for splice tests.
- GraphGraph and code-review-graph artifacts exist under the fixture's `.graphgraph` and `.code-review-graph` directories.

Temporary evidence:

- `C:\tmp\gg-critical-20260731` contains fresh foreign-repo graphs, manifests, before/after copies, memory data, and the federation registry/graph.
- Locus focused test execution used existing Cargo build output under `locus/target`.
- No source file in Flask, Express, ripgrep, UniGetUI, Locus, or GraphGraph was edited.

## Final decision

Use GraphGraph today for compact structural orientation, exact known-ID relationships, freshness-aware packets, Locus/Rust-focused affected-test guidance, and a first research packet that an agent verifies before acting.

Do not yet delegate without supervision when success depends on complete cross-language call topology, automatic compound-task decomposition, architecture completeness, C#/JavaScript caller coverage, no-op-safe refresh, ambient memory, historical truth, or cross-repository completeness.

The hard and valuable substrate is present. The remaining work is not “more graph.” It is closing every path by which correct evidence can be missing, ignored, mislabeled complete, or delivered too late to feel ambient.
