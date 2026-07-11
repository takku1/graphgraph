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
- Document summaries: explicit document traversal now follows `section_of` edges.
- Section ranking: document section retrieval is query-conditioned. `graph.expand`
  accepts a `priority_bias`, and doc-oriented plans feed it heading-weighted BM25
  relevance so the budget keeps the sections that answer the query, not whichever
  sections graph shape favours (P0 #2, done).

## P0: Accuracy Gates

1. Run frozen prompts through at least two live model families and score factual
   answers, citations, caller completeness, and blast-radius branch coverage.
2. Extend query-conditioned ranking beyond a document's own sections: rank
   cross-document section matches and long-fact bodies against the query, and
   fold in an embedding fallback for synonym queries that share no lexical
   terms with the section text. (Heading-weighted BM25 section ranking within
   the budget is done; see baseline.)
3. Extend the adversarial ambiguity suite. The initial benchmark
   (`adversarial_ambiguity_benchmark.py`, 6/6) and a generated-source ranking
   penalty are done; still to add: name collisions across many files, cyclic
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
4. Test beam search or Lagrangian relaxation for multi-hop connected selection.
   Greedy is unsafe there because a low-value parent can unlock valuable descendants.
5. Calibrate local PPR tolerance and push limits by graph size and seed confidence,
   using top-k agreement and latency Pareto fronts rather than one fixed threshold.
6. Add latency and memory constraints to the budget objective. Token-only optima
   can be operationally wrong when graph loading or selection dominates.

## P1: Runtime Efficiency

1. Build relation-indexed adjacency if hub benchmarks show repeated relation
   filtering is material after graph loading.
2. Make graph and packet caches thread-safe before concurrent MCP requests are
   supported. Add file locking or atomic replacement for persistent cache writes.
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
