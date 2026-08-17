# Intermediate Representation (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Hold the canonical in-memory graph IR shared by extraction, storage, retrieval, and packet encoding; does not own prompt-facing encodings or a query language.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Three record types plus traversal and ontology policy.

## 3. Interface Contracts

- **Inputs:** `extracted_nodes`, `extracted_edges`
- **Outputs:** `graph_ir`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Consumers that need complete materialization SHALL use the in-memory IR; the binary store is a persistence optimization.
  - `EvidenceStage:` Observed
- **[Conditional]** IF an ontology relation has zero traversal strength THEN expansion SHALL hard-block it, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Optional `infer_edges` SHALL be off by default and budget-capped.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Inferred edges SHALL carry provenance that distinguishes them from extracted edges.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-GIR-001:** The IR is the logical model; the store is a serialization of it.
- **ADR-GIR-002:** External schemas bind loosely and only on ingest.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/concepts/__init__.py`, `src/graphgraph/concepts/doccode.py`, `src/graphgraph/concepts/health.py`, `src/graphgraph/concepts/registry.py`, `src/graphgraph/concepts/terms.py`, `src/graphgraph/graph/__init__.py`, `src/graphgraph/graph/core.py`, `src/graphgraph/graph/coupling.py`, `src/graphgraph/graph/ontology.py`, `src/graphgraph/graph/operations.py`, `src/graphgraph/graph/traversal.py`
- **Test Surface Seam:** `tests/test_concepts.py`, `tests/test_graph_core.py`, `tests/test_graph_coupling.py`, `tests/test_graph_snapshot.py`

## 7. Measurement Seams

- **Primary Metric:** `traversal_cost_per_hop` (observation, `direction: lower`)
- **Evaluation Gate Path:** `components/intermediate-representation/measure.sh`
- **Correctness Backpressure:** `components/intermediate-representation/checks.sh`
- **Telemetry Surface:** node/edge/policy counts and canonical snapshot hash.
- **Branching Policy:** isolated candidate; byte-identical canonical dump is the refactor gate.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — three record types. The value is vocabulary discipline, not the data structure. NetworkX would still need the domain fields layered on top.
- **Selected:** in-repo `Graph` on Python 3.10, stdlib only
- **Standard / protocol:** none native; JSON-shaped schemas accepted on ingest
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | NetworkX 3.x | Large dependency for narrow traversals; domain fields still required. |
  | RDF / property-graph standards | Vocabulary far wider than this ontology; would push toward a triple store. |
  | Adopting an external tool schema natively | Couples the IR to another project's release cycle. |

- **Fit gap:** the IR carries no query language; intent lives in Query Planning.
- **Seam:** `src/graphgraph/graph/operations.py`
- **Exit cost:** HIGH — every subsystem reads the IR.
- **Cost model:** in-process memory; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unknown edge type is retained but carries no traversal strength.
- **Open questions:** OW-Q04
