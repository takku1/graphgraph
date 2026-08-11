# GraphGraph Documentation

Empirical system for:

> What is the cheapest **context representation** an LLM can reliably interpret?

**Pipeline:** corpus extraction → intermediate representation → native store → information retrieval & query planning → context-packet encoding → mechanical validation → (optional) live model scoring.

| Entry | Path |
|-------|------|
| **Index (this file)** | `docs/README.md` |
| **Incomplete work (sole checklist)** | [open-work.md](open-work.md) |
| **Getting started** | [guides/getting-started.md](guides/getting-started.md) |
| **L0 architecture** | [architecture/SYSTEM.md](architecture/SYSTEM.md) |
| **Evidence standards** | [guides/evidence-standards.md](guides/evidence-standards.md) |
| **Gray-box evidence records** | [evaluation/graybox-cycles/](evaluation/graybox-cycles/README.md) |

Superseded pre-redesign documents were retired; their history is in git.

---

## Guides (operations)

| Document | Role |
|----------|------|
| [guides/getting-started.md](guides/getting-started.md) | Install → doctor → scan → context |
| [guides/overview.md](guides/overview.md) | Agent/human bootstrap |
| [guides/evidence-standards.md](guides/evidence-standards.md) | Claim promotion / evidence bar |
| [guides/engineering-practices.md](guides/engineering-practices.md) | Engineering conventions |
| [guides/integration-interfaces.md](guides/integration-interfaces.md) | CLI / MCP / skill surfaces |
| [guides/terminology.md](guides/terminology.md) | Academic ↔ legacy terms, doc conventions, rename map |

---

## Architecture (recursive decomposition)

| Path | Academic framing |
|------|------------------|
| [architecture/SYSTEM.md](architecture/SYSTEM.md) | **L0** system map |
| [architecture/system-architecture.md](architecture/system-architecture.md) | End-to-end narrative (latency, store, query classes) |
| [architecture/package-structure.md](architecture/package-structure.md) | Package ownership map |
| [architecture/static-analysis/](architecture/static-analysis/) | Corpus extraction, language frontends, receiver-type inference |
| [architecture/intermediate-representation/](architecture/intermediate-representation/) | Graph IR, ontology, schema, interpretation |
| [architecture/storage/](architecture/storage/) | Native store, incremental update |
| [architecture/information-retrieval/](architecture/information-retrieval/) | Anchors, expansion, ranking, confidence |
| [architecture/query-planning/](architecture/query-planning/) | Query classes, budgets, routing |
| [architecture/context-packets/](architecture/context-packets/) | Packet encodings & validation |
| [architecture/application-services/](architecture/application-services/) | Query/context orchestration |
| [architecture/platform/](architecture/platform/) | Optional evidence / CPG / inference |
| [architecture/agent-interfaces/](architecture/agent-interfaces/) | Cold CLI vs resident MCP |
| [architecture/project-atlas/](architecture/project-atlas/) | Orientation, memory, navigation benchmark |
| [architecture/acceptance/](architecture/acceptance/SYSTEM.md) | Black-box acceptance & qualification |
| [architecture/evaluation-analysis/](architecture/evaluation-analysis/SYSTEM.md) | Calibration, authority, eval protocol |
| [architecture/research/](architecture/research/SYSTEM.md) | Unpromoted research candidates |
| [architecture/representation/](architecture/representation/SYSTEM.md) | Project representation (flat vs hybrid) |
| [architecture/runtime-context-model.md](architecture/runtime-context-model.md) | Runtime context model |

**Terminology:** *scan* → corpus extraction; *packet* → context packet; *blast radius* → change-impact neighborhood; *anchors* → retrieval anchors. Full map: [guides/terminology.md](guides/terminology.md).

---

## Evaluation

| Document | Role |
|----------|------|
| [evaluation/README.md](evaluation/README.md) | Evaluation index |
| [evaluation/empirical-evaluation.md](evaluation/empirical-evaluation.md) | Measured results (through 2026-07-19) |
| [evaluation/graybox-cycles/](evaluation/graybox-cycles/README.md) | Consolidated gray-box measurement ledger, corpora, and current receipts through 2026-08-08 |
| [evaluation/acceptance-evaluation-harness.md](evaluation/acceptance-evaluation-harness.md) | Acceptance harness |
| [evaluation/defect-ledger.md](evaluation/defect-ledger.md) | Defects & resolutions |
| [evaluation/metric-validity-gaps.md](evaluation/metric-validity-gaps.md) | Metric validity gaps |
| [evaluation/external-tool-interoperability-audit.md](evaluation/external-tool-interoperability-audit.md) | External tool audit |
| [evaluation/swe-bench-protocol.md](evaluation/swe-bench-protocol.md) | SWE-bench protocol |

---

## Research

| Document | Role |
|----------|------|
| [research/README.md](research/README.md) | Research index |
| [research/related-work.md](research/related-work.md) | Prior art |
| [research/optimization-research-agenda.md](research/optimization-research-agenda.md) | Optimization agenda (not a checklist) |
| [research/publication-roadmap.md](research/publication-roadmap.md) | Publication path |
| [research/manuscript-graphgraph-2.md](research/manuscript-graphgraph-2.md) | Manuscript draft |
| [research/comparisons/](research/comparisons/) | Neo4j, Graphify, Locus, … |
| (see research README for full list) | Hypotheses, math, surveys |

Incomplete product/research **tasks** live only in [open-work.md](open-work.md).

---
