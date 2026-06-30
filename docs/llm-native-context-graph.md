# LLM-Native Context Graph Design

This document states the direction bluntly: `graphgraph` should own a native
context graph runtime while interoperating with other graph generators through
explicit imports and benchmarks.

## Thesis

Most RAG systems optimize retrieval into human-readable text. That is useful,
but it leaves a lot of token budget on the floor. For code agents, the high
value context is often structural:

- which symbol calls which symbol,
- which file imports which file,
- which tests cover which behavior,
- which config controls which runtime path,
- which docs constrain which implementation.

The LLM does not need this as paragraphs by default. It needs a compact,
consistent representation it can attend over without wasting context on prose
syntax, repeated labels, and JSON keys.

The internal graph still needs richer memory than a bare adjacency list. The
compact packet is the LLM boundary format, not the whole system.

The target is analogous to low-level programming:

- **source prose** is convenient but expensive,
- **JSON/GraphML** is portable but verbose,
- **semantic arrows** are readable assembly,
- **relation-coded adjacency** is bytecode,
- **CSR/bitsets** are machine storage, not usually prompt text.

`graphgraph` should learn when each layer is the right layer.

## What "Close To The LLM" Means

We cannot write directly into model weights from a project CLI. We also cannot
assume stable access to provider KV-cache internals. The useful engineering
target is therefore:

1. Use stable compact symbols so repeated entities map to repeated tokens.
2. Keep related edges near their nodes to reduce long-distance lookup burden.
3. Use relation opcodes when the graph is large and relation vocabulary is
   small.
4. Use inline relation words when lookup indirection harms interpretation.
5. Add source facts only when the query requires semantics beyond topology.
6. Validate that the model actually answers correctly from each packet format.
7. Keep a path open for runtime-native memory integrations if model providers
   expose stable KV-cache or attention-augmentation APIs.

Token count is a necessary metric, not the final metric.

## Research Baseline

Current academic systems point to the same broad lesson: graph structure helps,
but only when retrieval, indexing, and summarization are designed around it.

- Microsoft GraphRAG builds a graph and community summaries for query-focused
  summarization across a corpus.
- LightRAG emphasizes dual-level retrieval and incremental graph maintenance.
- HippoRAG treats graph-shaped memory as a long-term associative memory layer.
- KAG pushes knowledge-graph-grounded generation for professional domains where
  factual precision matters.
- KBLaM-style approaches are closer to the low-level dream: encode knowledge
  into continuous key-value vectors and integrate them through attention. That
  is not available through ordinary prompt packets, but it is the right
  north-star for "how close can context get to the model's native substrate?"

The gap for `graphgraph` is narrower and more practical: code-agent context
packets. It should beat generic graph RAG systems when the task is local,
structural, and agent-loop constrained.

## Competitive Requirements

To be credible, `graphgraph` needs first-class support for:

1. Native indexing: code, docs, policies, tests, configs, and generated facts.
2. Incremental updates: changed files should update affected nodes and edges.
3. Query planning: choose anchors, hop count, packet format, and source snippets.
4. Evaluation: measure node recall, edge recall, path recall, answer accuracy,
   irrelevant context, token count, and latency.
5. Interop: import Graphify, Neo4j exports, CSV/TSV, and code-review graphs
   without treating any of them as the native core.

## Context Graph Semantics

A useful AI context graph needs more than nodes and edges:

- **Edge semantics**: relation types such as `calls`, `imports`, `contains`,
  `references`, `implements`, `causes`, `depends_on`, or `similar_to`.
- **Direction and strength**: `source -> target`, `weight`, and `confidence`
  must distinguish hard dependencies from weak signals.
- **Temporal validity**: `valid_from`, `valid_to`, `created_at`, and
  `updated_at` let the graph separate stale context from current context.
- **Hierarchy and scope**: node `parent` and `scope` support zooming between
  symbols, files, packages, subsystems, and communities.
- **Uncertainty and provenance**: edge `provenance`, `confidence`, `evidence`,
  and `source_location` keep inferred facts separate from extracted facts.
- **Active vs latent context**: inactive nodes/edges remain stored but are not
  used by default retrieval. This lets the graph remember dormant context
  without pushing it into every prompt.
- **Grounding anchors**: node `path`/`source` and edge `source_location` keep
  graph facts tied back to repo files or external artifacts.

The packet renderer should compress most of this away unless the query needs
it. Retrieval and scoring should use it aggressively.

## Packet Ladder

Use a ladder instead of a single favorite format:

| Layer | Use For | Prompt Suitability |
| --- | --- | --- |
| `.gg` adjacency | native storage and human-editable graph files | good |
| `svo` | tiny direct evidence packets | excellent |
| `semantic_arrow` | relation clarity with moderate token cost | excellent |
| `gg_max` | larger topology packets with low token cost | good, must validate |
| `gg_max_hybrid` | topology plus summaries/facts | good for summaries |
| CSR/bitset | machine retrieval and benchmarks | poor as raw prompt |
| JSON/GraphML | interchange/debugging | poor as prompt |

## Brutal Current Gaps

- Native retrieval is only lexical anchor search plus graph expansion. It is a
  bootstrap, not yet competitive with hybrid lexical/vector/graph retrieval.
- Symbol extraction and a durable file-hash manifest exist, but the active
  project graph can still regress to file-level evidence if dependencies or
  scanner options are missing.
- There is no native semantic extraction route for docs beyond links and weak
  filename mentions.
- There is no live model answer benchmark in CI, so compression can outrun
  interpretation accuracy.
- `.gg` has basic round-trip tests, but still needs a formal spec, large-graph
  regression coverage, and model parsing tests.

## Near-Term Direction

1. Make `.graphgraph/graph.gg` and `.graphgraph/graph.json` the native stores.
2. Enforce active-graph quality checks so symbol/doc scans do not silently
   degrade to file-only graphs.
3. Add hybrid retrieval: lexical anchors, graph expansion, optional embeddings,
   and source snippet grafting.
4. Extend benchmarks to compare against Graphify output and standard RAG packet
   baselines on identical tasks.
5. Add live model-answer scoring for each packet format before claiming wins.
