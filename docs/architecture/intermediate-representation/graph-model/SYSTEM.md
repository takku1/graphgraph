# Graph Record Model and Traversal (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Define the node, edge, and policy records, the relation ontology that says how far each edge type may be walked, and the traversal and coupling views built over them; does not normalize terminology, detect concepts, or serialize the records to disk.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One record set whose traversal and coupling views share its relation ontology.

## 3. Interface Contracts

- **Inputs:** `extracted_nodes`, `extracted_edges`
- **Outputs:** `graph_ir`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF an ontology relation has zero traversal strength THEN expansion SHALL hard-block it, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** Optional `infer_edges` SHALL be off by default and budget-capped.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Inferred edges SHALL carry provenance that distinguishes them from extracted edges.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Re-orienting a graph for a coupling view SHALL return a new graph rather than mutate the source, so a field experiment cannot silently change production traversal.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-GM-001:** The IR is the logical model; the store is a serialization of it. Three record types is the whole vocabulary, and the value is discipline about what may be added to them.
- **ADR-GM-002:** Traversal strength lives in the ontology, not in the traversal loop. An unknown edge type is retained as data but carries no strength, so a new extractor cannot widen expansion by accident.
- **ADR-GM-003:** Edge coupling is exchanged as its own stage, memoized on the source graph's mutation revision, so the orientation choice and the representation built on top of it can be measured independently.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/graph/__init__.py`, `src/graphgraph/graph/core.py`, `src/graphgraph/graph/coupling.py`, `src/graphgraph/graph/ontology.py`, `src/graphgraph/graph/operations.py`, `src/graphgraph/graph/traversal.py`
- **Test Surface Seam:** `tests/test_graph_core.py`, `tests/test_graph_coupling.py`, `tests/test_graph_snapshot.py`

## 7. Measurement Seams

- **Primary Metric:** `expand_context_ms` (median of the timed expansions in the component gate, `direction: lower`)
- **Evaluation Gate Path:** `components/intermediate-representation/measure.sh`
- **Correctness Backpressure:** `components/intermediate-representation/checks.sh`
- **Telemetry Surface:** node/edge/policy counts, relation-family mix, canonical snapshot hash.
- **Branching Policy:** isolated candidate; byte-identical canonical dump is the refactor gate.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — three record types plus a relation table. The value is vocabulary discipline, not the data structure; NetworkX would still need every domain field layered on top.
- **Selected:** in-repo `Graph` on Python 3.10, stdlib only
- **Standard / protocol:** none native; JSON-shaped schemas accepted on ingest
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | NetworkX 3.x | Large dependency for narrow traversals; domain fields still required. |
  | RDF / property-graph standards | Vocabulary far wider than this ontology; would push toward a triple store. |
  | Adopting an external tool schema natively | Couples the IR to another project's release cycle. |

- **Fit gap:** the record model carries no query language; intent lives in Query Planning.
- **Seam:** `src/graphgraph/graph/operations.py`
- **Exit cost:** HIGH — every subsystem reads these records.
- **Cost model:** in-process memory; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unknown edge type is retained but carries no traversal strength.
- **Open questions:** OW-Q04
