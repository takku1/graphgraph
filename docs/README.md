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
- [Execution Plan — active P-series first](planned-work.md)
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
- [Receiver Type Resolution](receiver-type-resolution.md)
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

## Operational findings — gray-box evaluation cycles

Current empirical evaluation of the tool as an agent context source. It is
self-contained and supersedes the removed cycle drafts.

- [Comprehensive gray-box evaluation after updates](findings/2026-07-27-graybox-comprehensive.md)
- [The influence field, not the cover formula, is the failing stage](findings/2026-07-29-influence-field-coupling.md)
- [Fixing the field did not rescue the cover — it raised the baseline](findings/2026-07-30-recoupled-cover-verdicts.md)
- [The field has no measurable leverage on production ranking](findings/2026-07-30-coupling-has-no-production-leverage.md)
- [Gray-box evaluation across six external repositories](findings/2026-07-30-graybox-multilang-critical.md)
- [Critical gray-box ceiling evaluation and reproducible task fixtures](findings/2026-07-30-critical-graybox-graph-tool-ceiling.md)
- [P02 typed-fact held-out receiver comparison](findings/2026-07-31-p02-typed-fact-heldout.md)
- [Q02-C persistent type facts and affected-key re-join](findings/2026-07-31-q02c-persistent-type-facts.md)
- [Q02-D JavaScript structural receiver owners](findings/2026-07-31-q02d-js-structural-owners.md)
- [The token proxy was uncalibrated, and it was not a constant offset](findings/2026-07-30-token-proxy-recalibration.md)

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
- [Context-graph maximization report](context_graph_maximization_report.md)
- [Optimization roadmap](optimization-roadmap.md)
- [Metric/component logic gaps](metric-component-logic-gaps.md)
- [SWE-bench evaluation protocol](swe_bench_evaluation_protocol.md)
- [Global project attention under finite compute](global_project_attention_research_proposal.md)
- [Context-system research tournament](context_system_research_tournament.md)
  - [executable claim ledger](../eval/context-system-research.json)
  - [Phase 0 oracle](../benchmarks/context_graph/global_attention_phase0.py)
  - [Phase 1 equal-token transfer screen](../benchmarks/context_graph/global_attention_phase1.py)

## Archive / scratch

Working notes under `docs/notes/` are scratch and are intentionally *not*
indexed here. Do not treat them as current reference documentation.
