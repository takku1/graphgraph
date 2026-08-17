# Project Representation (L1)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Shape a whole project before a packet is rendered — flat by default, or an opt-in multiresolution candidate; does not own packet encoding or which nodes are retrieved.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One versioned hybrid candidate beside the flat default.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `query_text`
- **Outputs:** `compiled_representation`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** The default representation SHALL remain `flat` until a candidate shows a measured win.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a representation is requested for an unsupported packet format THEN the request SHALL be rejected rather than silently downgraded, as checked by `tests/test_representation_hybrid.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A compiled representation SHALL carry its version.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Multiresolution coarsening SHALL preserve identity: a coarsened cell names what it summarizes, as checked by `tests/test_representation_hybrid.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-RP-001:** Shipped but not default. Promotion requires a measured token win with no recall regression.
- **ADR-RP-002:** The representation is versioned by name (`hybrid_reserve_v1`).

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/representation/__init__.py`, `src/graphgraph/representation/hybrid.py`
- **Test Surface Seam:** `tests/test_representation_hybrid.py`.

## 7. Measurement Seams

- **Primary Metric:** `hybrid_vs_flat_token_ratio` (`direction: lower`)
- **Evaluation Gate Path:** `components/representation/measure.sh`
- **Correctness Backpressure:** `components/representation/checks.sh`
- **Telemetry Surface:** representation version, token ratio per query class.
- **Branching Policy:** isolated candidate; the current measured ratio is 2.65–3.75× vs flat and cannot be claimed cheaper (RF-01).

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — how a project is shaped before rendering is a core research question, not a commodity.
- **Selected:** in-repo `hybrid.py` on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Flat selection only | The current default and the baseline to beat. |
  | GraphRAG-style community summarization | Optimizes global coverage; this system's queries are local and token-costed. |
  | LLM-generated hierarchy | A model call on the compile path; nondeterministic and unversionable. |

- **Fit gap:** extra tokens are expected by construction; whether they buy answer quality is unmeasured (RF-01).
- **Seam:** `src/graphgraph/representation/__init__.py`
- **Exit cost:** LOW — opt-in; removing it restores `flat`.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unsupported combination is rejected at request time.
- **Open questions:** RF-01
