# Packet Target Catalog (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Declare every advertised packet target exactly once — its renderer, its validator, its token cost model, and its published schema — behind lazy references that keep importing the catalog cheap; does not render text, decide whether a rendered packet is valid, or count its tokens.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One declaration table plus the lazy public facade that reads it.

## 3. Interface Contracts

- **Inputs:** `query_plan`
- **Outputs:** `target_spec`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A target SHALL name its renderer and validator by lazy reference, so importing the catalog does not import a renderer.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The published target table and schema SHALL be derived from the same declarations the runtime resolves, not maintained as a parallel list, as checked by `tests/test_public_contracts.py`.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-TC-001:** Target behavior is registered atomically in one cold-start-safe catalog. A format that exists in a renderer but not in the catalog is not a format; that is what makes "unadvertised" enforceable rather than aspirational.
- **ADR-TC-002:** Declarations hold `FunctionRef` module/name pairs rather than imported callables, so the catalog is importable on the cold path without pulling renderers, validators, or the estimator into the process.
- **ADR-TC-003:** The token cost model travels with the target declaration and carries its own `calibrated` flag and fit provenance, so a planner can tell a fitted surface from a placeholder without consulting a second table.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/packet_targets.py`, `src/graphgraph/packets/__init__.py`
- **Test Surface Seam:** `tests/test_public_contracts.py`, `tests/test_packets.py`

## 7. Measurement Seams

- **Primary Metric:** `packet_token_units` (summed over the gate's query set at fixed recall, `direction: lower`)
- **Evaluation Gate Path:** `components/context-packets/measure.sh`
- **Correctness Backpressure:** `components/context-packets/checks.sh`
- **Telemetry Surface:** target identity, declared renderer/validator references, cost-model provenance and calibration flag.
- **Branching Policy:** isolated candidate; the dead-format guard must stay green — a declared target with no working round trip fails the branch.
- **Known granularity gap:** this leaf currently shares the component-level `packet_token_units` gate; catalog cold-start import cost is asserted structurally rather than measured. Recorded as an open granularity gap rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — a frozen table of named tuples. Every plugin or entry-point registry considered would add import machinery and startup cost for a closed format set this repository owns end to end.
- **Selected:** in-repo `TargetSpec` catalog on Python 3.10, stdlib only
- **Standard / protocol:** none — the packet is a prompt-boundary format, not a wire format
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | `importlib.metadata` entry points | Startup scan and third-party registration for a closed, in-repo format set. |
  | A plugin class hierarchy | Imports every renderer to enumerate targets, which is the cold-start cost the lazy reference exists to avoid. |
  | A hand-maintained docs table | Drifts from the runtime; the published table is generated from the declarations instead. |

- **Fit gap:** third-party formats cannot register; adding one is a repository change by design.
- **Seam:** `src/graphgraph/packet_targets.py`
- **Exit cost:** MEDIUM — every compiler surface resolves targets through this table.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unknown target name raises rather than silently rendering a default format.
- **Open questions:** OW-Q05
