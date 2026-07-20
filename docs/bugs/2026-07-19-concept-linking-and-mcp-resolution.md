# Concept linking and Codex MCP resolution

Date: 2026-07-19

## Outcome

GraphGraph now projects exact frontend evidence into a small normalized
interpretation IR instead of treating concept labels as semantic proof:

```text
source primitive
  -> normalized fact
  -> typed interpretation edge
  -> closed-registry concept
```

The first two portable instructions are:

```text
== / != / exact equality assertion
  -> semantic_operator:equality
  -> uses_semantic_operator
  -> Equality Comparison

Rust BTreeSet/HashSet construction plus insert
  -> semantic_operation:deduplication
  -> performs_semantic_operation
  -> Deduplication
```

This is the low-level, LLM-facing shape intended by the advanced context
design: compact semantic operands and explicit gates, not prose that the model
must reinterpret.

No Graphify runtime, wrapper, graph, or implementation was used. Graphify
remains comparison-only.

## Root causes

### Apparent concept coverage was false

The previous four Locus source-concept links were generated interpretation
nodes relinking themselves:

- Bellman Optimality Equation to itself.
- Personalized PageRank to itself.
- Tree Knapsack Dynamic Programming to itself.
- Monte Carlo Tree Search to itself.

Generated registry kinds were not excluded from source eligibility. Incremental
manifest restoration could also preserve those stale edges.

### Source evidence already existed but stopped at facts

The Rust frontend already emitted exact facts including
`semantic_operator:equality` and `semantic_operation:deduplication`. The concept
pass only recognized aliases in labels, paths, summaries, and facts; it had no
typed fact-to-concept instruction.

### Natural-language concept lookup lost to personalization

An exact phrase such as `Equality Comparison` ranked first lexically, but
production personalized ranking could promote unrelated high-churn source
symbols. Reverse traversal also did not admit the new interpretation
relations.

### The Codex plugin cache had a Windows launch hazard

The stale cached plugin launched:

```text
uv run --project C:/Users/dcarn/aiprojects/graphgraph graphgraph-mcp
```

`uv` attempted to synchronize the environment and replace a console executable
held open by another process. MCP initialization failed before the server
started. The portable `graphgraph-mcp` command itself was healthy.

## Implementation

- Added closed-registry typed concepts for Equality Comparison and
  Deduplication.
- Added exact source-fact mappings and typed relations:
  `uses_semantic_operator` and `performs_semantic_operation`.
- Added proof-bearing edges with:
  - provenance `interpretation_registry_fact`;
  - confidence `0.98`;
  - evidence `normalized_ir_fact:<fact>`.
- Excluded all generated interpretation concept IDs from source eligibility.
- Removed legacy source-concept edges whose source is a registry concept,
  including incrementally restored edges.
- Split receipts into typed-fact links, exact-alias links, linked nodes, and
  linked concept count.
- Renamed the rejection receipt to the transport-neutral `no_evidence` while
  preserving the old `no_registry_alias` field for compatibility.
- Added the relations to the ontology and relevant reverse, blast-radius, and
  subsystem traversal policies.
- Added exact embedded-registry-label anchoring for direct/reverse lookups.
- Kept budget truncation honest: a bounded reverse lookup over a large concept
  hub reports incomplete and abstains.
- Removed comment, string, character, heredoc, and regex-literal regions before
  projecting operator facts so text such as `"left == right"` is not evidence.
- Reconciled the canonical, agent, and plugin skill contracts and added a parity
  regression test.
- Refreshed and cachebusted the local Codex plugin. The new cached MCP command
  is the portable `graphgraph-mcp` entry point.

## Locus black-box measurement

The validation graph was written outside Locus's own graph location, so the
measurement did not replace its working graph.

| Metric | Before | After |
|---|---:|---:|
| Graph nodes | 13,138 | 13,150 |
| Graph edges | 46,438 | 48,298 |
| Eligible source nodes | 6,912 | 6,918 |
| Linked source nodes | 4 | 1,789 |
| Coverage | 0.06% | 25.86% |
| Health | sparse | partial |
| Source-concept edges | self-link noise | 1,835 typed facts |
| Exact alias edges | 4 apparent self-links | 0 |
| Linked concepts | effectively 0 | 2 |

The 1,835 links comprise:

- 1,771 `uses_semantic_operator` edges.
- 64 `performs_semantic_operation` edges.

Linked nodes are fewer than links because some source symbols carry both exact
facts.

The all-edge mechanical audit checked every source-concept edge for:

- a matching required fact on the source node;
- the exact proof token;
- the intended registry target;
- typed provenance and confidence;
- no registry concept as edge source.

Result: 1,835 checked, zero violations.

This establishes structural precision against GraphGraph's declared evidence
contract. It does not claim that every equality operator or set insertion is a
high-level business concept; the relation names intentionally stay at the
normalized operator/operation layer.

## Retrieval acceptance

Query:

```text
Which source symbols use Equality Comparison?
```

Observed result:

- root: `Equality Comparison`;
- relation: only `uses_semantic_operator`;
- 11 direct source neighbors returned under a 12-node budget;
- 1,771 known direct neighbors;
- 1,760 omitted;
- answerability: `incomplete`, abstained;
- truncation reason: `node_budget`.

The packet therefore exposes a bounded useful slice without pretending that it
enumerated the complete reverse neighborhood.

## Codex MCP acceptance

- Plugin installed and enabled as
  `0.1.0+codex.20260720165227`.
- Cached command: `graphgraph-mcp`.
- MCP initialize: passed.
- Tools/list: 21 tools.
- Required tools present:
  `query_context`, `project_status`, `validate_packet`, `build_graph`, and
  `update_graph_files`.
- `graphgraph doctor`: plugin bundle configured; installed skill and validator
  current.

An already-open Codex thread cannot dynamically acquire a newly installed MCP
namespace. A fresh thread is the final client-exposure boundary; server
initialization itself is already verified.

## Constants versus dynamic behavior

The remaining constants have different roles and should not be treated alike:

- The closed concept registry is intentionally fixed. A dynamic formula that
  invents concept labels would weaken provenance and recreate fuzzy semantic
  false positives.
- Fact-to-relation mappings are intentionally exact instructions. They are
  extensible by adding a verified frontend fact, not by lowering a similarity
  threshold.
- Confidence values are evidence calibration constants and are surfaced in
  receipts. They should be recalibrated from labeled corpora, not varied per
  query.
- The 20% supported-coverage gate remains a policy constant. It should be
  calibrated across foreign repositories later, but must not dynamically fall
  merely to make a sparse graph report healthy.
- Query budgets and graph traversal remain shape-adaptive. Coverage health and
  truncation are computed from the actual graph.

This division keeps truth gates fixed and observable while allowing cost and
selection to adapt to project shape.

## Regression coverage

Tests cover:

- positive equality and dedup fact links;
- label/path/prose-only negative cases;
- comments and strings containing equality syntax;
- exact legacy registry aliases;
- registry self-link prevention;
- stale incremental self-link removal;
- metadata evidence breakdown;
- the 20% health boundary;
- exact natural-language concept anchoring;
- typed reverse traversal;
- ontology and provenance calibration;
- canonical/agent/plugin skill parity;
- no-sync project launcher generation.

Final repository gates:

- the full GraphGraph pytest suite passes;
- Ruff passes across source, tests, benchmarks, and scratch diagnostics;
- CLI startup and the relocated MCP/core import surfaces pass;
- the focused Locus game-theory command passes 13 tests.

One broad-query boundary remains intentionally visible: a composite,
repository-meta blast-radius prompt can recommend a generic graph regression
instead of the most feature-specific test file. Exact interpretation-concept
queries and their truncation receipts are verified, but broad test
recommendations remain evidence to verify, not authority to skip source/test
inspection.

## Concurrent retrieval refactor integration

During validation, the shared worktree's retrieval monolith was split into:

- `anchors.py`;
- `document_status.py`;
- `expansion.py`;
- `facets.py`;
- `pruning.py`;
- `quality.py`;
- `reservations.py`;
- `scoping.py`;
- `test_recommendations.py`.

The split was preserved and audited instead of reverted:

- all 92 top-level functions from the pre-split `context.py` remain present;
- zero old functions are missing;
- only `retrieve_context` and `packet_quality_metadata` have changed ASTs,
  matching the intentional orchestration and semantic-receipt work;
- the extracted module dependency graph is acyclic;
- `graphgraph.retrieval.context` re-exports the former helper surface for
  compatibility;
- the retrieval, planning, packets, MCP, concept, and package-local
  recommendation tests pass together.

This reduces the retrieval entrypoint from a multi-thousand-line mixed
implementation to an orchestrator without changing the established behavior
hidden behind its import surface.
