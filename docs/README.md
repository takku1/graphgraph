# graphgraph Docs

`graphgraph` is an empirical lab and early implementation for one question:

> What is the cheapest context representation an LLM can reliably interpret?

The current answer is not a universal winner. The measured shape is:

1. store rich context as structured records,
2. retrieve a narrow graph neighborhood,
3. render the LLM-facing packet with the cheapest passing format,
4. add only scoped policy constraints,
5. validate packets mechanically before live model-answer scoring.

This page is the authoritative index. Every operational and reference document
below has an inbound link from here (enforced by
`tests/test_docs_contract.py`); scratch material lives under `docs/notes/` and
is intentionally excluded.

## Operational

How to run, evaluate, and extend the tool.

- [Start Here](start-here.md)
- [Welcome](welcome.md)
- [Execution Plan](planned-work.md)
- [Empirical Findings](empirical-findings.md)
- [Acceptance Harness](acceptance-harness.md)
- [Engineering](engineering.md)
- [Source Layout](source-layout.md)
- [Integration Surfaces](integration-surfaces.md)
- [Incremental Update Instruction Set](incremental-update-instruction-set.md)
- [Graph Tool Usage Audit](graph-tool-usage-audit.md)

## Architecture & reference

How the pieces fit and the math they run.

- [Architecture](architecture.md)
- [Interpretation Layer](interpretation-layer.md)
- [Runtime Context Graph](runtime-context-graph.md)
- [Relation Ontology](relation-ontology.md)
- [Schema Alignment](schema-alignment.md)
- [Frontend IR Strategy](frontend-ir-strategy.md)
- [Tensor Context Architecture](tensor_context_architecture.md)
- [LLM-Native Context Graph](llm-native-context-graph.md)
- [LLM-Native Platform](llm-native-platform.md)
- [Retrieval Confidence & Routing](retrieval-confidence-routing.md)
- [Mathematical Formulations](mathematical_formulations.md)
- [Adaptive Planning Math](adaptive-planning-math.md)
- [Dynamic Surface Math](dynamic_surface_math.md)

**Note on inference:** an older claim that "no inference exists" is superseded.
There is now a bounded, Horn-style **optional** compiler pass
(`platform.infer_edges`) — off by default and budget-capped. Separately, the
scanner `cpg` frontend is *not* implemented (advertised as planned, not
selectable), which is distinct from the working platform
`CpgEvidenceProvider` that emits control/data/type evidence when its pass is
requested.

## Findings — gray-box evaluation cycles

Point-in-time empirical evaluations of the tool as an agent context source.
These are historical measurements; later cycles supersede earlier numbers but
do not rewrite them.

- [Cycle 1 — Gray-box evaluation](findings/2026-07-22-graybox-eval.md)
- [Cycle 2 — "Use, then what-if" vision](findings/2026-07-22-graybox-cycle2-vision.md)
- [Cycle 3 — Cross-language extraction](findings/2026-07-22-graybox-cycle3-crosslang.md)
- [Cycle 4 — Differential re-test](findings/2026-07-23-graybox-cycle4-differential.md)
- [Cycle 5 — Instrumentation](findings/2026-07-23-graybox-cycle5-instrumentation.md)
- [Cycle 6 — Multi-language retrieval, latency, instrument trust](findings/2026-07-24-graybox-multilang-retrieval-and-latency.md)
- [100% agent efficiency — four-property analysis](findings/2026-07-24-hundred-percent-agent-efficiency.md)
- [Bug findings pass 5 — GG-NEW-001 (resolved)](findings/NEWFINDINGS5.md)
- [Redis (C) — new language stratum; extraction vs ranking separation](findings/2026-07-25-cycle5-redis-c-language-stratum.md)

## Comparisons

Positioning against adjacent systems.

- [graphgraph vs graphify](graphgraph-vs-graphify.md)
- [neo4j vs graphgraph](neo4j_vs_graphgraph.md)
- [Locus comparison](locus-comparison.md)
- [Locus comprehensive report](locus_comprehensive_report.md)

## Research & hypotheses

Exploratory writing, position papers, and ideas not yet promoted to reference.
These are hypotheses and drafts, not authoritative behavior.

- [arXiv paper — GraphGraph 2.0](arxiv_paper_graphgraph_2.0.md)
- [Towards publishable research](towards_publishable_research.md)
- [Prior-art research](prior-art-research.md)
- [Rigorous framing](rigorous-framing.md)
- [LLM internals position paper](llm_internals_position_paper.md)
- [LLM connection strategy](llm-connection-strategy.md)
- [Semantic locality & LLM efficiency](semantic-locality-and-llm-efficiency.md)
- [Semantic locality — LLM efficiency paper](semantic-locality-llm-efficiency-paper.md)
- [Advanced context engineering](advanced-context-engineering.md)
- [High-level ideas](high-level-ideas.md)
- [New helpful concepts](new-helpful-concepts.md)
- [Agent memory vs code graph](agent_memory_vs_code_graph.md)
- [Obsidian graph-model lessons](obsidian-graph-model-lessons.md)
- [Hardware/compilation analogy](hardware_compilation_analogy.md)
- [Lean4 / SymPy comparison](lean4_sympy_comparison.md)
- [kiminotes](kiminotes.md)
- [kiminotes — follow-up](kiminotes-followup.md)
- [The Path to 10/10 — prescriptive gate roadmap](findings/2026-07-24-path-to-10.md)
- [Context-graph maximization report](context_graph_maximization_report.md)
- [Optimization roadmap](optimization-roadmap.md)
- [Metric/component logic gaps](metric-component-logic-gaps.md)
- [SWE-bench evaluation protocol](swe_bench_evaluation_protocol.md)

## Archive / scratch

Working notes under `docs/notes/` are scratch and are intentionally *not*
indexed here. Do not treat them as current reference documentation.
