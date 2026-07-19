# Advanced Context Engineering

## Verified Architecture and Research Roadmap

**Status:** implementation-calibrated design

**Last verified:** 2026-07-19

**Scope:** GraphGraph retrieval, graph runtime, evidence, memory, temporal views,
packet construction, and validation

This document separates what GraphGraph does now from what may be worth building
next. It is deliberately conservative: a mechanism is described as implemented
only when the repository contains the data model, execution path, and tests that
exercise it.

The architectural goal is still ambitious. GraphGraph should present a codebase
to an LLM in a form closer to an execution substrate than to a pile of prose:
explicit entities, typed relations, bounded transitions, evidence, receipts, and
clear stopping conditions. “Low level” does not mean literal binary. It means
minimizing the interpretation needed between a model receiving a packet and
acting on the relationships in it.

## 1. Status vocabulary

| Label | Meaning |
|---|---|
| **Implemented** | The data model, runtime behavior, and direct tests exist. |
| **Partial** | A useful subset exists, but the stronger stated contract does not. |
| **Experimental** | The idea is suitable for a measured prototype, not a public guarantee. |
| **Proposed** | Design work only; no compatibility or performance claim is implied. |

This distinction matters because an advanced-context design can otherwise become
a list of attractive names that overstates the runtime. In particular, GraphGraph
does **not** currently provide a CSR query engine, a textual GQL compiler, a
bi-temporal database, copy-on-write memory branches, automatic code rollback, or
Louvain-based packet coarsening.

## 2. The current low-level contract

The useful “instruction-level” representation for an LLM is a deterministic
pipeline:

```text
SYNC
  -> EXTRACT
  -> NORMALIZE TO GRAPH IR
  -> RESOLVE ANCHORS
  -> EXPAND TYPED RELATIONS
  -> SELECT UNDER BUDGET
  -> PACK EVIDENCE + RECEIPTS
  -> VALIDATE COMPLETENESS AND FRESHNESS
```

This is the analogue of a compact instruction stream:

- nodes are operands;
- edge types are operations or gates;
- query class and scope select the execution path;
- budgets bound work;
- provenance and confidence affect transition strength;
- citations and receipts make results auditable;
- validation determines whether the result is safe to act on.

The goal is not to remove reasoning. It is to avoid spending model tokens
reconstructing relationships that the repository can determine mechanically.
Packets should expose caller, callee, containment, test, documentation, and
evidence relationships directly, then state where the graph is incomplete.

## 3. Verified implementation matrix

| Area | Status | Current contract | Not yet implemented |
|---|---|---|---|
| Typed code graph | **Implemented** | Nodes and typed edges with weights, confidence, provenance, metadata, and temporal fields | A columnar/CSR execution layout |
| Provenance-aware traversal | **Implemented** | Expansion and global, personalized, and localized PageRank use one effective edge value | Full provenance-polynomial or semiring lineage evaluation |
| Decision/process traces | **Implemented** | `decision_trace`, `used_input`, and `applied_policy` relations plus runtime pass receipts | A general workflow/approval engine |
| Temporal graph views | **Partial** | `graph_as_of` filters nodes and edge validity intervals; episodes are append-only | Independent valid-time and transaction-time coordinates |
| Scoped memory | **Partial** | Scoped records, lexical retrieval, and graph projection | Copy-on-write branches, merge semantics, conflict resolution |
| Structured query plan | **Implemented** | Natural-language planning and `GraphProgram` select bounded runtime passes | A textual GQL grammar compiled to array operations |
| Hierarchy/community hints | **Partial** | Deterministic weighted label propagation and additive community nodes | Louvain optimization and lossy packet coarsening |
| Binary storage | **Implemented** | GGB3 dictionary-codes and serializes sequential node and edge records | CSR offsets, adjacency arrays, or memory-mapped query execution |
| Verification | **Implemented** | Packet validation, semantic/freshness receipts, acceptance fixtures, and quality gates | Automatic source rollback or transactional repair |

### 3.1 Storage is not the query model

GGB3 is a compact binary serialization format. It dictionary-codes repeated
strings and stores graph records, including confidence, provenance, and temporal
fields. That is useful, but it does not make the live Python graph a compressed
sparse row (CSR) engine. Runtime adjacency remains ordinary Python graph
structures.

CSR should be considered only after profiling proves object traversal or graph
load layout is a dominant cost. A migration would need:

1. stable node indexing and versioning;
2. forward and reverse offset arrays;
3. typed relation and evidence columns;
4. compatibility with temporal filtering;
5. a mutation strategy or immutable snapshot boundary;
6. parity tests against the current graph API;
7. measured end-to-end latency and memory wins.

Without those conditions, “CSR” is a storage label, not an optimization.

## 4. Evidence strength is one formula

All ranking and expansion paths must agree on what makes an edge trustworthy.
GraphGraph’s effective traversal value is:

```text
w_eff(e) =
    edge.weight
  * edge.confidence
  * provenance_confidence(edge.provenance)
  * traversal_strength(edge.type)
```

For a node `u`, a transition to neighbor `v` is normalized over the effective
outgoing values:

```text
P(u -> v) = w_eff(u, v) / sum(w_eff(u, x) for x in neighbors(u))
```

This contract now applies to:

- bounded graph expansion;
- global PageRank;
- personalized PageRank;
- localized personalized PageRank.

The consistency is important. Previously, expansion used the complete formula
while the three PageRank paths omitted edge and provenance confidence. A
low-confidence or ambiguous relationship could therefore rank like a verified
parser relationship. The implementation and regression tests now enforce the
same evidence semantics throughout.

### 4.1 What provenance currently means

Current provenance is operational metadata used in confidence calibration,
receipts, and traversal. It is not yet a provenance semiring. Work on provenance
semirings is relevant because it gives a rigorous way to compose lineage through
relational operations, but adopting that model would require explicit algebra,
path-composition semantics, and query-level lineage tests. Merely multiplying
edge strengths must not be described as semiring implementation.

Any future lineage algebra needs to answer:

- Is alternative evidence additive, max-selected, or retained symbolically?
- Is sequential evidence multiplied, minimum-bounded, or represented as a path?
- How are correlated extractors prevented from double-counting support?
- Which transformations preserve human-readable citations?
- Can a receipt explain the final score without replaying the whole graph?

Until then, `w_eff` is a calibrated traversal formula, not a proof probability.

## 5. Temporal semantics

### 5.1 Current contract

GraphGraph currently supports an as-of view using node timestamps and edge
validity intervals. Conceptually, an edge is visible at time `t` when:

```text
valid_from(e) <= t
and (valid_to(e) is absent or t < valid_to(e))
```

This is useful valid-time behavior. It can answer “which relationships were
modeled as valid at this time?” The append-only episode store separately records
events, but that does not create transaction-time query semantics.

### 5.2 True bi-temporal support is proposed

A bi-temporal contract requires two independent intervals:

```text
valid_from, valid_to        # when the fact is true in the modeled world
recorded_from, recorded_to  # when GraphGraph knew/stored that version
```

Queries then need both coordinates:

```text
view(valid_at=T_valid, known_at=T_recorded)
```

Building this correctly requires:

1. a schema and GGB version migration;
2. unambiguous closed/open interval rules;
3. corrections that preserve earlier recorded history;
4. indexing or pre-filtering appropriate to the query volume;
5. tests for late-arriving facts, corrected facts, deletion, and no-future-leakage;
6. receipts that state both requested temporal coordinates.

Adding another timestamp field without these query and correction semantics would
not qualify as bi-temporal support.

## 6. Memory and branching

Scoped memory is already useful: records can be stored, searched, and projected
into the graph with scope and provenance. It should remain explicit evidence,
not an invisible prompt side channel.

Copy-on-write memory branches are **proposed**, not implemented. They become
worthwhile only if users need to explore competing implementation hypotheses
without polluting durable memory. A minimum credible design includes:

- immutable parent snapshot identifiers;
- branch-local overlay records and tombstones;
- deterministic read precedence;
- explicit `branch`, `diff`, `merge`, and `discard` operations;
- conflict semantics for changed evidence;
- stale-source and freshness behavior;
- audit receipts linking merged records to their branch origin.

Git vocabulary alone is not a design. Branching should be deferred until a real
workflow demonstrates that scoped memory plus ordinary version control is
insufficient.

## 7. Query compilation

GraphGraph already compiles user intent in the practical sense: the planner
classifies a query, resolves anchors and scope, selects traversal behavior, and
the `GraphProgram` runtime executes bounded evidence, inference, and hierarchy
passes.

That structured representation is closer to an LLM-native instruction form than
a new text language because it avoids another parsing layer. A textual GQL is
therefore **not** a priority by default.

If repeated workloads show that the current plan cannot express important
operations, start with a typed internal AST:

```text
Anchor(symbol="normalize_rust")
Reverse(edge_type="calls", depth=1)
Include(kind="test")
Budget(nodes=12, tokens=600)
Require(fresh=True, complete=True)
```

Only add surface syntax after the AST, optimizer rules, error model, and
compatibility tests exist. Compilation to CSR operations should be a separate
optimization justified by profiling; it is not a prerequisite for a deterministic
query plan.

## 8. Hierarchy and semantic locality

GraphGraph’s current hierarchy pass uses deterministic weighted label propagation
and adds community nodes plus containment edges. It provides orientation without
discarding the underlying graph.

That is not Louvain community detection, and it is not packet coarsening.
Louvain is a modularity-optimization method; GraphGraph should not use its name
for a different algorithm.

Semantic locality remains a valid retrieval principle in a narrower form:
evidence near a correctly resolved anchor often has higher task value than
unrelated repository context. Personalized PageRank is a reasonable graph
mechanism for exploiting that locality. Research systems such as HippoRAG also
use graph structure and Personalized PageRank for retrieval, while KAG combines
knowledge-graph structure with logical-form-guided reasoning. These works support
experimentation, not automatic performance claims for GraphGraph.

### 8.1 A safe coarsening experiment

Packet coarsening is **experimental**. It should be an optional compiler pass
after candidate retrieval, never a replacement for extraction or evidence
validation.

Compare at least:

1. no coarsening;
2. current label-propagation hierarchy;
3. Louvain or another modularity method;
4. deterministic file/module hierarchy.

For each candidate, preserve:

- anchor nodes and exact requested symbols;
- shortest evidence paths needed to support an answer;
- citations and provenance;
- test relationships;
- uncertainty and truncation receipts.

Promote a coarsener only if it reduces tokens or latency without lowering
fixture recall, precision, citation coverage, or completeness detection. Generic
prompt-compression results such as LLMLingua are adjacent evidence, not proof
that graph coarsening will help this system.

## 9. Constants, formulas, and learned policies

Replacing every constant with a formula would make the system harder to reason
about and often less correct. The right choice follows the shape of the decision.

Use named categorical tables for:

- relation-type traversal strengths;
- provenance source priors;
- query-class policies;
- packet section priorities;
- supported format/version identifiers.

Use formulas for continuous composition:

- evidence-strength multiplication;
- normalized transitions;
- budget allocation;
- score decay;
- latency/token trade-offs.

Use a learned or automatically calibrated policy only when:

1. representative fixtures and a stable objective exist;
2. the policy is bounded by safety and completeness invariants;
3. its chosen values appear in receipts;
4. a deterministic fallback exists;
5. held-out evaluation beats the simpler rule.

The constants are configuration parameters, not universal truths. They should be
named, documented, and calibrated against acceptance fixtures. Dynamic behavior
is valuable where the input is continuous; it is unnecessary complexity where a
finite policy table clearly represents product intent.

## 10. Verification and rollback

GraphGraph already has the right foundation: structural validation, semantic and
freshness receipts, packet validation, and executable acceptance quality gates.
These detect incomplete or stale context before it is treated as trustworthy.

“Deterministic rollback” should not currently be claimed. The runtime can repair
or reject an invalid graph program, but it does not transactionally undo arbitrary
source edits. A future rollback feature would require:

- an explicit mutation boundary;
- pre-change snapshots or reversible patches;
- source-control integration rules;
- failure classification;
- proof that rollback cannot discard unrelated user work.

For now, validation should fail closed and report the missing evidence. Source
recovery remains the responsibility of the calling agent and version-control
workflow.

## 11. Evaluation contract

No percentage improvement belongs in this document without a reproducible
benchmark, baseline, fixture set, and measurement date.

### 11.1 Existing acceptance dimensions

Keep measuring:

- exact-symbol recall and precision;
- caller/callee and flow-scope recall;
- affected-test discovery;
- documentation-stage coverage;
- token count;
- warm and cold latency;
- citation validity;
- freshness;
- truncation and answerability correctness.

### 11.2 New invariants

Add targeted checks as features land:

| Invariant | Required behavior |
|---|---|
| Provenance monotonicity | Lowering edge/provenance confidence cannot improve that edge’s normalized rank when alternatives remain fixed. |
| Rank-path consistency | Expansion and every PageRank implementation use the same effective edge semantics. |
| Temporal no-leakage | A view cannot expose a fact outside its valid interval. |
| Bi-temporal no-leakage | Once implemented, `known_at` cannot expose a later correction. |
| Prefix stability | A larger packet budget preserves the high-confidence evidence returned by a smaller budget, unless a documented optimizer rule supersedes it. |
| Coarsening safety | Coarsening cannot remove anchors, required evidence paths, citations, tests, or incompleteness receipts. |
| Branch isolation | Once implemented, unmerged branch records cannot alter parent or sibling results. |

### 11.3 Hypotheses, not promises

The following are research hypotheses:

- community-aware selection may lower tokens for broad architecture queries;
- a columnar adjacency layout may reduce load time and traversal overhead on
  sufficiently large graphs;
- branch-local memory may improve speculative workflows;
- transaction-time history may make historical receipts more trustworthy.

Each can also lose: community summaries may hide exact paths, CSR may complicate
updates, branches may add user-visible state, and temporal indexing may increase
storage and maintenance cost. Evaluation must include those costs.

## 12. Prioritized roadmap

### P0 — Semantic consistency

- [x] Use the same confidence- and provenance-aware edge value in expansion and
  all PageRank variants.
- [x] Add a regression test proving a stronger provenance source outranks an
  otherwise identical ambiguous source.
- [ ] Add the monotonicity and prefix-stability invariants to acceptance fixtures.

### P1 — Temporal contract

- [ ] Document current valid-time interval semantics in the public schema.
- [ ] Add no-future-leakage acceptance fixtures.
- [ ] Measure whether real workflows require transaction-time history.
- [ ] If justified, design and version the bi-temporal schema before implementation.

### P2 — Packet coarsening experiment

- [ ] Build an optional post-retrieval compiler pass.
- [ ] Compare no coarsening, current hierarchy, module hierarchy, and Louvain.
- [ ] Require equal-or-better retrieval quality before considering token savings.
- [ ] Keep the default unchanged until the benchmark has a clear winner.

### P3 — Storage profiling

- [ ] Profile parsing, loading, traversal, ranking, and serialization separately.
- [ ] Prototype columnar/CSR adjacency only if traversal layout is material.
- [ ] Require parity, mutation, temporal, and memory measurements.

### P4 — Branching and query language

- [ ] Gather concrete workflows that cannot be expressed with scopes and
  `GraphProgram`.
- [ ] Design copy-on-write overlays only if branch isolation solves those workflows.
- [ ] Add a textual query language only if a typed AST proves insufficient for
  external clients.

This ordering favors trust and measured retrieval quality over architectural
novelty.

## 13. Primary research references

- Peter Buneman, Sanjeev Khanna, and Wang-Chiew Tan,
  [Why and Where: A Characterization of Data Provenance](https://doi.org/10.1007/3-540-44503-X_20),
  ICDT 2001.
- Todd J. Green, Gregory Karvounarakis, and Val Tannen,
  [Provenance Semirings](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf),
  PODS 2007.
- Richard T. Snodgrass and Ilsoo Ahn,
  [A Taxonomy of Time in Databases](https://www2.cs.arizona.edu/~rts/pubs/SIGMOD85.pdf),
  SIGMOD 1985.
- Vincent D. Blondel et al.,
  [Fast Unfolding of Communities in Large Networks](https://arxiv.org/abs/0803.0476),
  2008.
- Shunyu Yao et al.,
  [Tree of Thoughts: Deliberate Problem Solving with Large Language Models](https://proceedings.neurips.cc/paper_files/paper/2023/hash/271db9922b8d1f4dd7aaef84ed5ac703-Abstract.html),
  NeurIPS 2023.
- Maciej Besta et al.,
  [Graph of Thoughts: Solving Elaborate Problems with Large Language Models](https://ojs.aaai.org/index.php/AAAI/article/view/29720),
  AAAI 2024.
- Huiqiang Jiang et al.,
  [LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models](https://aclanthology.org/2023.emnlp-main.825/),
  EMNLP 2023.
- Bernal Jiménez Gutiérrez et al.,
  [HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models](https://arxiv.org/abs/2405.14831),
  2024.
- Lianghao Liang et al.,
  [KAG: Boosting LLMs in Professional Domains via Knowledge Augmented Generation](https://arxiv.org/abs/2409.13731),
  2024.

These references motivate individual mechanisms. They do not establish GraphGraph
performance. Repository acceptance results remain the governing evidence.
