# Agent cycle efficiency and quality tracker

**Opened:** 2026-08-02  
**Status:** active  
**Scope:** GraphGraph retrieval speed, token use, language precision,
completeness, accuracy, deployment freshness, and agent-facing integration  
**Method:** gray-box execution, hand-oracled evaluation tasks, real tokenizer
counts, and GraphGraph's own receipts

This document turns the 2026-08-02 audit into a trackable improvement program.
It deliberately distinguishes three states that must not be conflated:

1. **Implemented:** code and focused tests exist.
2. **Validated:** the change passes an independent fixture or metamorphic gate.
3. **Active:** the graph, skill contract, and resident service actually used by
   an agent contain the validated change.

A workstream is complete only when all three states are satisfied, unless its
exit gate explicitly says otherwise.

## How to update this tracker

- Assign one owner before moving a workstream to `active`.
- Add dated evidence to the run ledger; do not overwrite the baseline.
- Record cold CLI, warm in-process, and resident MCP timings separately.
- Use real `o200k_base` or `cl100k_base` counts for token gates. Keep proxy
  counts as a separate column.
- Rebuild with `--no-incremental` before comparing extractor or resolver
  coverage. Incremental scans carry full-scan telemetry forward.
- Do not call a negative task a pass merely because its expected-node recall is
  zero. It must also abstain with the required confidence and packet size.
- Do not mark an active-state task complete using a graph stored under a
  different filename; verify the graph discovered by the normal agent path.

Status values: `todo`, `active`, `blocked`, `revalidate`, `done`.

## Baseline snapshot

The repositories were at the exact commits pinned by their hand-authored
evaluation tasks:

| Fixture | Language | Commit | Active graph |
| --- | --- | --- | --- |
| GraphGraph | Python | working tree with concurrent agent edits | 13,383 nodes / 49,343 edges; 4 relevant paths stale at final snapshot |
| Flask | Python | `954f5684e4841aad84a8eec7ace7b81a0d3f6831` | 1,632 nodes / 4,141 edges |
| Express | JavaScript | `18e5985b8a9d5e8423db0a9121f22bdaecd5b120` | 3,439 nodes / 5,546 edges |
| ripgrep | Rust | `227381db0ee83dfa4341f1e27ff9617c0f5ad992` | 4,866 nodes / 14,493 edges |

Important active-state discrepancy: the corrected Express investigation
reported a 3,486-node / 12,139-edge graph and 87.09% receiver evidence, but the
normally discovered Express graph remained the older 3,439-node / 5,546-edge
build with 2.76% strict internal member-call resolution.

### Quality baseline

| Measure | Baseline |
| --- | ---: |
| Positive tasks with full expected-node recall | 12 / 15 |
| Named/direct positive tasks with full recall | 12 / 12 |
| Conceptual, lexically disjoint tasks with full recall | 0 / 3 |
| External negative controls that fully abstained | 1 / 3 |
| Flask median positive-task packet | 124 proxy tokens |
| Express median positive-task packet | 343.5 proxy tokens |
| ripgrep median positive-task packet | 567.5 proxy tokens |
| Broad GraphGraph compact JSON | 3,783 real `o200k_base` tokens |
| Evidence packet inside that response | 1,727 real `o200k_base` tokens |
| Nonsense GraphGraph compact JSON | 3,303 real `o200k_base` tokens |
| Exact cold CLI query | approximately 433-435 ms |
| Broad cold CLI query | approximately 0.9 s median; later observations 2.9-3.9 s |

### Active topology and semantic coverage

Strict internal member-call rate is
`resolved / (resolved + ambiguous + unknown_receiver + unmatched)`.

| Fixture | Strict member-call rate | Concept-link coverage | Health note |
| --- | ---: | ---: | --- |
| GraphGraph | 24.7% | 33.78% | mixed topology trust; full-scan counters carried forward |
| Flask | 62.40% | 23.15% | fresh full scan; 67.00% receiver evidence |
| Express active graph | 71.58% | 0.83% | fresh corrected full scan; 87.09% receiver evidence |
| ripgrep | 29.48% | 8.64% | fresh full scan; 34.67% receiver evidence; five ambiguous calls |

## Workstream scorecard

| ID | Workstream | Owner | Status | Baseline | Exit gate |
| --- | --- | --- | --- | --- | --- |
| AC-01 | Resident agent transport | Codex | active | Codex session used cold CLI; MCP bundle configured but not exposed | Normal Codex session exposes `graphgraph/query`; resident exact-query p95 meets gate |
| AC-02 | Active graph publication and freshness | Codex | active | Self graph stale; Express corrected build not active; clean external repos report stale with zero delta | Normal discovery selects validated build; zero-delta status is fresh and recommends no refresh |
| AC-03 | Conceptual intent retrieval | Codex | active | 0/3 conceptual tasks achieved recall | At least 80% full recall on calibration plus held-out conceptual tasks; no direct-task regression |
| AC-04 | Abstention and confidence calibration | Codex | active | 1/3 external red controls abstained; arbitrary self nonsense returned 3,303 tokens | Every red task is unanswerable, confidence <= 0.2, zero nodes, and <= 50 real tokens |
| AC-05 | Cross-language call topology | Codex | active | Active Python 62.40%, JS 71.58%, Rust 29.48% strict rates; receiver evidence 67.00%, 87.09%, and 34.67% | Per-language volume gates pass with independently checked precision >= 98% |
| AC-06 | Machine-response token surface | unassigned | todo | Evidence was 45.7% of a 3,783-token broad JSON response | Ordinary response <= 1.15x evidence-packet tokens; diagnostics remain opt-in and complete |
| AC-07 | Token estimator calibration | Codex | done | Two broad packets were undercounted by about 12-13% | Mean absolute error <= 5%, p95 <= 10%, no format-ranking inversions on held-out packets |
| AC-08 | Latency and scale invariance | unassigned | todo | Exact cold CLI about 435 ms; broad path variable; ripgrep eval wall time 12.1 s | Transport-specific absolute and invariance gates pass |
| AC-09 | Contract and telemetry consistency | unassigned | todo | Global Codex skill stale; answerability labels contradicted oracle outcomes | Capability/contract identity is machine-readable; co-reported state and metrics are internally consistent |
| AC-10 | Rotating held-out repository panel | Codex | active | Flask, Express, and ripgrep only | Repeatable small panel covers at least five language/runtime strata without one monolithic run |

## AC-01 — Resident agent transport

Outcome: agents should use a long-lived process for the normal cycle and pay
cold process startup only for explicit CLI use.

- [ ] Confirm `graphgraph/query` and `graphgraph/query_context` are exposed in a
  fresh Codex session.
- [ ] Record server execution, queue, serialization, transport, and client wall
  time separately.
- [ ] Prove that `query` routes an exact caller/callee question to the relation
  micro-IR without ranked retrieval.
- [ ] Prevent individual agents from launching competing refresh cycles against
  the same project graph.
- [ ] Repair or reinstall the stale global Codex skill contract.
- [ ] Verify active state after restarting the client, not only installer
  output.

Gates:

- Resident exact-query server p95 <= 25 ms.
- Resident exact-query end-to-end p95 <= 60 ms.
- Auto-routed exact query <= 1.10x direct relation-query latency.
- Cold CLI latency remains reported but does not gate resident performance.

## AC-02 — Active graph publication and freshness

Outcome: the graph discovered by an agent must be the graph whose quality was
validated.

- [x] Publish or rebuild the corrected Express graph at the normal active path.
- [ ] Include extractor identity, source revision, graph fingerprint, and
  semantic-sidecar fingerprint in the status/query receipt.
- [x] Make zero changed and zero deleted paths resolve to `fresh`, not `stale`.
- [x] Verify no-op sync performs no graph write.
- [ ] Define one coordinator/owner for graph refresh during multi-agent edits.
- [ ] Verify exact changed/deleted path splices before allowing absence or count
  claims.
- [ ] Add an active-vs-validated graph mismatch check to `doctor` or startup.

Gates:

- Express normal discovery reports the validated node/edge shape or a newer
  independently validated fingerprint.
- `status` on an unchanged pinned repository reports fresh and recommends no
  mutation.
- Query receipts expose the same active graph identity as validation receipts.

## AC-03 — Conceptual intent retrieval

Outcome: semantically equivalent questions should reach the same structural
terminals even when the query shares no important identifier with them.

- [x] Preserve the three current failing conceptual tasks as calibration cases.
- [x] Add an opt-in hard promotion gate for the 12 external named positives,
  three lexical-disjoint conceptual tasks, and three external negatives.
- [x] Add paraphrases without reusing symbol names from the answer key.
- [ ] Add held-out conceptual tasks after policy tuning; never tune against the
  held-out set.
- [ ] Report anchor-set overlap and normalized core-node Jaccard for paraphrases.
- [x] Distinguish missing semantic evidence from a confidently answerable
  packet.
- [x] Verify direct/named-symbol recall remains 100% on the existing 12 tasks.

Latest structural-only run (working tree, existing active graphs):

| Task | Returned | Expected | State |
| --- | ---: | ---: | --- |
| Flask inbound transaction lifecycle | all expected facets | 5 nodes | 1.0 node recall and 1.0 facet completeness; answerable at 0.20 confidence |
| Express factory-to-router modules | both expected modules | 2 paths | 1.0 recall; unsupported role projection capped at 0.20 confidence |
| ripgrep input-to-matcher-to-traversal path | all five expected obligations | 5 nodes | 1.0 recall/completeness; incomplete at 0.15 because no directed connector is proved |

The GraphGraph training panel now also has full recall on all three
lexically-disjoint conceptual tasks. The ambiguous `Where is status
implemented?` task includes `cmd_status`, the exact reverse lookup remains at
1.0 recall, and the plausible Kubernetes/gRPC negative returns zero nodes,
zero edges, zero packet tokens, and confidence 0.0. This is training evidence,
not a held-out generalization claim.

The bounded software-role rewrite is a calibration bridge, not the general
retriever. Primary retrieval work on
[SPLADE v2](https://arxiv.org/abs/2109.10086),
[ColBERTv2](https://arxiv.org/abs/2112.01488), and
[light hybrid retrievers](https://aclanthology.org/2023.acl-short.139/)
supports a hybrid sparse+dense candidate stage: learned sparse expansion
preserves inverted-index behavior, while dense or late-interaction evidence
improves lexical-disjoint recall and out-of-domain robustness. GraphGraph must
then use typed topology and facet coverage as its precision/abstention layer,
not treat embedding similarity as proof.

Gates:

- Calibration conceptual full-recall rate >= 80%.
- Held-out conceptual full-recall rate >= 70% initially.
- Same-intent normalized core-node Jaccard >= 0.70.
- No conceptual miss may be labeled answerable above 0.2 confidence.

## AC-04 — Abstention and confidence calibration

Outcome: the system should spend almost nothing when the repository cannot
answer the question.

- [x] Keep one explicit red task per fixture.
- [x] Add random nonsense, plausible out-of-domain, and near-miss negatives.
- [x] Require answerability state, confidence, node count, and token count to
  agree.
- [ ] Track Brier score and expected calibration error by query class.
- [x] Test negatives with and without semantic sidecars.
- [x] Ensure an unresolved expected symbol fails measurement rather than being
  excluded as an unscored success.

Gates:

- Negative task status is `unanswerable`.
- Answerability confidence <= 0.2.
- Returned nodes and edges = 0.
- Total real-token response <= 50.
- False-answerable rate = 0 on the committed red panel.

## AC-05 — Cross-language call topology

Outcome: caller, callee, blast-radius, affected-test, and dead-code questions
must have measurable language-specific completeness.

- [x] Rebuild every comparison fixture with `--no-incremental`.
- [ ] Publish strict rate, receiver-evidence ratio, unknown receiver shapes,
  ambiguity count, and independent precision separately.
- [x] Re-run the corrected Express build through normal active discovery.
- [x] Add hand-labelled positive and adversarial receiver oracles for Python,
  JavaScript/TypeScript, and Rust.
- [x] Add at least one held-out Java or C# fixture and one C or C++ fixture.
- [ ] Preserve explicit abstention where source evidence cannot recover dynamic
  framework behavior safely.

Initial gates:

- Python strict member-call rate >= 0.65.
- Rust strict member-call rate >= 0.34.
- JavaScript strict member-call rate >= 0.50, then raise toward 0.80.
- Independently labelled trusted-edge precision >= 0.98 for every language.
- Express golden request path fits in <= 12 nodes and <= 250 proxy tokens.

## AC-06 — Machine-response token surface

Outcome: default machine output should contain the evidence and the minimum
receipt needed to use it safely; detailed diagnostics should be requested only
when needed.

Observed broad response composition:

| Field | Real tokens |
| --- | ---: |
| Evidence packet | 1,727 |
| Retrieval receipt | 662 |
| Actionable structure | 570 |
| Anchors | 523 |
| Workflow | 140 |
| Remaining fields and JSON structure | approximately 161 |
| Total | 3,783 |

- [ ] Define a minimal response tier: evidence packet, compact control receipt,
  metrics required for safe use, and required next action.
- [ ] Keep anchors, detailed retrieval decomposition, workflow, and expanded
  actionable data behind an explicit diagnostic tier.
- [ ] Detect duplicated node/path/signature information across envelope fields.
- [ ] Preserve full receipts for validation and debugging.
- [ ] Measure total tool-response tokens, not only packet proxy tokens.
- [ ] Recheck packet-format minimums with the exact active tokenizer.

Gates:

- Successful ordinary response <= 1.15x evidence-packet real tokens.
- Exact relation response remains <= 250 real tokens for the current
  three-neighbor fixture.
- Diagnostic mode remains semantically complete and packet-valid.

## AC-07 — Token estimator calibration

Outcome: budgeting and format selection should agree with real model tokenizers
closely enough that rankings and hard limits do not change.

- [x] Re-run the calibration corpus after renderer or envelope changes.
- [x] Score `o200k_base` and `cl100k_base` independently.
- [x] Include broad packets, identifier-heavy packets, negative responses, and
  pretty JSON as separate strata.
- [x] Fail when the proxy chooses a different minimum valid format than a real
  tokenizer.
- [x] Round once after additive token-unit accumulation.

The enforceable calibration run covers 108 rendered packet/tokenizer pairs
(nine formats, six sizes, and two tokenizers). The shipped estimator records
2.73% mean absolute error, 5.93% p95 absolute error, 7.61% maximum error, a
6.68-point cross-format mean-error spread, and zero minimum-format inversions
across 12 tokenizer/size comparisons. Per tokenizer, `o200k_base` records
3.01% MAE and 6.40% p95; `cl100k_base` records 2.45% MAE and 5.53% p95.

Separate diagnostic strata preserve distinctions the packet fit must not hide:
compact negative JSON is underestimated by 8%, a real identifier-heavy `gg`
packet is overestimated by 4.80% (`o200k_base`) and 6.34% (`cl100k_base`), and
pretty negative JSON is underestimated by 41.03%. Pretty machine envelopes
therefore require real-token measurement under AC-06 rather than silently
extending a compact-packet proxy beyond its calibration domain. The existing
`token_units` contract accumulates an unrounded additive cost and
`estimate_tokens` rounds once at the boundary.

Gates:

- Mean absolute error <= 5%.
- p95 absolute error <= 10%.
- Cross-format error spread <= 10 percentage points.
- Zero minimum-format ranking inversions on the held-out packet set.

## AC-08 — Latency and scale invariance

Outcome: cost should track the requested delta and query difficulty, not total
repository size or process startup.

- [ ] Maintain separate cold CLI, warm in-process, and resident MCP dashboards.
- [ ] Report p50, p95, and maximum over controlled repeated runs.
- [ ] Separate graph load, row/index construction, anchoring, expansion,
  selection, rendering, and transport.
- [ ] Compare the same query class across small and large fixtures.
- [ ] Preserve the current one-file versus five-file delta invariance.
- [ ] Eliminate refresh work when the source delta is empty.
- [ ] Record machine load and concurrent-test interference with every timing
  run.

Gates:

- Resident relation-query p95 <= 60 ms end-to-end.
- One-file incremental update p95 <= 300 ms.
- Large/small fixture relation-latency ratio <= 1.2.
- Large/small fixture one-file update ratio <= 1.2.
- Five-file/one-file update ratio <= 1.3.
- Broad ranked-query p95 has an explicit budget per graph-size stratum.

## AC-09 — Contract and telemetry consistency

Outcome: agents should be able to trust that instructions, capabilities,
metrics, and active state describe the same implementation.

- [ ] Negotiate a machine-readable protocol/skill contract version at MCP
  initialization.
- [ ] Include active graph and extractor identity in every response.
- [ ] Reject impossible combinations such as high answerability with zero
  oracle recall on a calibrated task.
- [ ] Preserve the committed red metric control and require it to appear in
  failing-task summaries.
- [ ] Add invariants for summary counts versus detail arrays.
- [ ] Report `implemented`, `validated`, and `active` status separately in
  release/doctor output.

Gates:

- No stale skill contract in a release-validation client.
- No internal metric contradictions in the acceptance suite.
- Active graph identity matches the graph used for its published quality
  receipt.

## AC-10 — Rotating held-out repository panel

Outcome: test a small, useful cross-section every cycle without scanning every
repository at once.

Current panel:

| Slot | Repository | Stratum | Role |
| --- | --- | --- | --- |
| 1 | Flask | Python framework | calibration and abstention |
| 2 | Express | dynamic JavaScript framework | value-flow and affected tests |
| 3 | ripgrep | Rust workspace | qualified members, docs, multi-hop paths |

Candidate next rotation:

| Candidate | Stratum | Why |
| --- | --- | --- |
| crewAI | large Python application | scale and member-resolution invariance |
| Redis | C systems project | tree-sitter shared path and C call extraction |
| Neo4j | Java multi-module project | typed member calls and workspace scale |
| UniGetUI | C# application | properties, fields, and application topology |
| mathlib4 | Lean project | unsupported/partial-language honesty and docs |

- [x] Freeze commit and hand-authored answer keys before measuring a new slot.
- [x] Use at most three primary repositories per routine cycle.
- [ ] Rotate one repository at a time so regressions remain localizable.
- [x] Keep calibration and held-out task sets separate.
- [x] Record scan completeness, exclusions, and frontend identity with results.

First untouched rotation (task files committed at `f0e99f9` before any graph
execution):

| Fixture | Scan profile and shape | Conceptual | Named | Negative |
| --- | --- | ---: | ---: | ---: |
| Redis (`138263a`) | C, tree-sitter, full non-incremental, no docs/history; 1,088 files, 7,407 nodes, 25,597 edges; 15.5 s | 0/1 | 3/4 full recall | pass |
| UniGetUI (`5b05b35`) | C#, tree-sitter, full non-incremental, no docs/history; 1,091 files, 5,921 nodes, 16,150 edges; 9.8 s | 0/1 | 3/4 full recall | pass |
| Neo4j (`8f4aa6a`) | Java/Scala, tree-sitter, full non-incremental, no docs/history; 12,978 files, 153,522 nodes, 521,602 edges; 223.9 s | 0/1 | 4/4 full recall | pass |

Aggregate first-run gate: conceptual full recall `0/3`, named full recall
`10/12`, and negative fail-closed `3/3`. The conceptual packets were labeled
answerable at confidence 0.2185-0.2342 despite zero recall, just above the 0.20
safety ceiling. Redis's pointer-return definition `struct redisCommand
*lookupCommand(...)` did not exist in the extracted graph, making both tasks
that require it explicit extractor-coverage failures rather than retrieval-only
misses. UniGetUI's failed named task resolves the source expectations but lacks
the required member-call evidence. The 217.2 s three-project evaluation wall
time also confirms that large-graph ranked evaluation must remain outside the
interactive resident-query path.

This panel is now frozen test evidence. Do not add aliases or tune thresholds
against these three conceptual questions. Diagnose general failures with
separate synthetic/calibration fixtures and use a future rotation for the next
unseen generalization claim.

## Do-not-regress gates

These capabilities were already strong and should remain hard constraints:

- [x] Structural validation passes for every active graph.
- [ ] Independent full builds produce zero structural delta.
- [ ] Exact query output is byte-identical across repeated unchanged runs.
- [ ] Raising a node budget never removes prior results.
- [x] No-op update performs no write.
- [ ] Ambiguous symbols return candidates and a retry action rather than a
  silent guess.
- [ ] Truncation, partial topology, stale telemetry, and unresolved receivers
  remain explicit.
- [x] The evaluator's nonexistent-symbol red task reports zero recall.
- [x] Direct/named-symbol full recall remains 12/12 or better on the current
  panel.

## Recommended execution order

1. **Activate the validated system:** AC-01, AC-02, and AC-09.
2. **Repair unsafe answers:** AC-04, then AC-03.
3. **Raise structural completeness:** AC-05.
4. **Collapse recurring cost:** AC-06, AC-07, and AC-08.
5. **Prove generality without a giant run:** AC-10.

## Run ledger

Append one row per controlled run. Link a saved JSON/Markdown artifact when
available.

| Date | Run ID | Graph/code identity | Fixture(s) | Transport | Result summary | Evidence | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-08-02 | BASELINE-01 | GraphGraph working tree; active saved graphs listed above | GraphGraph, Flask, Express, ripgrep | cold CLI and in-process evaluator | 12/15 positive full recall; 0/3 conceptual; 1/3 external red controls abstained; exact CLI about 435 ms | This document and linked reports below | Codex audit |
| 2026-08-02 | GATES-01 | working tree | committed retrieval-v1 panel | evaluator unit contract | Added `--enforce-agent-cycle-gates`; verifies exact task counts, conceptual aggregate/project floors, named full recall, and fail-closed negative state/nodes/edges/tokens; focused tests and Ruff pass | `agent_cycle_gate_report`; `tests/test_eval_protocol.py` | Codex |
| 2026-08-02 | RETRIEVAL-02 | working tree; existing active saved graphs; `source-mode=off` | Flask calibration, Express and ripgrep test | cold CLI evaluator | Flask conceptual improved from 0 to 1.0 recall/completeness; Express and ripgrep conceptual remain 0; all three external red controls now unanswerable at 0 confidence with zero evidence; focused 54-test suite and Ruff pass | `retrieval/facets.py`; `retrieval/context.py`; `tests/test_retrieval_section_relevance.py` | Codex |
| 2026-08-02 | GRAPHS-03 | extractor `1adc483474cf`; active full-scan artifacts | Flask, Express, ripgrep | no-incremental scan + active discovery | All three active graphs are byte-identical to validated candidates, structurally valid, source-clean, and extractor-compatible. Express is 3,486 nodes/12,139 edges with 87.09% receiver evidence (1,315 resolved, 195 unknown); clean sync reports zero delta and performs no write (hash and mtime unchanged). Old artifacts are recoverable from `C:\tmp\*-active-before-20260802.gg`. | active `status --json`; frozen eval panels; 164 receiver/frontend tests plus cross-language adversarial oracle pass | Codex |
| 2026-08-02 | RETRIEVAL-04 | working tree; fresh active external graphs; `source-mode=off` | Flask, Express, ripgrep | manifest-backed evaluator | Hard external gate passes: conceptual full-recall rate 3/3, named positives 12/12, negatives 3/3 fail closed with zero evidence. Role facets retain bounded candidate groups, use minimum directed typed connectors when provable, balance roots when topology is partial, and cap unsupported/disconnected confidence at 0.20. | `agent_cycle_gate_report`; 81 focused tests; Ruff | Codex |
| 2026-08-02 | SEMANTIC-05 | FastEmbed 0.8 / BGE-small v4 sidecar; working-tree role guard | Flask | explicit `source-mode=all` plus structural negative controls | Raw dense candidates preferred database prose for the lifecycle paraphrase. Constraining semantic seeds to proposal evidence preserved the graph-backed role terminals; the conceptual task returned to 1.0 recall while random, plausible OOD, and near-miss negatives remained zero-evidence abstentions with and without semantic seeds. | active Flask `.graphgraph/semantic.json`; `tests/test_retrieval_section_relevance.py` | Codex |
| 2026-08-02 | SELF-06 | working tree; active GraphGraph graph | GraphGraph train panel and active external panel | in-process evaluator, `source-mode=off` | GraphGraph train panel: conceptual 3/3 full recall, exact/ambiguous positives 2/2 full recall, red control zero nodes/edges/tokens at confidence 0. External hard gate revalidated after the shared fix: conceptual 3/3, named 12/12, negatives 3/3. Saturated facet reservation now replaces weak prose rather than appending then truncating; one qualified witness must supply both evidence type and label quality; projected labels are ranked against their compiled role rather than raw prose. | `retrieval/anchors.py`; `retrieval/context.py`; `retrieval/facets.py`; focused 53-test suite and Ruff | Codex |
| 2026-08-02 | HELDOUT-07 | task freeze `f0e99f9`; isolated `C:\tmp\heldout-*-20260802.gg` | Redis C, UniGetUI C#, Neo4j Java/Scala | full non-incremental tree-sitter scans; in-process evaluator; `source-mode=off` | First untouched run fails promotion: conceptual 0/3, named 10/12, negatives 3/3. All conceptual misses were incorrectly answerable just above 0.20. Redis exposed a pointer-return C definition extraction gap; UniGetUI exposed missing member-call evidence. Full builds passed structural validation; Neo4j scan 223.9 s and total evaluation wall 217.2 s. | `eval/heldout-2026-08-02/`; isolated graph receipts in `C:\tmp` | Codex |
| 2026-08-02 | C-FRONTEND-08 | working tree after held-out baseline; no held-out rerun | synthetic C pointer-return fixture | tree-sitter frontend unit and full frontend/grammar suites | Reproduced the extractor defect independently: `struct redisCommand *lookupCommand(...)` was mislabeled `redisCommand` because generic descent visited the return type before the declarator. Following the grammar's explicit `declarator` field restores `lookupCommand` without a C-specific symbol table. Targeted red/green test, full frontend/grammar suite, and Ruff pass. The frozen Redis result remains the published untouched baseline. | `scanner/frontends/syntax.py`; `tests/test_scanner_frontends.py` | Codex |
| 2026-08-02 | TOKENS-09 | shipped estimator constants `1.2593` / `0.1626`; active GraphGraph packet corpus | nine packet formats at six sizes; `o200k_base` and `cl100k_base`; negative and identifier-heavy diagnostics | in-process renderer plus real tokenizer counts | Enforced gate passes on 108 packet/tokenizer pairs: MAE 2.73%, p95 5.93%, max 7.61%, cross-format spread 6.68 points, and 0/12 minimum-format inversions. Compact negative error is -8%; real identifier-heavy packet errors are +4.80%/+6.34%. Pretty JSON is explicitly out of calibration and measured separately at -41.03%. Ruff passes. | `benchmarks/context_graph/calibrate_token_proxy.py --enforce`; `packets/metrics.py` | Codex |
| YYYY-MM-DD | RUN-___ |  |  |  |  |  |  |

## Decision log

| Date | Decision | Reason | Revisit condition |
| --- | --- | --- | --- |
| 2026-08-02 | Separate implemented, validated, and active states | The corrected Express graph existed but was not the graph normal discovery consumed | Revisit only if release tooling makes the states transactionally identical |
| 2026-08-02 | Use a rotating three-repository panel | It provides language stratification without an expensive all-repository sweep | Expand only when routine cycle cost remains inside its budget |
| 2026-08-02 | Treat full JSON amplification separately from packet efficiency | The evidence packet was less than half of the broad machine response | Revisit after a tiered response contract ships |
| 2026-08-02 | Make audit thresholds executable, not report-only | The frozen suite already exposed weak strata but returned success regardless of threshold failure | Revisit when the suite version or task counts intentionally change |
| 2026-08-02 | Keep calibrated role rewrites bounded and make hybrid retrieval the general conceptual path | Hand aliases can close known lexical gaps but cannot establish cross-domain generality; learned sparse/dense candidates have stronger empirical support, while graph constraints can preserve GraphGraph's precision | Revisit after a resident, transaction-coupled semantic index is benchmarked on a newly frozen held-out repository |
| 2026-08-02 | Treat the current Express/ripgrep conceptual tasks as seen regression evidence after this run | Their answer keys were inspected while implementing role projections, so their green result proves the mechanism and prevents regression but no longer proves unseen-domain generalization | Replace the held-out claim with AC-10 repositories frozen before their first measurement |
| 2026-08-02 | Retain the shipped token-proxy coefficients despite least-squares coefficient drift | Prediction gates pass comfortably on both supported tokenizers and every rendered format; coefficient movement alone is not evidence that changing a coupled fit improves held-out prediction | Refit only when an independently frozen corpus fails MAE, p95, cross-format, or ranking gates |

## Evidence and companion reports

- [Retrieval and shared-path optimization](2026-08-01-retrieval-and-shared-path-optimization.md)
- [Express theoretical ceiling and post-fix verification](2026-08-01-graybox-express-theoretical-ceiling.md)
- [Flask and multi-language gray-box analysis](2026-08-01-graybox-flask-multilang.md)
- [Token proxy recalibration](2026-07-30-token-proxy-recalibration.md)
- [Caching and compression prototypes](2026-07-31-caching-and-compression-prototypes.md)
- [Confirmed bugs and Express follow-up checklist](BUGS.md)
- [`eval/retrieval-v1/flask.json`](../../eval/retrieval-v1/flask.json)
- [`eval/retrieval-v1/express.json`](../../eval/retrieval-v1/express.json)
- [`eval/retrieval-v1/ripgrep.json`](../../eval/retrieval-v1/ripgrep.json)
