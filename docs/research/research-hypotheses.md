# High-Value Ideas - Critical Runtime Plan

This file is an implementation filter, not a wishlist. The useful direction for
GraphGraph is not "bigger graph". It is faster compilation of small, validated,
query-specific packets that an LLM can actually use.

## Implemented Or Worth Keeping

1. Hot in-memory search indexes
   - Keep JSON/`.gg` as storage and interchange formats.
   - Keep per-loaded-graph memory indexes for search rows and token-to-node
     candidates.
   - Avoid scoring every node for normal token queries.

2. Two-phase retrieval
   - Phase 1: lexical and query-personalized anchor selection.
   - Phase 2: relation-aware expansion using query-class traversal policy.
   - Phase 3: packet refinement from observed subgraph shape.

3. Query-class-specific traversal
   - Keep this first-class. `direct_lookup`, `reverse_lookup`,
     `blast_radius`, `multi_hop_path`, `subsystem_summary`, `doc_summary`, and
     `negative_query` should not share one BFS policy.

4. Relation confidence and weak-edge throttling
   - Keep confidence/provenance gating.
   - Suppress weak/noisy relation fans unless the query asks for conceptual or
     documentation context.

5. Context packet compiler
   - The runtime should return validated packets, not raw graph dumps.
   - Mechanical validation must fail empty packets and broken references.

6. Scoped retrieval
   - Scope must constrain anchor search and expansion.
   - Applying scope only after anchor selection is a quality bug because the
     wrong subsystem can win before expansion starts.

7. Dependency-aware cache metadata
   - Packet cache entries now record node and path dependencies.
   - Current invalidation still uses graph mtime for safety; dependency metadata
     is the foundation for finer invalidation once incremental graph updates
     expose changed node/file sets.

8. Eval manifests as runtime contracts
   - Benchmark files must actually run through the CLI.
   - Support flat task lists, `tasks`, nested `projects`, `query`, and
     `question` task records.

9. Lazy source snippets
   - First-stage packets stay graph-shaped and compact.
   - Exact source is loaded only for selected node IDs, labels, or paths via
     the `snippets` CLI/MCP path.
   - Excerpts are bounded by line count and centered on node line metadata when
     available.

## Deferred Until There Is A Benchmark Need

1. SQLite/duckdb/mmap runtime store
   - This is plausible, but it is a storage project.
   - Do not add it until in-process graph load/traversal is proven to dominate
     latency after process startup and Python import overhead are separated.

2. Graph delta packets
   - Useful for multi-turn sessions, but needs stable packet identity and a
     client-side previous-packet contract.

3. Community summaries as supernodes
   - Useful only if generated summaries are verified against source and do not
     become stale prose.

4. Contradiction detection
   - Valuable, but it needs doc/code alignment metrics and explicit false
     positive handling. Do not bolt it into retrieval as a heuristic.

## Rejected As Currently Too Vague

1. "Attention-aware ranking" as a standalone subsystem
   - Keep the concrete signals: exact matches, source proximity, relation
     strength, test penalties, doc/code bridge, git churn, centrality, and
     query-class fit.
   - Do not introduce an opaque attention score without eval wins.

2. "Budget optimizer" without task evidence
   - Keep measured defaults and shape-aware trims.
   - Do not let a continuous formula override recall-sensitive query classes
     unless benchmark fixtures prove it.

## Next Best Work

1. Build project-specific benchmark manifests for this repo.
2. Measure loaded-graph search latency separately from CLI startup.
3. Use packet dependency metadata for incremental cache invalidation once the
   scanner exposes changed node IDs and changed paths.
4. Build project-specific benchmarks for snippet usefulness and answer impact.
