# Research Baseline

This benchmark is grounded in a few current patterns from RAG and code-agent
research.

## What Existing Work Suggests

- RAG uses external retrieval at inference time so the model can answer from
  current or private data without retraining.
  Source: https://en.wikipedia.org/wiki/Retrieval-augmented_generation
- Microsoft GraphRAG extracts a knowledge graph, builds community structure,
  and uses that structure during RAG tasks instead of relying only on plain
  semantic chunks.
  Source: https://microsoft.github.io/graphrag/
- RAPTOR shows that hierarchical summaries can improve retrieval for questions
  that require integrating information across a long corpus.
  Source: https://arxiv.org/abs/2401.18059
- LightRAG argues for combining graph structures with vector/text retrieval to
  improve contextual awareness and support incremental updates.
  Source: https://arxiv.org/abs/2410.05779
- GraphCoder and GRACE report gains for repository-level coding tasks by using
  code graphs rather than only text-similarity retrieval.
  Sources: https://arxiv.org/abs/2406.07003 and https://arxiv.org/abs/2509.05980
- CodexGraph explores putting repository structure into a graph database so an
  LLM agent can query precise code relationships.
  Source: https://arxiv.org/abs/2408.03910

## Working Hypothesis

The best system is likely not "Markdown vs graph" but:

1. store machine-readable graph context,
2. retrieve a query-specific subgraph,
3. attach source snippets for grounding,
4. render the final packet in compact Markdown.

This benchmark is designed to test that hypothesis without overfitting to one
hand-picked query type.

