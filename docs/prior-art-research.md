# Prior art: code-graph and agent-memory systems

This replaces `docs/enterprise.md`, which was an unedited copy-paste of a
general "enterprise AI platform stack" survey — mostly identity/security,
observability, and business-automation categories with no bearing on what
this project does. Renamed and rewritten to keep only what's actually in
graphgraph's domain: **how other systems build a queryable graph of code (or
of agent memory) and rank what matters inside it.**

Per [`rigorous-framing.md`](rigorous-framing.md): this is a research/ideas
log, not a roadmap commitment. Each entry ends with a verdict — already
covered, partial, genuine gap, or consciously different by design — so it's
clear what, if anything, is actionable.

## Code indexing / code graph systems

### Meta Glean — [glean.software](https://glean.software/), [engineering.fb.com writeup](https://engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/)
Open-source fact-indexing system for monorepo-scale code search. Per-language
indexers extract facts into compact, incremental storage designed for
billions of facts; queried with **Angle**, a Datalog-style query language.
Also ships LSIF/SCIP ingestion for languages without a native indexer.

**Verdict:** architecturally similar in spirit (structured facts about code,
language-agnostic core), but built for a different scale (monorepo,
billions of facts) and a different consumption model (a general query
language for tools, not LLM context packets). graphgraph's fixed,
empirically-calibrated query classes (`direct_lookup`, `blast_radius`, ...)
are a deliberate simplification for the LLM-context use case — a full
Datalog engine would be over-engineering here. **Consciously different by
design**, not a gap.

### Sourcegraph SCIP + Zoekt — [SCIP announcement](https://sourcegraph.com/blog/announcing-scip), [cross-repo nav](https://sourcegraph.com/blog/cross-repository-code-navigation)
SCIP is a language-agnostic protobuf protocol for precise symbol
definitions/references, designed to make cross-*repository* navigation work
(a click on an import in repo A lands on the exact line in repo B). Zoekt is
the underlying fast trigram full-text index with a real ranking/query
language layer, not just raw grep.

**Verdict:** graphgraph is explicitly single-repo-native (external graphs
only enter via `ingest`), so SCIP's cross-repo resolution model doesn't
directly apply — but the **idea of a stable, language-agnostic symbol ID
scheme** is exactly what graphgraph's node IDs already are. **Already
covered** conceptually; cross-repo resolution specifically is out of scope
by design (see `docs/architecture.md`).

### Google Kythe — [kythe.io/docs/kythe-overview](https://kythe.io/docs/kythe-overview.html)
Language-agnostic cross-reference graph for Google's internal multi-language
monorepo. The key architectural point: a **hub-and-spoke schema** reduces the
integration cost of L languages × C clients × B build systems from O(L×C×B)
to O(L+C+B) — every frontend normalizes into one shared graph shape once,
instead of every client needing bespoke per-language logic.

**Verdict:** **already covered** — this is exactly graphgraph's own
frontend architecture (`scanner/frontends.py`'s `RegexExtractor`/
`TreeSitterExtractor` both normalize into the same `Node`/`Edge` shape).
Worth citing as independent validation that the pattern is sound, not a new
idea to adopt.

### GitHub CodeQL — [appsecsanta.com overview](https://appsecsanta.com/github-codeql)
Treats code as a queryable database (SQL/Datalog-like) supporting arbitrary
data-flow queries across functions/files/modules, mainly for security
analysis across 12+ languages.

**Verdict:** same shape as Glean's tradeoff — a general query language for
arbitrary program-analysis questions is a different goal than compact,
pre-planned LLM context packets. **Consciously different by design.**

### Aider's repo-map — [aider.chat/2023/10/22/repomap.html](https://aider.chat/2023/10/22/repomap.html)
The most directly comparable tool: tree-sitter parses source, builds a graph
of definitions/references, ranks it with **PageRank**, and renders a
token-budgeted summary — same problem (compact codebase context for an LLM
coding agent), same core algorithm family as graphgraph.

The specific detail worth pulling out: Aider's personalization multipliers
on the PageRank seed vector —
**mentioned identifiers ×10, well-named identifiers ×10, active chat files
×50**.

**Verdict, checked directly against graphgraph's own retrieval code
(`retrieval/search.py`, confirmed via
`test_personalization_lexical_score_constants`):**
- "mentioned identifiers" boost — **already covered** (exact-id-match is a
  flat +8.0 lexical bonus; git-session-modified files get a
  `log2(change+2)*2.0` weight, conceptually Aider's "chat files" idea via a
  different signal — recent git activity instead of open chat buffers).
- **"well-named identifiers" boost — genuine gap.** Grepped
  `graph/core.py` and `retrieval/*.py` directly: nothing currently
  distinguishes a descriptive identifier (`resolve_modified_node_ids`) from
  a generic one (`x`, `tmp`, `data`) when scoring. This is a concrete,
  cheap, well-scoped feature to consider: a small score bonus for labels
  that look like real words (length, snake_case/camelCase segmentation,
  not a single short/generic token) — the same kind of signal Aider found
  worth 10x weighting.

## Agent memory / knowledge-graph-as-memory systems

This is the actual technical territory behind "Vektor" (the internal
Epic-Games-job-listing name for "org-wide memory plane with knowledge
graph" that prompted the original doc) — the real, researchable public
analogs are these:

### Zep / Graphiti — [vectorize.io comparison](https://vectorize.io/articles/mem0-vs-zep)
Builds agent memory as a **temporal knowledge graph** where time is a
first-class dimension of every fact, not just a timestamp field. Reported
15-point gap over Mem0 on the LongMemEval benchmark, attributed specifically
to temporal-graph structure.

**Verdict: partial.** graphgraph already has real bitemporal bones —
`Edge.valid_from`/`valid_to`, `Node.created_at`/`updated_at`, soft-delete
via `expire_node`/`expire_edge` keeping an append-only operation log
(`docs/incremental-update-instruction-set.md`), plus git-history-derived
`fixes`/churn edges. What's *not* exploited yet: none of the query classes
let a caller ask a time-scoped question ("what did this function's
dependents look like as of commit X," "what changed in the last N
commits that touches this subsystem"). The storage model already supports
it; the retrieval layer doesn't expose it. Worth a scoped experiment before
committing to it — per `rigorous-framing.md`, don't promote this without a
benchmark showing it actually helps.

### Mem0 — [mem0.ai](https://mem0.ai/)
Dual-store: vector DB for semantic recall + a separate knowledge graph for
entity relationships, queried together.

**Verdict:** graphgraph is graph-only by design (no vector/embedding store)
— that's a real, intentional scope boundary (`docs/architecture.md`/
`docs/rigorous-framing.md`: claims about embeddings are explicitly listed as
needing evidence, not assumed). Not a gap to close; a boundary to keep
honest about, which the project already does.

## What to actually do with this

Two concrete, scoped candidates came out of this pass, in priority order:

1. **"Well-named identifier" lexical bonus** (from Aider) — small, cheap,
   directly testable against the existing benchmark suite
   (`benchmarks/context_graph/`). Lowest-risk next step if this list turns
   into work.
2. **Time-scoped query classes** (from Zep/Graphiti) — bigger, needs a
   concrete use case and a benchmark before promotion, per this project's
   own evidence bar. Don't build it speculatively.

Everything else in this survey is either already covered by graphgraph's
existing architecture (validated independently by Kythe's hub-and-spoke
precedent, SCIP's symbol-ID model) or a deliberate scope boundary the
project already states honestly elsewhere (no query language, no
cross-repo resolution, no embeddings).
