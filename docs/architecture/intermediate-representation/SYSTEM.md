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

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Consumers needing complete materialization SHALL use the in-memory IR; the binary store is a persistence optimization.
  - `EvidenceStage: Observed`.
- **[Conditional]** IF an ontology relation has zero traversal strength THEN expansion SHALL hard-block it.
  - `EvidenceStage: Sampled` — `tests/test_graph_core.py`.
- **[Ubiquitous]** Optional `infer_edges` SHALL be off by default and budget-capped.
  - `EvidenceStage: Observed` — distinct from the *unimplemented* scanner `cpg` mode; see [platform](../platform/SYSTEM.md).
- **[Ubiquitous]** Inferred edges SHALL carry provenance distinguishing them from extracted edges.
  - `EvidenceStage: Observed` — same rule as runtime `observed_calls` in [static-analysis](../static-analysis/SYSTEM.md).

## 5. ADRs

- **ADR-IR-001:** The IR is the logical model; the store is a serialization of it. Any consumer that needs the whole graph reads the IR, so the store's layout stays free to change for performance.
- **ADR-IR-002:** External schemas bind loosely and only on ingest. Interop is an import concern; making the native IR conform to a foreign schema would put an external project's vocabulary on the hot path.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `graph/` (6 modules): `operations.py`, `traversal.py`, `coupling.py`; `concepts/` (5 modules) |
| **Test surface** | `tests/test_graph_core.py`, `tests/test_graph_coupling.py`, `tests/test_concepts.py`, `tests/test_scope_graph.py` |
| **Snapshot seam** | `tests/test_graph_snapshot.py` plus `scripts/graph_snapshot.py` — the canonical dump used as the determinism gate |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Traversal cost per expansion hop (`direction: lower`) |
| **Structural gate** | Byte-identical canonical dump across a refactor — the gate that made the scan and retrieval optimizations safe |
| **Ontology metric** | Edge-type contribution to retrieval quality, ranked under OW-Q04-* |
| **Caution** | `graph/coupling.py` is production graph coupling; the research coupling line (influence field) is separate and [did not survive production measurement](../../evaluation/graybox-cycles/README.md#influence-field-experiment) |

## 8. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo `Graph` (nodes, edges, policies) — plain Python data structures, stdlib only
- **Standard / protocol:** none native; JSON-shaped schemas accepted on ingest
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | NetworkX | A large dependency for traversals this project implements narrowly, and its generic node/edge model would still need the domain fields layered on top |
  | RDF / property-graph standards | Real interop value, but the vocabulary is far wider than the ontology here and would push toward a triple store; kept as an ingest mapping instead |
  | Adopting an external tool's schema natively | Would couple the IR to another project's release cycle; see [schema-alignment.md](./schema-alignment.md) for the ingest-side treatment |

- **Fit gap:** the IR carries no query language. Expression of intent lives in [query-planning](../query-planning/SYSTEM.md).
- **BUILD justification:** genuinely trivial and stable — the IR is three record types; its value is the vocabulary discipline in [relation-ontology.md](./relation-ontology.md), not the data structure.
- **Seam:** `graph/operations.py`
- **Exit cost:** **HIGH** — every subsystem reads the IR; it is the widest internal contract in the system.
- **Operational owner:** us
- **Failure mode:** an unknown edge type is retained but carries no traversal strength, so it cannot silently widen expansion.
- **Open questions:** ontology ranking under OW-Q04-* — [open-work.md](../../open-work.md)
