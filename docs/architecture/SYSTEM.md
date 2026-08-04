# GraphGraph — System Architecture (L0)

## 1. Intent

GraphGraph is an **empirical system for minimum-cost context representation**: extract a program/document **intermediate representation (IR)**, **retrieve** a task-local subgraph, **encode** an LLM-facing **context packet**, and **mechanically validate** that packet before any optional live-model scoring.

Core research question:

> What is the cheapest context representation an LLM can reliably interpret?

## 2. Pipeline (textbook stages)

```text
Corpus extraction (static analysis frontends)
  → Intermediate representation (nodes, edges, facts, policies)
  → Native graph store (persistent .gg)
  → Information retrieval & query planning
  → Context-packet encoding
  → Scoped constraint / policy selection
  → Mechanical validation
  → (Optional) external model scoring
```

External graph tools are **ingestion interoperability** only; they are not the runtime core.

## 3. Subsystem decomposition

| Subsystem | Academic framing | Package (implementation; docs-only map) | Spec |
|-----------|------------------|----------------------------------------|------|
| Static analysis / extraction | Language frontends, AST, scope, typed facts | `scanner/`, `scanner/frontends/` | [static-analysis/SYSTEM.md](./static-analysis/SYSTEM.md) |
| Intermediate representation | Graph IR, ontology, schema | `graph/`, `concepts/` | [intermediate-representation/SYSTEM.md](./intermediate-representation/SYSTEM.md) |
| Persistent storage | Native store, incremental update, sectioned layout | `storage/`, `runtime/`, `io/` | [storage/SYSTEM.md](./storage/SYSTEM.md) |
| Information retrieval | Anchors, expansion, ranking, facets, selection | `retrieval/` | [information-retrieval/SYSTEM.md](./information-retrieval/SYSTEM.md) |
| Query planning | Query classes, budgets, routing, packet choice | `planning/` | [query-planning/SYSTEM.md](./query-planning/SYSTEM.md) |
| Context-packet encoding | Serialization formats, validation | `packets/` | [context-packets/SYSTEM.md](./context-packets/SYSTEM.md) |
| Application services | Query orchestration, atlas, freshness, snippets | `services/` | [application-services/SYSTEM.md](./application-services/SYSTEM.md) |
| Platform & evidence | CPG evidence, inference, temporal, memory | `platform/` | [platform/SYSTEM.md](./platform/SYSTEM.md) |
| Agent interfaces | CLI cold-start vs resident MCP transport | `cli/`, `mcp/` | [agent-interfaces/SYSTEM.md](./agent-interfaces/SYSTEM.md) |
| Project atlas | Orientation, navigation benchmark, project memory | `services/project_atlas`, `analysis/navigation` | [project-atlas/SYSTEM.md](./project-atlas/SYSTEM.md) |

Package inventory narrative: [package-structure.md](./package-structure.md).  
End-to-end narrative (legacy detail): [system-architecture.md](./system-architecture.md).

## 4. Interface contracts (L0)

| Direction | Artifacts |
|-----------|-----------|
| **Inputs** | Source/docs corpus, natural-language or typed queries, optional external graphs for ingest |
| **Outputs** | Context packets, control receipts (JSON), store under `.graphgraph/`, validation reports |
| **Non-goals** | Replacing a full compiler; using model-judge scores as sole correctness proof |

## 5. Invariants (EARS-style)

- **[Ubiquitous]** The system SHALL treat the in-memory graph IR as the logical model and the native `.gg` store as the default persistent form.
- **[Ubiquitous]** Incomplete product and research work SHALL be tracked only in `docs/open-work.md` (not parallel root checklists).
- **[Conditional]** IF a packet fails mechanical validation THEN THE SYSTEM SHALL NOT present it as a successful structural answer.
- **[Conditional]** IF a claim is about external model answer quality THEN THE SYSTEM SHALL require explicit live scoring; retrieval shape alone is insufficient ([evidence-standards.md](../guides/evidence-standards.md)).
- **[Event-driven]** WHEN transport is a one-shot CLI process THE SYSTEM SHALL report cold-start latency separately from resident retrieval latency.

## 6. Architectural decisions

- **ADR-001:** Prefer deterministic extraction; score any LLM extraction separately.
- **ADR-002:** Resident MCP process is the interactive transport; CLI is cold-start / scripting.
- **ADR-003:** Academic terminology in living docs; informal aliases documented in [archive/README.md](../guides/terminology.md).
- **ADR-004:** Expand a subsystem node only when interface seams justify it (recursive modular decomposition).

## 7. Open work

See [open-work.md](../open-work.md). Do not duplicate scorecards here.
