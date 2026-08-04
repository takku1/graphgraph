# Intermediate Representation (L1)

> **Packages:** `graph/`, `concepts/`  
> **Children:** [relation-ontology.md](./relation-ontology.md), [schema-alignment.md](./schema-alignment.md), [interpretation-layer.md](./interpretation-layer.md)  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Shared IR

## 1. Intent

Canonical **logical IR** shared by extraction, storage, retrieval, and packet encoding.

| Element | Fields (core) |
|---------|----------------|
| **Node** | `id`, `label`, `kind`, `path`, `summary`, `facts` |
| **Edge** | `source`, `target`, `type`, `weight` |
| **Policy** | `id`, `kind`, `priority`, `applies_to`, `task_tags`, `compact`, `content` |

Loose schema binding exists for **interop ingest**; native persistence is `.graphgraph/graph.gg`.

## 2. Decomposition

| Child | Role |
|-------|------|
| [relation-ontology.md](./relation-ontology.md) | Edge vocabulary, traversal strength |
| [schema-alignment.md](./schema-alignment.md) | External tool schemas → IR |
| [interpretation-layer.md](./interpretation-layer.md) | Typed interpretation / concepts |
| Graph operations / traversal | `graph/operations.py`, `traversal.py`, `coupling.py` (research coupling separate) |

## 3. Interfaces

| | |
|--|--|
| **Inputs** | Frontend emissions, ingest mappings, optional inferred edges |
| **Outputs** | In-memory `Graph` for retrieval; serializable store payload |
| **Non-goals** | Prompt-facing encoding (that is context-packets) |

## 4. Invariants

- **[Ubiquitous]** Complete materialization consumers SHALL use in-memory IR; binary store is persistence optimization.
- **[Conditional]** IF an ontology relation has zero traversal strength THEN expansion SHALL hard-block it.
- **[Ubiquitous]** Optional `infer_edges` SHALL be off by default and budget-capped (distinct from unimplemented scanner `cpg` mode).

## 5. Open work

Ontology ranking under OW-Q04-*; inference pass documentation under platform.
