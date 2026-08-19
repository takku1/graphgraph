# Store Discovery and Interchange (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Locate the store a caller should read and decode any supported on-disk revision into graph IR; does not define the native section layout, publish build state, or promote a legacy format to active.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One format-dispatching read path over the candidate store set.

## 3. Interface Contracts

- **Inputs:** `active_build`
- **Outputs:** `loaded_graph`, `format_provenance`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Active store discovery SHALL prefer native `.gg` over legacy interchange.
  - `EvidenceStage:` Observed
- **[Conditional]** IF only a legacy `ggb2` / `ggb3` / JSON revision is present THEN THE SYSTEM SHALL load it for reading without promoting it to the active store.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A decoded graph SHALL carry the format it came from so a caller can distinguish native from interchange provenance, as checked by `tests/test_io.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-SD-001:** Legacy `ggb2` / `ggb3` / JSON load but are never auto-selected as the active store, so an old revision left in a workspace cannot silently become the answer.
- **ADR-SD-002:** Discovery returns a selection plus its provenance rather than a bare graph, because "which store answered" is a correctness fact for freshness reporting.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/io/__init__.py`, `src/graphgraph/io/cache.py`, `src/graphgraph/io/core.py`, `src/graphgraph/io/discovery.py`
- **Test Surface Seam:** `tests/test_io.py`

## 7. Measurement Seams

- **Primary Metric:** `store_load_ms` (target measured on the cold CLI path, `direction: lower`)
- **Evaluation Gate Path:** `components/storage/measure.sh`
- **Correctness Backpressure:** `components/storage/checks.sh`
- **Telemetry Surface:** selected store path, detected format, candidate count.
- **Branching Policy:** isolated candidate; storage checks must pass.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — format dispatch over an in-repo format set is a few branches, and every candidate library would import a store engine this project deliberately does not run.
- **Selected:** in-repo `load_any` dispatch on Python 3.10
- **Standard / protocol:** JSON for interchange only
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | A plugin/entry-point registry | Indirection and import cost for a closed format set owned by this repository. |
  | Always-JSON interchange | Loses the sectioned read that the cold-start budget depends on. |

- **Fit gap:** single-project discovery. Multi-repository federation is a retrieval concern, not a discovery one.
- **Seam:** `src/graphgraph/io/discovery.py`
- **Exit cost:** LOW — read-side dispatch; adding or retiring a format touches one module.
- **Cost model:** local disk; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** discovery reports no active graph rather than guessing a stale candidate.
- **Open questions:** OW-AC-02
