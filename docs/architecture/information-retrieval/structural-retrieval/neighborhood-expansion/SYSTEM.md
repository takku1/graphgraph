# Neighborhood Expansion (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Walk structural edges outward from seated anchors under a hop bound to assemble the candidate neighborhood; does not rank anchors, apply the token budget, or score result quality.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One bounded traversal phase over graph relations and subsystem grouping.

## 3. Interface Contracts

- **Inputs:** `facet_reservations`
- **Outputs:** `candidate_neighborhood`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Expansion SHALL follow declared structural edges rather than lexical similarity, so the neighborhood remains a dependence cone.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Traversal SHALL stop at the planned hop bound, as checked by `tests/test_relations.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN a neighbor is omitted by the hop bound THE SYSTEM SHALL record the omission count rather than presenting the neighborhood as complete.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a caller requests a subsystem view THEN THE SYSTEM SHALL group by declared package structure rather than by ranking order, as checked by `tests/test_retrieval_subsystems.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-NE-001:** Bounded k-hop expansion, not a whole-program closure. An unbounded cone is both unaffordable in tokens and less useful than a task-local one.
- **ADR-NE-002:** Omitted neighbors are counted and reported. Silence about truncation is what turns a bounded answer into a misleading one.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/expansion.py`, `src/graphgraph/retrieval/relations.py`, `src/graphgraph/retrieval/subsystems.py`
- **Test Surface Seam:** `tests/test_relations.py`, `tests/test_retrieval_subsystems.py`, `tests/test_retrieval.py`

## 7. Measurement Seams

- **Primary Metric:** `expand_context_ms` (`direction: lower`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** hop depth reached, expanded node count, omitted-neighbor counts.
- **Branching Policy:** isolated candidate; expansion may not grow the packet without a recall gain.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — a budgeted, structurally constrained dependence cone is the system's core contribution; a graph library traversal would still need every bound, receipt, and omission count written here.
- **Selected:** in-repo expansion over the native graph IR on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | NetworkX traversal | Extra dependency and node-object overhead over an in-memory IR that already indexes edges. |
  | Graph-database traversal (Cypher) | Server dependency inside the cold-start budget. |
  | Group Steiner Tree / prize-collecting connected subgraph | The correct formalism for "smallest connected subgraph touching every facet group" — what k-hop expansion approximates without saying so. NP-hard with polylogarithmic approximations available. Not adopted yet: ranking-affecting, and the hop bound is currently also serving as the latency bound. Tracked as `RF-04`. |

- **Fit gap:** expansion treats all edge types as equally traversable; typed edge weighting is unmeasured.
- **Seam:** `src/graphgraph/retrieval/expansion.py`
- **Exit cost:** MEDIUM — traversal is isolated behind the phase record.
- **Cost model:** in-process CPU.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an empty neighborhood yields the anchor set alone rather than an error.
- **Open questions:** OW-Q02
