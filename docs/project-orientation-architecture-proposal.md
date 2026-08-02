# Project Orientation Engine: Architecture Proposal

Status: candidate architecture derived from the project-navigation research
agenda.  Names, APIs, and data structures are proposals, not current behavior.

## Architectural goal

Produce a correct, grounded working map of an unfamiliar repository quickly,
then refine it for the current task without forcing the agent to repeatedly
search and reread the same code.

```text
workspace state
  -> evidence compiler
  -> multi-layer project graph
  -> grounded project atlas
  -> intent/facet planner
  -> retrieval ensemble
  -> connected evidence optimizer
  -> navigation controller
  -> source-backed packet + stopping receipt
```

The project graph is the evidence substrate.  The project atlas is a derived,
human/agent-scale view.  A task packet is a still smaller view selected for one
question.  Keeping those levels separate avoids treating a retrieval packet as
the whole architecture or an inferred community as source truth.

## 1. Evidence compiler

All evidence enters a versioned normalized IR with provenance and an extractor
identity.  Providers may abstain independently.

### Entity levels

- repository, package/build target, directory, file;
- class/type/module, function/method, field/variable;
- statement or source region when flow precision requires it;
- documentation section and paragraph;
- test target, fixture, executable command, configuration key;
- commit/change episode and optional runtime event;
- inferred concept, subsystem, and role as derived nodes.

### Edge families

| Family | Examples | Trust/completeness requirement |
| --- | --- | --- |
| Declared hierarchy | contains, target membership, package membership | Deterministic and source-grounded |
| Name/type | defines, references, implements, overrides, returns, type-of | Frontend-specific coverage receipt |
| Execution | calls, dispatch candidate, callback registration | Soundness/precision limits explicit |
| Dependence | data, control, read/write, parameter flow | Context and depth bounds explicit |
| Validation | tests, covers, command-to-target | Concrete provenance required |
| Documentation | explains, discusses, section-of | Paragraph/span grounding required |
| Evolution | changed-with, introduced-by, churn | History window and tangled-change caveat |
| Runtime | observed-call, observed-read | Positive observation only; never proof of absence |
| Inferred architecture | belongs-to-subsystem, role, landmark | Derived view with method/version/stability |

The compiler should use demand-driven or bounded interprocedural analysis for
task-sensitive flow rather than eagerly promising a fully sound whole-program
graph across dynamic languages.  IFDS/CFL-reachability and system dependence
graphs provide the formal model; language frontends may implement conservative
subsets with explicit abstention.

## 2. Multi-layer project graph

Represent the repository as layers over shared entity IDs:

```text
L0 physical     files, directories, manifests, generated/excluded status
L1 symbolic     declarations, imports, references, types
L2 behavioral   call, control, data, tests, runtime observations
L3 conceptual   docs, semantic concepts, issue/change vocabulary
L4 architectural declared and inferred subsystems, roles, boundaries
L5 temporal     revisions, change episodes, validity intervals
```

A query selects useful layers; it does not flatten every layer into one set of
untyped edges.  Relation-specific transition probabilities and completeness
receipts survive into retrieval.

Every derived fact carries:

```text
value, provenance, source span, extractor version,
confidence, validity interval, derivation parents, completeness scope
```

This lets an answer distinguish "source declares", "static analysis infers",
"runtime observed", and "documentation claims".

## 3. Grounded project atlas

The atlas is the cold-start orientation product.  It should be cheap to load and
should answer "what is this repository?" before a task-specific search.

### Atlas views

1. **System card:** languages, build tools, packages, entry points, test commands,
   executable artifacts, and excluded/generated regions.
2. **Subsystem map:** named regions, responsibilities, public interfaces, storage,
   and external boundaries.
3. **Landmark map:** high-authority entry points, central interfaces, state owners,
   registries, dispatchers, and test roots.
4. **Golden paths:** bounded source-to-sink paths for startup, request handling,
   persistence, and test execution where evidence exists.
5. **Drift map:** agreements and disagreements among manifests/docs, physical
   hierarchy, and inferred dependency communities.

### Atlas construction

Start with declared structure.  Infer only where declarations are absent or
conflicting:

\[
w_{uv}=w_r\,p_{prov}(u,v)\,p_{complete}(u,v)
+\alpha s_{semantic}(u,v)+\beta s_{cochange}(u,v).
\]

Run a connected community method such as Leiden/CPM on appropriate aggregated
edges, then test stability under small repository changes and resolution
parameters.  Label a community from grounded manifests, documentation headings,
public symbols, and distinctive terms.  If no stable grounded label exists,
show the files and abstain from naming it.

Do not let a community algorithm override an explicit build/package boundary.
Instead, expose the mismatch through a reflexion-model-style view.

## 4. Intent and facet planner

Replace a single query-class winner with a small typed plan:

```text
intent:
  orientation | lookup | relation | path | change-impact | documentation | negative
facets:
  definition, implementation, callers, data-flow, constraints, tests, docs, history
claim strength:
  exploratory | implementation-grade | completeness-required
budgets:
  lines, tokens, latency, tool actions
```

The planner may keep explicit semantic gates.  Uncertain parts—facet presence,
source value, and expected cost—should use calibrated probabilities learned on
frozen tasks.  The plan is inspectable and versioned.

## 5. Retrieval ensemble

### Stage A: candidate generation

Run independent bounded generators:

- exact path/symbol/literal;
- BM25 or learned sparse expansion over identifiers, summaries, docs, and facts;
- optional dense code/text embeddings;
- atlas landmarks and relevant subsystem nodes;
- relation/path seeds from current navigation state;
- history or runtime sources only when the plan assigns them value.

Exact evidence is never down-ranked merely because semantic evidence is absent.
Unavailable optional sources abstain without stalling interactive queries.

### Stage B: rank fusion

Use reciprocal-rank fusion as the no-training baseline.  Compare it with a
calibrated linear model over normalized features:

\[
P(relevant\mid q,v)=\sigma(\theta^T x(q,v)).
\]

Features include exactness, path authority, semantic similarity, relation type,
distance, provenance, freshness, query-facet compatibility, and session novelty.
Fit on training repositories, calibrate separately, and evaluate on held-out
repositories.  A learned model must beat RRF and the current policy by a
predeclared practical margin.

### Stage C: demand-driven structural expansion

From high-confidence anchors, run typed expansions:

- exact one-hop adjacency for direct relations;
- context-sensitive slice for data/control questions;
- bidirectional path search for connection questions;
- reverse influence for change impact;
- test/command attribution for implementation tasks.

Expansion is query-dependent.  Uniform two-hop traversal remains a baseline,
not a universal policy.

## 6. Connected evidence optimizer

Candidates must become an evidence set, not just a ranking.  Define facet
coverage with diminishing returns:

\[
F(S)=\sum_f w_f\min\left(1,\sum_{v\in S}p(v,f)\right)
+\alpha\sum_{v\in S}r_v
-\beta\sum_{u,v\in S}\operatorname{sim}(u,v).
\]

Choose \(S\) subject to:

- token and source-line budgets;
- a latency budget for newly acquired evidence;
- required paths remaining connected;
- mandatory source spans for implementation-grade claims;
- no invalid or stale evidence crossing the claim boundary.

Compare lazy submodular greedy, current tree-knapsack selection, and a
prize-collecting Steiner/maximum-weight connected-subgraph approximation.  The
receipt reports binding constraints, missing facets, and high-value omissions.

## 7. Navigation controller

The controller manages a session-level evidence workspace corresponding to the
human search-relate-collect loop.

### State

- accepted and rejected anchors;
- collected evidence regions and why they matter;
- open facets and competing hypotheses;
- inspected paths and returned-from-navigation points;
- source revision and source/index freshness;
- current risk and cost estimates.

### Actions

- run exact lexical lookup;
- disambiguate a symbol or path;
- expand a typed relation;
- retrieve bounded source around selected regions;
- request a deeper dependence slice;
- inspect a manifest/doc/history source;
- run a focused command or trace;
- answer, answer with caveats, or abstain.

Choose the next action by expected information gain per cost.  Initially this
can be a fitted contextual bandit or supervised cost model over logged actions.
A full reinforcement-learning policy is unnecessary until offline replay shows
that greedy value-of-information decisions leave meaningful utility behind.

The workspace should persist stable task context across calls, reducing repeated
navigation while invalidating evidence whose source revision changed.

## 8. Claim and stopping receipt

Return separate probabilities/statuses rather than one overloaded confidence:

```text
identity_correct
evidence_relevant
facet_complete
topology_complete_for_claim
source_grounded
fresh
packet_not_truncated
```

Claim policy examples:

- "likely caller" may tolerate incomplete topology if provenance is shown;
- "all callers" requires checked freshness, no truncation, and sufficient
  call-resolution coverage for the language slice;
- "no callers" requires an independent source/static-analysis verification
  path when topology is incomplete;
- architecture labels must cite grounded atlas evidence and mark inference;
- affected-test commands require concrete coverage attribution.

Fit risk/coverage by query class and language.  Emit the best next action when
the requested claim is not licensed.

## 9. Proposed interfaces

```text
orient(repo, budget) -> system card + subsystem/landmark atlas + receipt
navigate(query, state?, budgets?) -> evidence packet + updated state + receipt
relations(target, direction, claim_strength?) -> exact micro-IR + actions
source(regions, line_budget) -> bounded excerpts with revision IDs
explain(evidence_id) -> derivation/provenance tree
compare_architecture() -> declared/inferred agreement and drift
```

`navigate` may call the cheap primitives internally, but its receipt must expose
which actions ran and their cost.  `rg` remains an explicit fallback opcode for
literal questions or graph extraction gaps.

## 10. Failure behavior

| Failure | Required behavior |
| --- | --- |
| Missing/stale graph | Return system status and a bounded rebuild/update action |
| Documentation query with no grounded rows | Fail retrieval; do not substitute nearby code nodes |
| Ambiguous symbol | Return candidates and expected disambiguation value |
| Incomplete receiver topology | Qualify relation claims and offer verification |
| Semantic backend cold or absent | Continue lexical/structural path; expose source state |
| Budget truncation | Report omitted required neighbors/facets |
| Atlas instability | Fall back to declared hierarchy or unlabeled regions |
| Store/index disagreement | Refuse completeness claims and repair/rebuild |

## 11. Delivery slices

1. **Orientation benchmark and system card.** No learned policy; ground every
   field and compare against the primitive-agent baseline.
2. **Atlas prototype.** Declared hierarchy plus stable connected communities and
   a drift view; no production routing changes.
3. **Hybrid candidates.** RRF baseline, semantic/sparse optional, exact path
   invariant preserved.
4. **Typed dependence navigation.** Demand-driven slices behind explicit
   capability receipts.
5. **Evidence-set optimization.** Equal-budget selector tournament.
6. **Session controller.** Log actions first, fit value-of-information second.
7. **Calibrated stopping.** Only after enough held-out tasks exist per stratum.
8. **Storage specialization.** Adopt the winning design from the `.gg` proposal
   only if persistence is a measured bottleneck.

## Research lineage

The architecture draws on program slicing and IFDS graph reachability for
precise task-sensitive dependence, code property graphs for a shared semantic
substrate, software reflexion models for architecture drift, information
foraging and developer-navigation studies for session design, coarse-to-fine
graph retrieval for candidate generation, submodular/connected-subgraph
optimization for packet construction, and selective/conformal prediction for
stopping.  The full primary-source list is maintained in
[Project Navigation Research Agenda](project-navigation-research-agenda.md).

