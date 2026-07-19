# GraphGraph 10/10 and 11/10 acceptance specification

Status: Proposed
Date: 2026-07-19
Baseline: GraphGraph 0.1.0 against Locus
Companion evidence:
[`2026-07-19-locus-black-box-usage-report.md`](2026-07-19-locus-black-box-usage-report.md)

## Purpose

This document turns the observed Locus failures into a black-box release
standard for making GraphGraph:

- **10/10:** reliably correct, complete when it claims completeness, small,
  fast, reproducible, and safe for implementation workflows within its declared
  support envelope.
- **11/10:** all 10/10 guarantees plus adaptive packet minimality,
  self-diagnosed evidence gaps, calibrated uncertainty, and proof-carrying
  verification receipts.

This is an acceptance specification, not an implementation design. It evaluates
GraphGraph only through documented CLI/MCP behavior, emitted graphs, packets,
receipts, source-grounded checks, and test-command results.

## Non-negotiable scoring rule

A high average must not hide an unsafe dimension.

Report both:

```text
composite_average = arithmetic mean of dimension scores
release_floor     = minimum release-blocking dimension score
```

The release grade is controlled by `release_floor`.

- **Straight 10:** every release-blocking dimension satisfies its 10/10 gates;
  no open P0 or P1 correctness defect; composite average is at least 10.0.
- **Proverbial 11:** every 10/10 gate remains satisfied and every 11/10 stretch
  gate passes on unseen evaluation tasks.
- A 10.8 average with one 7.0 dimension is **not** a 10/10 release.
- Unsupported capabilities must be declared and must abstain cleanly. They
  cannot be counted as passing.

## Black-box evidence contract

Every acceptance run must obey these rules:

1. Do not inspect GraphGraph source code to derive expected behavior.
2. Audit repository exclusions before building.
3. Produce the GraphGraph packet before opening sealed expected-answer data.
4. Never inject expected node IDs, fixture answers, or golden paths as retrieval
   seeds unless the task explicitly supplies those paths or symbols.
5. Establish ground truth after retrieval from repository source, documentation,
   manifests, focused test listing, and requested command output.
6. Treat GraphGraph output as orientation evidence until verified.
7. Save the tool version, repository snapshot, graph/manifest identity, command,
   packet, receipt, token counts, timing state, and verification result.
8. Distinguish graph correctness, retrieval correctness, packet validity,
   command validity, and test outcome. One passing layer cannot substitute for
   another.
9. Re-run correctness suites from clean graphs and incremental graphs.
10. Do not silently relax a threshold after seeing results. Threshold changes
    require a versioned spec revision and rationale.

## Declared support envelope

GraphGraph must publish support tiers for every advertised language/frontend.

### Tier A — Full structural support

Tier A means all applicable gates in this specification:

- definitions, imports, calls, type references, containment, and documentation;
- direct/reverse lookup, paths, blast radius, and affected tests;
- manifest-derived focused test commands;
- exact incremental create/edit/delete/rename refresh.

### Tier B — Bounded structural support

Tier B may omit explicitly named relation types, but must:

- declare the omissions in `frontends`, `doctor`, build receipts, and queries;
- never present a missing relation as complete;
- abstain or return a capability warning for unsupported query classes;
- meet all safety, validation, freshness, token, and transport-parity gates.

### Tier C — File/document orientation only

Tier C may provide file/document retrieval but cannot claim symbol-level
answerability, blast radius, or affected-test completeness.

No frontend may appear “supported” without an explicit tier and tested
capability matrix.

## Evaluation corpus

A release candidate must pass all four layers.

### Layer 1 — Deterministic micro-fixtures

Create small, independently readable fixtures for every Tier A language:

- local and cross-module free-function calls;
- qualified cross-package calls;
- overloaded and same-named members;
- traits/interfaces, implementations, inheritance, and dynamic dispatch;
- type aliases, generic parameters, fields, variants, constructors, and pattern
  matches;
- direct, indirect, unit, integration, and generated test-target layouts;
- nested documentation headings, repeated headings, enumerations, and prose
  facts;
- ignored directories, symlinks/junctions, build outputs, and secret canaries;
- parse errors, unsupported syntax, macros/metaprogramming, and malformed files.

Expected relationships are sealed until retrieval completes.

### Layer 2 — Locus real-world suite

Locus is the primary dense Rust workspace and documentation corpus. The
canonical cases later in this document are permanent regression tests.

### Layer 3 — External projects

For each Tier A frontend, test at least:

- two independent public repositories;
- one small repository and one repository with at least 10,000 graph nodes;
- multiple test-layout styles where the ecosystem supports them.

At least one overall corpus must exceed 100,000 graph nodes. Repositories used
for final release scoring must not all be used for budget tuning.

### Layer 4 — Mutation and adversarial suite

Run on disposable repository copies:

- single-file edit;
- multi-file edit;
- new file;
- deleted file;
- renamed/moved file;
- changed ignore rule;
- dirty worktree already matching graph hashes;
- stale graph with unrelated changes;
- corrupt/incompatible graph;
- duplicate symbols and ambiguous queries;
- hard node budgets below the complete answer size;
- zero-match and intentionally negative queries.

## Task matrix

Every supported query class must have at least 25 scored tasks across the full
corpus, with at least five real-repository tasks.

| Query class | Required ground truth |
| --- | --- |
| `direct_lookup` | exact definition, signature, path, line, owning scope |
| `reverse_lookup` | complete direct reverse adjacency and omitted count |
| `subsystem_summary` | entry points, owned files/symbols, major dependencies |
| `blast_radius` | direct and ranked transitive dependents with relation reasons |
| `multi_hop_path` | valid paths, endpoints, intermediate relations |
| `affected_tests` | direct/transitive tests, `covers`, executable commands |
| `doc_summary` | grounded sections/paragraphs and complete requested enumeration |
| `negative_query` | correct absence or bounded abstention |
| `recent_changes` | qualifying changes and affected structural context |

Compound tasks must also score per-facet fulfillment and merged path/test intent.

## Machine-readable benchmark task

Each benchmark task should have a versioned record equivalent to:

```yaml
id: GG-LC-003
repo_snapshot: <immutable identity>
query: "What does LocusEngine::parse_to_ir call?"
expected_query_class: direct_lookup
scope: []
ground_truth:
  required_nodes: []
  required_relations: []
  acceptable_alternatives: []
  relevant_tests: []
  doc_facts: []
assertions:
  must_be_complete: true
  max_irrelevant_node_ratio: 0.10
  max_packet_tokens: 500
  answerability: answerable
  selected_test_count_min: null
timing:
  cache_state: cold_and_warm
```

`ground_truth` remains sealed until the packet has been produced. The harness
may use it for scoring, never for anchoring, planning, retrieval, or packet
construction.

## Scorecard dimensions

### D1 — Installation, discovery, and transport availability

#### 10/10 gates

- `doctor` accurately reports CLI, MCP, frontend, credential, graph, and project
  registration state.
- A documented project installation command produces a working registration
  for Codex, Claude Code, Cursor, and Gemini on their supported platforms.
- A fresh supported workspace can reach a validated first query without manual
  config editing.
- Missing integration produces one actionable repair command, not a generic
  failure.
- Windows, macOS, and Linux acceptance fixtures pass.
- Project and user registrations are distinguished without ambiguity.

#### 11/10 gates

- The client detects and safely repairs stale registrations, version skew, and
  moved executables with an explicit receipt.
- Transport selection is automatic and explains why MCP or CLI was selected.
- A portable project profile reproduces equivalent behavior across clients.

### D2 — Scan safety, exclusions, and privacy

#### 10/10 gates

- Root and nested `.gitignore`/`.ignore` rules are honored before descent.
- Explicit exclusions and built-in exclusions are individually reported with
  reasons.
- Generated outputs, caches, dependencies, graph artifacts, VCS data, and
  declared secret-bearing files are not indexed.
- Secret-canary contents never appear in graph nodes, packets, logs, receipts,
  caches, or errors.
- Symlinks/junctions cannot escape the intended repository boundary.
- Tests, fixtures, migrations, and docs are retained unless intentionally
  excluded.
- Every truncation, fallback, failure, skipped file, and pruned directory is
  machine-readable.
- Repeated scans with identical inputs produce the same logical graph.

#### 11/10 gates

- A preflight audit proposes unusually large, generated, copied, or sensitive
  paths with explanations before scanning.
- The build emits a machine-checkable exclusion proof showing why each path was
  included or excluded.
- Resource budgets prevent malicious or accidental corpus explosions without
  losing unreported evidence.

### D3 — Frontend extraction correctness

#### 10/10 gates

For every Tier A frontend:

- Definition extraction precision is at least 99.5%; recall at least 99%.
- Import/reference edge precision is at least 99%; recall at least 98%.
- Statically resolvable call-edge precision is at least 99%; recall at least
  98%.
- Type-reference precision is at least 99%; recall at least 98%.
- Qualified cross-module/package free-function calls meet the same threshold.
- Ambiguous or dynamic calls are labeled rather than assigned a confident wrong
  target.
- Parse fallback, timeout, unsupported syntax, and parse failure are separate
  categories.
- Node IDs remain stable across unchanged rebuilds.

Thresholds are computed over independently ground-truthed relationships, not
only relationships GraphGraph chose to emit.

#### 11/10 gates

- Dynamic/ambiguous call candidates carry calibrated probabilities or bounded
  candidate sets with at least 99% candidate recall.
- Previously unseen syntax degrades to explicit partial evidence without
  corrupting neighboring extraction.
- Cross-language edges through manifests, FFI, generated bindings, or declared
  adapters are represented with provenance.

### D4 — Graph integrity and ontology fidelity

#### 10/10 gates

- Structural validation passes for every accepted graph.
- No dangling edge endpoints, duplicate logical nodes, invalid path escapes, or
  impossible containment cycles.
- Graph serialization/ingestion round trips preserve all logical nodes, edges,
  provenance, and manifest identity.
- Every relation has documented direction, semantics, and traversal policy.
- Advanced evidence, memory, time, federation, traces, and repair inputs are
  projected into normal GraphGraph nodes/edges rather than hidden parallel
  stores.
- Profile, scan, status, and validation report consistent node/edge and
  unresolved-edge counts.

#### 11/10 gates

- Each graph ships a compact integrity certificate tied to its manifest hash.
- Structural changes between snapshots can be explained as source-grounded
  additions, removals, or relation changes.
- Ontology/version migrations are lossless or explicitly enumerate lost
  capabilities before conversion.

### D5 — Routing, anchoring, and scope inference

#### 10/10 gates

- Query-class routing accuracy is at least 99% on the scored matrix.
- Exact qualified identifiers resolve to the intended symbol as the top anchor
  at least 99.5% of the time.
- Same-named members require or infer type qualification without silent
  conflation.
- Explicit strict scopes never leak nodes; expand scopes cross only supported
  structural boundaries.
- Unambiguous crate/package/path terms infer scope in at least 95% of eligible
  tasks.
- Historical audit docs and test-name matches cannot outrank exact production
  entry points without a structural reason.
- Every anchor has a machine-readable relevance reason.

#### 11/10 gates

- GraphGraph asks one minimal clarification when genuine ambiguity would
  materially change the packet.
- It learns/calibrates routing and scope policies from evaluation outcomes
  without using task answer keys during retrieval.
- It provides a counterfactual receipt showing how alternate scopes or query
  classes would change coverage and cost.

### D6 — Exact, direct, and reverse retrieval

#### 10/10 gates

- Direct definition precision and recall are each at least 99.5%.
- Exhaustive direct/reverse relationship queries return 100% of known eligible
  graph neighbors or explicitly report every omitted neighbor count.
- Returned relationship precision is at least 99%.
- If a hard budget prevents completeness, status is `incomplete`, never
  `answerable`.
- Irrelevant-node ratio is at most 10% at p95.
- Exact queries do not spend budget on unrelated siblings merely because they
  share a containing file/type.

#### 11/10 gates

- The packet includes the smallest complete eligible relationship slice or a
  certificate that no smaller valid packet exists under the output ontology.
- Each included node states the query facet and relation that justified it.
- Each excluded frontier class states its count and exclusion reason.

### D7 — Multi-hop paths, subsystem summaries, and blast radius

#### 10/10 gates

- Returned paths contain valid source-grounded edges end to end.
- At least one shortest or equivalently minimal valid path is returned when one
  exists.
- Multi-hop path recall is at least 97%; edge precision at least 99%.
- Subsystem summaries include verified entry points, primary owned symbols,
  imports/dependencies, and boundary crossings.
- Blast-radius output separates direct, transitive, type/reference, test, doc,
  and configuration impact.
- Broad packets satisfy every claimed facet or abstain on the missing facets.
- No packet is `answerable` based only on lexical/document matches when the task
  asks for structural code evidence.

#### 11/10 gates

- Paths are ranked by structural strength and implementation relevance, not
  only hop count.
- Blast radius includes a calibrated confidence and “why affected” proof for
  every recommendation.
- The packet can optimize jointly for completeness, minimal tokens, and
  verification cost.

### D8 — Affected tests and executable commands

#### 10/10 gates

- Direct contract-test recall is at least 98%.
- Top-five affected-test precision is at least 90%; top-ten recall at least 95%.
- Type definitions, variants, constructors, pattern matches, imports, calls,
  test helpers, and manifest target layout all contribute evidence.
- Every recommendation has a non-empty `covers` receipt containing a real path
  from the changed symbol/file to the test.
- Generated commands select the intended package, target, module, and/or test.
- **100% of recommended focused commands select at least one test.**
- A process exit code of zero with zero selected tests is a failed
  recommendation.
- The receipt distinguishes command validity, selected count, passed count,
  failed count, ignored count, compile failure, test failure, timeout, and
  infrastructure failure.
- Broad suites are ranked below focused direct tests unless no focused evidence
  exists.

#### 11/10 gates

- GraphGraph produces the minimum-cost test set that covers all selected change
  points under the available graph evidence.
- It can execute or ingest sandboxed focused-test results and return a
  proof-carrying selection receipt.
- It detects flaky or historically unreliable tests and proposes a bounded
  fallback without hiding uncertainty.

### D9 — Documentation grounding and enumeration

#### 10/10 gates

- Every factual document claim maps to a section/paragraph span.
- Grounded-document precision is at least 99%; requested-fact recall at least
  98%.
- Enumerative questions within an explicit document/section return 100% of
  matching sibling items or report exact omitted items/count.
- Repeated headings, nested sections, tables, code blocks, and long paragraphs
  preserve correct hierarchy.
- Heading-only matches cannot satisfy a prose fact.
- Truncated documents and zero grounded nodes force narrowing or abstention.
- Plain, JSON, and MCP validation agree on document node/edge counts and status.

#### 11/10 gates

- The packet derives the smallest complete hierarchical document slice,
  preserving enough parent context to interpret every fact.
- It detects contradictory or temporally superseded sections and surfaces both
  with provenance.
- Documentation and source relationships are ranked by verified explanatory
  value, not raw lexical overlap.

### D10 — Completeness, truncation, abstention, and calibration

#### 10/10 gates

- False `answerable` rate is zero for exhaustive deterministic tasks.
- Every node/edge/source/document truncation has an explicit flag, reason,
  original count when knowable, selected count, and omitted count.
- Facet coverage separates lexical evidence, structural evidence, document
  grounding, and test evidence.
- A missing requested structural facet forces `incomplete`.
- Negative queries distinguish verified absence, unsupported extraction,
  out-of-scope evidence, and budget-limited absence.
- Answerability decisions are identical across CLI, JSON, and MCP.
- Confidence calibration error is at most 5 percentage points on probabilistic
  tasks.

#### 11/10 gates

- Every packet carries a machine-checkable completeness proof relative to the
  graph, scope, query policy, and budget.
- Graph-relative completeness and source-relative uncertainty are explicitly
  separated.
- GraphGraph proposes the smallest next action that can resolve an evidence gap:
  refresh, widen scope, increase budget, request qualification, retrieve source,
  or run a test.

### D11 — Token efficiency and packet minimality

#### 10/10 gates

Token counts measure packet content only, using both `cl100k_base` and
`o200k_base`; the worse value controls the gate.

| Task | p95 token ceiling |
| --- | ---: |
| Exact definition | 250 |
| Complete direct/reverse lookup | 500 |
| Negative query | 200 |
| Focused affected-tests slice | 900 |
| Scoped document answer | 900 |
| Multi-hop path | 1,200 |
| Subsystem summary | 1,500 |
| Blast radius | 1,500 |

Additional gates:

- Token ceilings apply only to packets that meet correctness/completeness gates.
- Receipts, provenance detail, and source snippets are independently optional
  and never silently inflate the compact packet.
- At p95, at least 90% of packet nodes contribute to a requested facet,
  necessary parent context, or a connecting path.
- Raising a node budget does not add unrelated nodes after the complete answer
  is available.

#### 11/10 gates

- Packet size is within 10% of a post-hoc oracle minimum on deterministic tasks.
- GraphGraph chooses the budget automatically and provides a minimality
  certificate.
- The same complete packet is at least 25% smaller at p95 than the 10/10
  ceiling without reducing source-grounded recall.

### D12 — Latency, caching, and scale

#### 10/10 gates

On the 11,000-node Locus graph and reference Windows machine:

| Operation | p95 ceiling |
| --- | ---: |
| Warm exact query | 500 ms |
| Cold exact query | 1,500 ms |
| Warm complex query | 1,500 ms |
| Cold complex query | 3,000 ms |
| One-file incremental splice | 500 ms |
| Full audited Locus scan | 20 s |

Additional gates:

- Every query receipt declares cache hit/miss, cache identity, and phase timings.
- Latency samples include at least 10 cold and 30 warm runs.
- No blocking phase lacks a timing.
- Exact-query latency remains below one second p95 on a 100,000-node graph after
  warmup.
- Memory/disk growth is bounded and reported by graph scale.
- Cache invalidation never serves stale logical results.

#### 11/10 gates

- Warm exact p95 is at most 150 ms and warm complex p95 at most 750 ms on Locus.
- Performance scales with touched evidence rather than total graph size for
  exact and incremental operations.
- GraphGraph predicts query cost before expansion and adapts the plan without
  crossing the requested latency/token envelope.

### D13 — Freshness and the edit loop

#### 10/10 gates

- Exact changed paths update only those paths and required dependent metadata.
- Deleted paths are removed without ghost nodes/edges.
- Renames preserve identity when supported or clearly report remove+add.
- `sync git` reconciles edited, created, deleted, renamed, and newly ignored
  paths.
- Dirty does not mean stale when graph hashes already match.
- Unrelated dirty paths do not make a correctly scoped packet stale.
- Refresh receipts list requested, updated, removed, unrelated, and remaining
  stale paths.
- Query results after an incremental update equal a clean rebuild's logical
  result.
- Cost of an exact splice scales with touched files rather than repository size.

#### 11/10 gates

- The packet explains the structural delta caused by the edit before providing
  implementation context.
- Rename/move lineage is preserved across historical and federated views.
- GraphGraph automatically selects exact splice versus broader reconciliation
  from verifiable filesystem state.

### D14 — Validation and cross-transport parity

#### 10/10 gates

- Graph validation, packet validation, and packet/receipt semantic validation
  are distinct and consistently named.
- CLI plain, CLI JSON, MCP, and saved-packet validation return identical logical
  status, node count, edge count, scope, truncation, and answerability.
- Format-specific renderers round-trip without losing logical evidence.
- A malformed packet fails closed with actionable errors.
- Validation never reports zero nodes for a populated recognized packet.
- A semantic receipt cannot pass when its rendered packet fails structural
  validation unless the distinction is explicitly justified and named.

#### 11/10 gates

- A transport-independent packet digest proves logical equivalence across
  renderings.
- Clients can independently verify packet and completeness certificates.
- Version skew produces a compatibility explanation and safe downgrade path.

### D15 — Observability and reproducibility

#### 10/10 gates

Every build/query receipt includes:

- GraphGraph version and frontend versions;
- repository root identity and manifest/graph hash;
- declared support tier;
- ignore/exclusion identity;
- query text, inferred query class, scope, plan, budgets, and anchor reasons;
- cache state and phase timings;
- graph freshness;
- selected and omitted counts;
- packet format, node/edge counts, token counts, and validation;
- test commands, `covers`, and execution-selection counts when available.

The same version, graph, query, and settings produce the same logical packet.
Nondeterministic ranking ties are stable or explicitly seeded.

#### 11/10 gates

- A single portable evidence bundle can replay and verify the entire operation.
- Receipts identify the first phase responsible for a regression in extraction,
  ranking, selection, packing, validation, or command generation.
- A structural diff explains why two packet versions differ.

### D16 — Security, robustness, and failure containment

#### 10/10 gates

- Scanning never executes repository code.
- Malformed source, binary files, huge lines, cyclic links, invalid encodings,
  and corrupt graphs cannot crash the service or escape resource limits.
- Paths are canonicalized and remain inside authorized roots.
- Packet rendering escapes untrusted content safely for each transport.
- Timeouts and caps produce partial receipts rather than fabricated
  completeness.
- Cache and graph files cannot overwrite arbitrary paths through repository
  content.
- Fuzz/property suites cover parsers, graph ingestion, packet formats, and
  path handling.

#### 11/10 gates

- Every external or untrusted evidence source carries a trust label propagated
  into packets.
- GraphGraph can run in a least-privilege read-only mode with externally managed
  graph output.
- Adversarial benchmark results ship with the release evidence bundle.

### D17 — Implementation trust and agent usability

#### 10/10 gates

- Change points identify exact source paths/lines and why each matters.
- Source snippets are bounded and available on demand for every claimed
  implementation relationship.
- Missing evidence is surfaced before an implementation-ready status.
- A “ready to implement” receipt requires:
  - fresh scoped graph;
  - satisfied structural facets;
  - no hidden truncation;
  - source-grounded change points;
  - at least one valid focused test when tests exist;
  - packet and receipt validation.
- The receipt never claims a test passed unless the emitted command was executed
  and selected at least one intended test.
- Instructions remain usable by an agent without reading GraphGraph source.

#### 11/10 gates

- GraphGraph returns a proof-carrying context packet: every change point, path,
  test, and document fact is connected to source-grounded evidence.
- It identifies the cheapest verification plan that can convert an incomplete
  packet into an implementation-ready one.
- It performs an explicit pre-implementation audit and post-edit refresh/test
  audit while keeping source and executed tests as ground truth.

## Canonical Locus regression cases

These cases are permanent. Their expected data must remain sealed until each
packet is produced.

### GG10-LC-001 — Focused Rust unit-test selection

Query: `What calls normalize_rust and which tests cover it?`

10/10:

- Finds `rust_logical_ops_lower_to_bitwise_at_binary_positions`.
- Command selects at least that test.
- Command may use its exact label or the real `normalize_tests` module.
- A zero-selected exit code cannot pass.
- Receipt records selected/passed/failed counts.

11/10:

- Selects the minimum direct test set for the requested change surface.

### GG10-LC-002 — Core `Expr` affected tests

Query: `If Expr changes, which production code and tests are affected?`

10/10:

- Returns bounded ranked tests with type/reference evidence.
- Includes direct construction/match/reference coverage.
- Does not claim all 69 lexical-reference files are necessarily affected.
- Does not return zero test evidence while verified candidates exist.

11/10:

- Produces a minimum-cost test set covering the selected `Expr` change facets.

### GG10-LC-003 — Qualified cross-crate calls

Query: `What does LocusEngine::parse_to_ir call?`

10/10:

- Returns both `locus_frontends::formula::parse` and
  `locus_engine::lift::lift_expr`.
- Excludes unrelated `LocusEngine` siblings and historical audit prose.
- Reports complete only when both resolvable outgoing calls are present.
- Complete packet is at most 500 tokens.

11/10:

- Packet contains only the method, required callees/types, and connecting
  relations, with a minimality certificate.

### GG10-LC-004 — Budget-truncated reverse lookup

Query: `What directly calls normalize_rust?`

10/10:

- With an 8-node budget, reports incomplete and four omitted direct callers for
  the baseline graph.
- With sufficient budget, returns all eight verified direct callers.
- Does not spend caller budget on unrelated siblings.

11/10:

- Automatically chooses the smallest complete budget and proves no caller was
  dropped.

### GG10-LC-005 — Complete document stage enumeration

Query:
`According to docs/core-architecture/backbone-pipeline.md, what stages form the Locus pipeline?`

10/10:

- Returns stages 1 through 8, or explicitly reports each omitted stage.
- Every stage is grounded to its heading/span.
- Plain, JSON, and MCP validators agree on populated node/edge counts.
- Complete packet is at most 900 tokens.

11/10:

- Returns the minimal complete hierarchical slice with one shared parent
  context and no redundant prose.

### GG10-LC-006 — Natural-language architecture flow

Query:
`How does expression parsing flow from locus frontends into the engine expression representation?`

10/10:

- Distinguishes formula parsing/lifting from source-language extraction instead
  of conflating them.
- Infers relevant Locus crate scopes or explains remaining ambiguity.
- Prioritizes production entry points and calls over lexical test/audit matches.
- Separately reports structural and documentation evidence.
- Complete packet is at most 1,200 tokens.

11/10:

- Detects the two plausible flows and either returns two minimal facets or asks
  one targeted clarification.

### GG10-LC-007 — Exact incremental edit

On a disposable Locus copy, edit one `normalize_rust` body line and query its
callers/tests with `changed_paths`.

10/10:

- Only the changed file and required metadata are spliced.
- Packet equals a clean rebuild logically.
- Freshness receipt is exact.
- Incremental operation finishes within 500 ms p95.

11/10:

- Receipt explains the structural delta and automatically reuses the minimal
  caller/test packet.

### GG10-LC-008 — Delete and rename

On a disposable copy, rename one source file and delete one fixture file.

10/10:

- Old paths have no ghost nodes.
- New path contains the expected definitions/relations.
- Delete/rename receipts are exact.
- Incremental result equals a clean rebuild.

### GG10-LC-009 — Same-named member qualification

Choose two real same-named Locus members.

10/10:

- `Type::method` resolves exactly.
- Unqualified ambiguity is declared or clarified.
- No call/type edges are silently mixed between owners.

### GG10-LC-010 — Ignore and secret boundary

Add a disposable ignored directory and secret canary.

10/10:

- Directory is pruned before descent.
- Canary never appears in any artifact or output.
- Exclusion receipt identifies the controlling rule.

### GG10-LC-011 — Transport parity

Run the same fixed queries through CLI plain, CLI JSON, and MCP.

10/10:

- Logical nodes, edges, status, scope, truncation, and validation agree.
- Differences are presentation-only and documented.

### GG10-LC-012 — Cache and latency receipt

Run the same exact and complex queries cold and warm.

10/10:

- Cache state is explicit.
- p95 thresholds are met.
- Warm results are logically identical to cold results.
- Refresh invalidates only affected entries.

## Delivery phases

### Phase 0 — Build the acceptance harness

Deliver:

- versioned task schema;
- sealed ground-truth store;
- black-box runner for CLI and MCP;
- packet parser and logical-normalization layer;
- `cl100k`/`o200k` token counters;
- cold/warm latency runner;
- test-selection/result parser;
- source/doc ground-truth adapters;
- Markdown and JSON scoreboards.

Exit:

- Current GraphGraph baseline can be reproduced from one command without
  expected-answer leakage.

### Phase 1 — Close the trust-boundary defects

Fix and lock:

- GG10-LC-001 zero-test false success;
- GG10-LC-002 missing type-driven affected tests;
- command-selection receipts;
- fail-closed implementation-ready status.

Exit:

- No focused test recommendation selects zero tests across the corpus.
- No P0 defect remains.

### Phase 2 — Structural and completeness correctness

Fix and lock:

- GG10-LC-003 qualified calls;
- GG10-LC-004 truncation/omitted counts;
- exact/reverse adjacency completeness;
- frontend support tiers;
- cross-report unresolved-edge consistency.

Exit:

- Extraction and exact/reverse thresholds pass.
- False `answerable` rate is zero on deterministic exhaustive tasks.

### Phase 3 — Documentation, routing, and transport parity

Fix and lock:

- GG10-LC-005 document enumeration/validation;
- GG10-LC-006 scope inference/noise;
- CLI/JSON/MCP logical equivalence;
- doc hierarchy and grounding.

Exit:

- All document and cross-transport gates pass.

### Phase 4 — Token, latency, scale, and edit loop

Fix and lock:

- task-specific token ceilings;
- exact packet relevance ratio;
- cache state/timing receipts;
- cold/warm SLOs;
- create/edit/delete/rename/ignore refresh;
- 100,000-node scale corpus.

Exit:

- All 17 dimensions meet 10/10 gates for three consecutive clean runs.

### Phase 5 — The 11/10 layer

Deliver:

- automatic smallest-complete budget selection;
- packet minimality certificates;
- graph-relative completeness proofs;
- source-relative uncertainty;
- counterfactual scope/budget receipts;
- cheapest verification-plan selection;
- proof-carrying test execution/ingestion;
- self-repairing integrations and version-skew handling.

Exit:

- All 10/10 gates still pass.
- All 11/10 gates pass on an unseen holdout corpus.
- No token/latency improvement reduces correctness, grounding, or safety.

## Required release evidence bundle

Each scored release must publish an artifact bundle containing:

```text
acceptance/
  manifest.json
  environment.json
  support-matrix.json
  graph-build-receipts/
  query-receipts/
  compact-packets/
  validation-results/
  source-ground-truth-results/
  test-selection-results/
  timing-samples/
  token-samples/
  transport-parity/
  mutation-results/
  scoreboard.json
  scoreboard.md
```

The manifest ties every artifact to tool version, repository snapshot, task
version, graph identity, and environment. Sensitive repository contents must
not be copied into the bundle.

## Regression policy

- P0: secret exposure, path escape, fabricated completeness, zero-test false
  success, corrupt graph accepted, or implementation-ready status without its
  required evidence. Release blocked.
- P1: deterministic relationship omission, wrong confident edge, transport
  disagreement, stale packet presented as fresh, or document grounding failure.
  Release blocked.
- P2: token, latency, relevance, observability, or integration regression that
  remains within correctness guarantees. Release requires an explicit waiver
  and expiry.
- Every fixed GG10 case becomes permanent.
- Threshold waivers cannot produce a 10/10 or 11/10 grade.
- Three consecutive passing clean runs are required for 10/10.
- An unseen holdout run is required for 11/10.

## Definition of 10/10 done

GraphGraph is 10/10 only when:

1. Every advertised frontend has an honest support tier.
2. All applicable D1–D17 10/10 gates pass.
3. Every canonical Locus case passes.
4. All query classes meet correctness, completeness, token, and latency SLOs.
5. CLI, JSON, and MCP are logically equivalent.
6. Incremental results equal clean rebuilds.
7. Every focused test command selects at least one intended test.
8. No P0/P1 defect is open.
9. The complete evidence bundle is reproducible.
10. Three consecutive clean acceptance runs pass.

## Definition of 11/10 done

GraphGraph is 11/10 only when:

1. It remains 10/10 with no relaxed threshold.
2. Every applicable D1–D17 11/10 gate passes.
3. It chooses near-minimal complete packets automatically.
4. It proves graph-relative completeness and states source-relative
   uncertainty.
5. It diagnoses missing evidence and proposes the cheapest resolving action.
6. It provides proof-carrying source/test verification receipts.
7. It meets the tighter token and latency targets.
8. It passes an unseen multi-language holdout corpus.
9. Its adaptive behavior never uses expected answers as retrieval evidence.
10. Independent clients can replay and verify the evidence bundle.

The essential difference is:

```text
10/10 = trustworthy, complete, bounded context within a declared envelope
11/10 = self-minimizing, self-diagnosing, proof-carrying trustworthy context
```
