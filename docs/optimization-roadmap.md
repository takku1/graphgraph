# Optimization Roadmap

This roadmap separates measured production behavior from hypotheses. Structural
evidence gates prove that required graph evidence is present; they do not prove
that a particular model will interpret every packet correctly.

## Current Measured Baseline

- Production minimum-evidence gate: 90/90 real-project task contracts.
- Production average packet: about 294 proxy tokens with shape budgets enabled.
- Full raw-neighborhood completeness: 45/90, intentionally reported separately.
- Connected selection: greedy is roughly 93x faster than bucketed DP overall.
- Selection policy: greedy for direct/reverse/blast/summary; DP for multi-hop path.
- Personalized PageRank: confidence-routed local PPR retains exact-identifier speedups.
- Query routing: deterministic no-I/O auto routing passes 16/16 labeled agent
  intents at about 22.8 microseconds per route; explicit classes remain overrides.
- Document summaries: explicit document traversal now follows `section_of` edges.
- Section ranking: document section retrieval is query-conditioned. `graph.expand`
  accepts a `priority_bias`, and doc-oriented plans feed it heading-weighted BM25
  relevance so the budget keeps the sections that answer the query, not whichever
  sections graph shape favours (P0 #2, done).
- Locus source-baseline scan: 14.5s wall time / 12.2s scanner time for 10,646
  nodes and 40,530 edges, with 2.77s document extraction and 0.71s
  source-concept linking reported separately.
- Compound affected-test retrieval: bounded facet searches plus graph-aware
  anchor reservation achieved 6/6 requested-facet coverage on the Locus
  real-source benchmark question in about 4.16s.
- Document grounding: paragraph nodes and 1,200-character bounded facts recover
  the answer-bearing Phase 3 body and expose truncated document names.
- Qualified Rust identity: inherent and trait methods use owner-qualified IDs;
  same-file `TypeA::evaluate` and `TypeB::evaluate` remain distinct through
  full and incremental scans.
- Affected-test precision: exact `Type::method` resolution bypasses lexical
  candidate caps, facet anchors use owner coherence, and direction-consistent
  60/40 incoming/outgoing expansion removed file-sibling zigzags (36 -> 14
  nodes on the focused Locus query).
- Test-command trust: Cargo package/target discovery understands explicit test
  entries and aggregated `tests/<target>/main.rs` harnesses; recommendations
  report which selected symbols each test covers.

## P0: Accuracy Gates

1. Run frozen prompts through at least two live model families and score factual
   answers, citations, caller completeness, and blast-radius branch coverage.
2. Extend query-conditioned ranking beyond a document's own sections: rank
   cross-document section matches and long-fact bodies against the query, and
   fold in an embedding fallback for synonym queries that share no lexical
   terms with the section text. (Heading-weighted BM25 section ranking within
   the budget and bounded paragraph-body indexing are done; query-time recovery
   from over-cap paragraph spans remains open.)
3. Extend the adversarial ambiguity suite. The initial benchmark
   (`adversarial_ambiguity_benchmark.py`, 6/6) and a generated-source ranking
   penalty are done; same-named Rust methods across same-file impl owners are
   now covered. Still to add: name collisions across many files, cyclic
   re-export chains, and overloads distinguished only by signature/arity.
4. Measure completeness expectations separately from minimum evidence. A bounded
   packet can support an answer without listing every raw neighbor.

## P1: Mathematical Calibration

Scoring-model note: `search_nodes` is a multiplicative (log-linear) ranking
model -- `log(score) = log(base) + Σ feature·log(weight)`. Penalties on binary
facts (is-test, is-generated, is-external) are single weights and are correct
as constants; there is no continuous input there to turn into a formula.
Continuous signals should be smooth functions, so the former hard `min()` caps
on the PageRank and degree boosts are now `tanh` saturations. The remaining
"proper formula" upgrade is to fit all of these weights from labeled
query -> correct-node data rather than hand-setting them; that is gated on the
same evaluation signal as the accuracy gates below.

1. Fit the ranking-model weights (penalty log-weights, boost caps, coverage
   slope) by leave-one-project-out on labeled anchor-resolution data once an
   eval set exists. Until then hand-set weights are the honest state.
2. Refit packet token surfaces with train/holdout project splits. Include label
   bytes, fact bytes, relation-map cardinality, and packet fixed overhead.
3. Replace manually chosen query-class lambda values only if leave-one-project-out
   validation beats the current regularized budget with no evidence failures.
4. Beam search now reserves the strongest bounded path between anchors
   (`_beam_best_path`): level-synchronous so length stays minimal, but the
   equal-length tie-break maximises cumulative edge strength instead of taking
   whatever the adjacency yields first. Still open: the connected-selection
   *partition* keeps exact tree-knapsack DP for `multi_hop_path`; evaluate
   Lagrangian relaxation there only if a case shows DP is too slow or the tree
   restriction drops a valuable non-tree route.
5. Local PPR limits are now calibrated by graph size and seed count
   (`adaptive_local_ppr_params`): tolerance ~ c/N (sharper on big graphs where
   PPR mass is smaller), frontier ~ sqrt(N) x seeds, push budget tracks the
   frontier, all clamped. Synthetic sweep vs the old fixed constants: overlap@10
   with full PPR holds or improves (0.70 -> 0.80 at 20k-50k nodes) and small
   graphs run ~3x faster with no accuracy loss. Still open: fold measured
   latency into the choice (Pareto front) and adapt to seed *concentration*
   (weight entropy), not just seed count.
6. Add latency and memory constraints to the budget objective. Token-only optima
   can be operationally wrong when graph loading or selection dominates.

## P1: Evidence-Aware Refinement

1. Keep the monolithic query as the global retrieval prior, then use facets for
   evidence verification/reranking. This matches the stage-aware result reported
   in [When Should Queries Be Decomposed?](https://arxiv.org/abs/2606.08577):
   early decomposition can dilute retrieval, while later constraint checks gain
   from decomposition. GraphGraph already preserves the whole-query search and
   adds bounded facet searches; benchmark Reciprocal Rank Fusion across those
   ranked lists before replacing the current graph-aware reservation score.
2. Make facet budgets adaptive only after a labeled coverage/latency set exists.
   A useful candidate is an exploration/exploitation allocation over facets, but
   it must beat equal reservation without starving low-frequency requested
   evidence. The relevant primary result is
   [MAB-DQA](https://aclanthology.org/2026.acl-long.1053/), which treats aspects
   as bandit arms and reallocates retrieval budget from observed utility.
   The low-latency receiver-evidence baseline is now implemented: Python
   annotations, stable constructor/literal bindings, direct class receivers,
   and stable `self.field` types can activate trusted call edges. Unknown
   receivers remain telemetry rather than name-only candidate topology, and
   ontology relations with zero traversal strength are hard-blocked during
   expansion.
3. Add an optional, query-local typed Rust refinement tier for unresolved member
   calls. Tree-sitter remains the low-latency default; only the selected crate or
   files should pay for compiler-grade evidence. Rust's
   [THIR](https://rustc-dev-guide.rust-lang.org/thir.html) is the right semantic
   target because it is post-type-checking and converts method calls/implicit
   dereferences into explicit function calls. Measure rust-analyzer/rustc query
   startup and cacheability before choosing the integration surface.
4. For documents that hit paragraph caps, build a small overflow-only lexical
   sidecar mapping terms to `(path, byte_start, byte_end)`. At query time, score
   only those overflow spans and materialize the winning paragraph as an
   ephemeral node. This preserves bounded graph size without making late body
   paragraphs permanently unreachable.
5. Fit the affected-test incoming/outgoing budget share from labeled
   implementation-and-test queries. The current 60/40 allocation has a bounded
   union and removed the observed direction-zigzag noise, but remains a
   hand-set prior until cross-project recall/latency data supports a learned or
   query-conditioned share.

## P1: Runtime Efficiency

Completed platform hot-path work:

- Production rendering and benchmark gates execute `GraphRuntime.compile`
  instead of maintaining parallel route/retrieve/render implementations.
- Evidence IR uses query-prioritized SQLite partitions with transactional
  incremental refresh and exact aggregate receipts.
- Semantic indexes and federated graph files are cached per process with
  mtime/size invalidation.
- CPG providers consume the scanner's public CST adapter, and shared state I/O
  no longer creates a runtime-to-platform dependency.

1. Build relation-indexed adjacency if hub benchmarks show repeated relation
   filtering is material after graph loading.
2. Graph, packet, evidence, memory, temporal, semantic, and federation state now
   use atomic replacement or locked append operations. Continue stress-testing
   high-contention multi-process workloads and stale-lock recovery on CI hosts.
3. Profile scanner and native graph load allocations on 10k, 100k, and 1m-node
   synthetic graphs before adding more compression formats.
4. Track cold process startup, graph load, search, expansion, selection, rendering,
   and validation as separate latency stages.

## P2: Source Organization

1. Split `retrieval/context.py` into query orchestration, expansion/evidence
   reservation, and sibling-enrichment modules once behavior stabilizes.
2. Split `scanner/frontends.py` by frontend ownership: base protocol, Tree-sitter
   extraction, call resolution, and import/re-export resolution.
3. Split CLI and MCP command registries by feature domain while preserving public
   entry points.
4. Group benchmarks by gate type only when imports and canonical artifact paths
   can be migrated without breaking promotion automation.

## Promotion Rule

A runtime optimization is promotable only when it preserves the production
minimum-evidence gate, packet validation, connectivity invariants, and full test
suite. Claims about answer quality require model-scored evidence in addition to
structural containment.
