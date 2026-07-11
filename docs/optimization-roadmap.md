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

## P0: Accuracy Gates

1. Run frozen prompts through at least two live model families and score factual
   answers, citations, caller completeness, and blast-radius branch coverage.
2. Add query-conditioned section ordering for documents with more sections than
   the document node budget. The current policy retrieves sections, but graph
   traversal alone does not rank section text against the query.
3. Add adversarial ambiguity cases: duplicate symbols, generated sources,
   overloaded methods, re-exports, and mixed documentation/code anchors.
4. Measure completeness expectations separately from minimum evidence. A bounded
   packet can support an answer without listing every raw neighbor.

## P1: Mathematical Calibration

1. Refit packet token surfaces with train/holdout project splits. Include label
   bytes, fact bytes, relation-map cardinality, and packet fixed overhead.
2. Replace manually chosen query-class lambda values only if leave-one-project-out
   validation beats the current regularized budget with no evidence failures.
3. Test beam search or Lagrangian relaxation for multi-hop connected selection.
   Greedy is unsafe there because a low-value parent can unlock valuable descendants.
4. Calibrate local PPR tolerance and push limits by graph size and seed confidence,
   using top-k agreement and latency Pareto fronts rather than one fixed threshold.
5. Add latency and memory constraints to the budget objective. Token-only optima
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
