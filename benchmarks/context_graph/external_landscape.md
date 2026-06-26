# External Landscape

Question: does a context graph / RAG layer like this already exist?

Short answer: **partially, yes**. The broad idea exists. The exact combination
we are testing is less common:

- deterministic code/repo graph
- machine-efficient storage such as CSR/CSC or compact tables
- graph-hop retrieval policy
- ultra-compact LLM packet such as GG-LL
- explicit token/schema/round-trip/model-reasoning benchmark

## Closest Existing Systems

### Codebase-Memory

Codebase-Memory is very close conceptually. It builds a persistent Tree-sitter
knowledge graph for LLM code exploration through MCP, with call-graph traversal,
impact analysis, and community discovery. The paper reports much lower token
use and fewer tool calls than file exploration, with some answer-quality tradeoff.

Source: https://arxiv.org/abs/2603.27277

Fit:

- Strong match on persistent code graph and MCP access.
- Strong match on token-efficient code exploration.
- Unknown/less clear on compact prompt serialization and storage min-maxing.

### RepoGraph

RepoGraph is an open-source repository-level code graph for AI software
engineering. Its GitHub README says the `repograph` package constructs and
retrieves context from a graph, emits line-level tags and a NetworkX graph, and
integrates with Agentless and SWE-agent.

Source: https://github.com/ozyyshr/RepoGraph

Fit:

- Strong match on repository-level graph context.
- Strong match on SWE-bench-oriented code-agent use.
- Less focused on LLM packet/token format min-maxing.

### CodexGraph

CodexGraph integrates LLM agents with graph database interfaces extracted from
code repositories, letting an agent construct and execute graph queries for
precise code-structure-aware retrieval.

Source: https://arxiv.org/abs/2408.03910

Fit:

- Strong match on graph database + code repository + LLM agent.
- More agent/query-interface oriented than compact context-packet oriented.

### Microsoft GraphRAG

Microsoft GraphRAG is a modular graph-based RAG system. It is general-purpose
RAG over private/narrative data rather than specifically a codebase graph or
low-level packet format.

Source: https://github.com/microsoft/graphrag

Fit:

- Strong match on graph-based RAG.
- Weaker match on static code structure, repo-level dependency graphs, and
  compact LLM packets.

### LightRAG

LightRAG is a graph-enhanced RAG system combining graph structures with
vector/text retrieval. The GitHub project is active and large, and the paper
emphasizes simple, fast retrieval with graph structures and incremental updates.

Sources:

- https://github.com/HKUDS/LightRAG
- https://arxiv.org/abs/2410.05779

Fit:

- Strong match on graph + vector retrieval and incremental update direction.
- Not specifically a codebase graph min-max packet architecture.

### RepoScope

RepoScope constructs a repository structural semantic graph and uses
call-chain-aware multi-view context. It explicitly mentions
structure-preserving serialization for prompt construction.

Source: https://arxiv.org/abs/2507.14791

Fit:

- Strong match on repository graph retrieval and prompt serialization.
- Likely one of the closest academic neighbors to our "retrieval + compact
  LLM-facing structure" direction.

### Sourcegraph / Cody / Code Search

Sourcegraph has long built code intelligence over large codebases, including
symbol/reference graphs for navigation and search. This is production-grade code
graph infrastructure, though not necessarily the same as our explicit GG-LL
packet benchmark.

Source: https://en.wikipedia.org/wiki/Sourcegraph

Fit:

- Strong match on code intelligence graph/search.
- Commercial/platform implementation rather than open benchmark for packet
  formats.

## What Seems Novel In Our Work

The graph/RAG idea is not novel by itself. The useful novelty is the
benchmarking and architecture min-max frame:

- comparing full Markdown, keyword/BM25, graph-hop, SQL, compact adjacency,
  CSR-like arrays, GraphML, JSON, and hybrid packets
- measuring exact tokenizer cost
- separating machine storage floor from LLM prompt floor
- testing schema overhead with cached vs uncached prompt assumptions
- validating packet round-trip parseability
- keeping answer keys separate from retrieval code

## Current Conclusion

Closest existing category:

```text
Codebase-Memory / RepoGraph / CodexGraph / RepoScope
```

Closest general RAG category:

```text
GraphRAG / LightRAG
```

What we should not rebuild blindly:

- generic GraphRAG
- generic vector RAG
- basic code-symbol graph extraction

What is still worth exploring:

- the min-max prompt packet layer
- CSR/CSC-backed local graph store plus LLM packet renderer
- policy for graph_1hop vs graph_2hop escalation
- live model accuracy of low-level packets vs SQL rows vs hybrid snippets

