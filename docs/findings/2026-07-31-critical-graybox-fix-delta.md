# Critical gray-box fix delta: GraphGraph

**Date:** 2026-07-31  
**Compared with:** `2026-07-31-critical-graybox-universal-limit.md`  
**Method:** public CLI/MCP behavior, GraphGraph telemetry, hermetic oracles, metamorphic invariants, and packaged acceptance surfaces. GraphGraph implementation source and version history were not inspected.

## Verdict

GraphGraph moved materially forward. The strongest fix is not cosmetic: on the frozen polyglot fixture, exact call-edge recall rose from **1/15 to 15/15** across Python, JavaScript, Rust, C#, and Go. The C# edges that were previously absent are now present, the CLI no-op update contract now succeeds without rewriting the graph, and all **10/10** advertised packet formats generate and validate end to end instead of 6/10.

The result is approximately **7.1/10 today, up from 6.1/10**. It is now credible as a fast exact graph core and a strong repository-orientation aid. It is not yet a universal, thought-free context layer for every graph-tool workflow. The limiting failures have shifted upward: exact evidence exists, but natural affected-test answers still omit it; standalone memory is not consumed by context; temporal views remain current snapshots with timestamps; and federated compound queries still fail to cover every named repository.

The shortest honest summary is:

> GraphGraph can now know substantially more of the graph, but it does not yet reliably carry everything it knows into the answer, across time, memory, repositories, and multi-part intent.

## Live-run qualification

This was a live workspace rather than a frozen revision. The first exact fresh-scan command reached successful extraction and then failed with `NameError: scan_started is not defined`. Later, the identical command and three isolated flag variants all completed successfully. The scanner artifact's modification time was 2026-07-31 17:06:24 UTC, during the evaluation window. Therefore:

- the initial failure is retained as observed evidence;
- it is not treated as a deterministic failure of the final on-disk state;
- the later exact retry is the current-state result;
- a release decision should repeat the board against an immutable revision.

The configured Codex MCP process also predated the fixes, so current-state measurements used fresh CLI processes. MCP was used only where transport behavior was already covered by the acceptance board.

## Measured delta

| Probe | Previous run | Current run | Interpretation |
| --- | ---: | ---: | --- |
| Polyglot direct-oracle call edges | 1/15 | **15/15** | Major extractor correction |
| Same-file `Root -> Middle` edges | 0/5 | **5/5** | Now matches the elementary oracle |
| C# `Root -> Middle` | absent | **present** | Fixed |
| C# `TestRoot -> Root` | absent | **present** | Fixed at exact topology layer |
| Unchanged-file CLI update | 0/4 successful | **1/1 successful** | Fixed in the current CLI path |
| No-op graph hash | command crashed | **byte-identical** | Correct invariant |
| No-op wall time | n/a | **342 ms** | Fast on the tiny fixture |
| Advertised packet formats | 6/10 | **10/10** | Contract now complete |
| Natural C# affected-tests result | no test | **still no test** | Evidence-to-answer gap remains |
| Context memory consumption | 0 memories | **0 memories** | Not fixed |
| Pre-creation temporal snapshot | same as current | **same 42/63 graph** | Not reconstructed, but caveat improved |
| Federated named-project coverage | omitted fixture, answerable | **omitted fixture, incomplete** | Calibration improved; coverage did not |
| Locus cases | 13/13 | **13/13** | Still green at case level |
| Locus release state | ready | **blocked by stale legacy graph** | Freshness gate is now decisive |
| Packaged quality cases | not used as primary evidence | **4/4, recall 1.0** | Useful regression signal |

## Structural evidence

The current exact-retry scan produced a valid graph with **42 nodes and 63 edges**. It contained exactly the 15 known calls:

- Python: 4/4, including `root -> middle`, `root -> bonus`, `middle -> leaf`, and test-to-root.
- JavaScript: 2/2 after the fixture's intentional test deletion.
- Rust: 3/3.
- C#: 3/3, including both the production chain and direct test call.
- Go: 3/3.

The earlier comparison baseline, code-review-graph, had already proven that the five elementary `Root -> Middle` edges were extractable, but took about 14 times longer to build the original fixture. GraphGraph now retains its speed advantage while matching that elementary topology oracle.

One telemetry nuance remains: relation receipts reported `call_topology_status=complete` while `answer_complete=false` because freshness or task-level evidence gates were not all satisfied. That conservatism is safer than asserting completeness, but the reason should be unmistakable to a caller.

## Incremental behavior

The first update against a copied old graph did not accept the copied manifest and promoted a clean repair, finishing in 500 ms with a valid 42-node/63-edge graph. The immediately repeated identical update was a true no-op:

- exit code 0;
- explicit `No changes detected` receipt;
- structural validation passed;
- SHA-256 before and after was identical;
- 342 ms wall time.

This closes the prior 0/4 unchanged-file crash. The packaged Locus acceptance board also passed exact edit-splice and delete/rename equivalence cases, including byte identity with a clean rebuild.

## Where exact knowledge still fails to become usable context

### Affected tests

The fresh graph contains `csharp_Flow_cs__FlowTests__TestRoot -> csharp_Flow_cs__Flow__Root`. Exact relations return it. Yet both a reverse natural query and a focused `affected_tests` query produced no direct or transitive C# tests and returned `incomplete`.

This is now a composition failure, not an extraction failure. It matters because the user's desired workflow is not “manually inspect relations until the evidence is found”; it is “ask once, receive the right context and the next safe action.”

### Memory

A synthetic memory was added under an isolated scope, anchored to the C# and Go `TestRoot` nodes, and retrieved successfully through standalone memory search. A matching context query with the same scope reported `memories: 0` and did not carry the synthetic fact into the answer.

Storage works. Retrieval works. Task integration still does not.

### Time

Materializing a snapshot before repository creation and one after creation produced the same 42 nodes and 63 edges, with zero left-only or right-only edges. The current system now labels this honestly as `partial_current_snapshot` and explains that it is not a reconstructed historical source snapshot. That is a calibration improvement, not temporal recall.

### Federation

The natural Flask-plus-fixture comparison still anchored and returned evidence only from Flask. It now reports `incomplete` instead of `answerable`, which fixes the dangerous overclaim. It still does not satisfy the named-project comparison.

## Formats, validation, and transport

All advertised formats now generated and structurally validated from the same exact start node:

`lowlevel`, `sql`, `hybrid`, `semantic_arrow`, `gg`, `gg_hybrid`, `gg_lex`, `gg_lex_hybrid`, `svo`, and `doc_summary`.

There is one validation footgun. When packet generation failed because the required start node was omitted, the downstream validator received no packet, silently auto-detected GraphGraph's repository graph, and reported structural success. A validation command used in a pipeline should fail closed on empty input instead of validating an unrelated default artifact.

The Locus board's CLI/plain/JSON/MCP transport-parity case passed. Because the long-lived MCP process was older than the current files, that result should be repeated after restarting the configured process before claiming live transport parity for these fixes.

## Speed and token-cost posture

The current core remains fast where the request is exact and the graph is small:

- fresh polyglot scan telemetry: about 186 ms internal total; roughly 1.2 s process-level command time;
- exact relation work: about 1 ms internally;
- repeated natural fixture query: 540 ms cold and 368 ms warm at the process boundary;
- Locus acceptance: cold P95 1,028 ms and warm P95 362 ms, with a 269 ms warm median;
- compact fixture packet: 243 proxy tokens and 788 characters.

The proof envelope is still much larger than the context it protects. The matching detailed JSON response was 12,759 characters, or **16.19 times** the compact packet. The prior run observed ratios from 2.6 to 25.7 times, so this bottleneck remains.

The Locus board passed all 13 active cases but exited nonzero and set `release_blocked=true` because its saved graph was stale, had one changed path (`semantic.json`), and carried a legacy extractor identity. This is appropriate release behavior. A green case count must not erase an invalid environment.

## Updated scorecard

| Category | Previous | Current | Credible ceiling | Current limiter |
| --- | ---: | ---: | ---: | --- |
| Build safety and validation | 7.0 | 8.0 | 9.9 | Live-run transient; empty-input validator can pass the wrong artifact |
| Definition extraction and indexing | 8.5 | 8.5 | 10.0 | Definitions strong; broad docs truncation not rerun |
| Call and dependency topology | 4.0 | **8.5** | 9.9 | 15/15 fixture oracle; broader real-repo recall not re-frozen |
| Exact lookup and packet core | 8.5 | 9.0 | 10.0 | Strong once identity and freshness are established |
| Natural-language retrieval and routing | 6.5 | 6.5 | 9.9 | Exact C# evidence still omitted from task answer |
| Multi-hop paths | 6.0 | 6.0 | 9.8 | Prior Rust and cross-boundary limits not shown fixed |
| Architecture and blast radius | 4.5 | 4.5 | 9.8 | Named facets still lack hard coverage gates |
| Affected tests and commands | 6.5 | 6.8 | 9.9 | Exact C# edge fixed; natural test result still empty |
| Documentation grounding | 6.0 | 6.0 | 9.8 | No evidence that prior named-doc/truncation gaps changed |
| Incremental freshness and equivalence | 5.0 | **8.0** | 10.0 | No-op fixed; broad-repo splice cost not rerun |
| Memory, temporal, federation continuity | 3.5 | 4.0 | 9.8 | Better honesty, still missing task integration |
| Abstention and calibration | 6.0 | **7.5** | 9.8 | C# and federation now incomplete; temporal result clearly caveated |
| Packet and token efficiency | 7.0 | 7.0 | 9.9 | Compact core, 16.19x detailed envelope |
| End-to-end latency and fluidity | 6.0 | 6.5 | 9.9 | Warm near 400 ms; cold and task variance remain perceptible |
| Format and transport contract | 6.5 | **9.5** | 10.0 | 10/10 formats; restart needed for current MCP proof |

Unweighted mean: **7.1/10**. The weakest necessary continuity and task-composition layers still cap universal delegation below the mean.

## Priority floors before a 10/10 claim

1. Every exact relationship that is relevant to the requested task must appear in the natural answer or in an explicit missing-evidence receipt.
2. Affected-test results must consume production-to-test call edges across every advertised language.
3. Memory must participate in ordinary context retrieval, with scope and provenance visible.
4. Historical queries must reconstruct the requested time or refuse; a timestamped current graph is not a historical graph.
5. Federated queries must cover every named project or identify the missing project as a blocking facet.
6. Validation must fail closed when its intended artifact is absent, empty, stale, or from another identity.
7. Release boards must run on fresh, extractor-compatible graphs and a restarted live transport.
8. The detailed proof surface must become proportional to uncertainty instead of routinely dwarfing the usable packet.
9. The frozen Flask, Express, and ripgrep task board should be rebuilt with the current extractor before raising natural-retrieval or multi-hop scores.

## What if there were virtually no bottlenecks?

At GraphGraph's useful limit, the user would never choose between exact lookup, blast radius, affected tests, memory, history, or federation. They would state the work, and GraphGraph would silently assemble the smallest complete context needed for that work.

What if:

- context were already current before the question was asked, so refresh was never a foreground task;
- every named part of a request became a coverage obligation, making quiet omission impossible;
- an exact graph fact automatically flowed into explanations, plans, test selection, and next actions without a second query;
- decisions, discoveries, failed approaches, and unfinished work were recalled at the moment they became relevant, without asking for memory explicitly;
- crossing repository boundaries felt identical to crossing file boundaries, while provenance always remained visible;
- asking about the past produced the actual past, and uncertainty produced refusal rather than a timestamped present;
- the first response arrived below the threshold of human perception, with deeper proof available only when risk or curiosity demanded it;
- the context packet expanded only around uncertainty, so confidence made answers smaller rather than more verbose;
- after each implementation step, the next likely dependencies, tests, risks, and decisions were already waiting;
- GraphGraph learned the user's active objective strongly enough that “continue” meant continue the work, not reconstruct the conversation;
- every answer carried a compact guarantee: all requested facets covered, all material uncertainty named, all provenance retained, and no unsupported completeness claim;
- tool use disappeared from the user's mental model, leaving only research, judgment, implementation, verification, and forward motion.

That is the real 10/10 target: not a larger graph and not more output, but a context system so complete, timely, selective, and self-correcting that obtaining context stops feeling like a separate activity.

## Final disposition

**Promote:** exact polyglot topology, no-op update handling, format coverage, conservative federation/temporal labeling, and the fresh-graph release gate.

**Do not yet promote as universal:** natural affected tests, end-to-end memory, historical reconstruction, federated compound coverage, and fully fluid sub-perceptual context delivery.

**Recommended next critical run:** freeze a revision, restart the MCP process, rebuild Flask/Express/ripgrep plus one C# and one multi-repository fixture with the current extractor, then rerun the same labeled natural, path, affected-test, memory, temporal, federation, token-envelope, and cold/warm boards without changing the oracle.
