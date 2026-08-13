# Cold Contract Authority (L2)

## 1. System Intent & Responsibility

Provide parser-safe names and defaults from one cold-import authority; does not
own runtime routing, representation compilation, compiler-pass execution, or
scanner behavior.

## 2. Sub-System Decomposition

Atomic leaf (atomic build; implemented by T-A11).

## 3. Interface Contracts

- **Inputs:** query-class, representation, compiler-pass, and scan-limit contract definitions.
- **Outputs:** immutable cold catalogs consumed by CLI construction and their owning runtime subsystems.

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Each transport-visible name or default SHALL have one authoritative definition.
  - `EvidenceStage: Sampled` — atomic cold contract completeness and parser projection are covered by `tests/test_surface_constants.py`.
- **[Event-driven]** WHEN the CLI parser is constructed THE SYSTEM SHALL NOT import planning, representation, scanner, retrieval, platform, `pathspec`, or `asyncio`.
  - `EvidenceStage: Sampled` — `ParserImportWeightTest`.
- **[Conditional]** IF a runtime catalog adds an item THEN the parser SHALL expose it without a separately edited compatibility tuple.
  - `EvidenceStage: Sampled` — query classes and compiler passes project from their cold contract catalogs.

## 5. Architectural Decisions (ADRs)

- **ADR-CC-001:** Follow the cold atomic-catalog pattern established by `packet_targets.py`; runtime modules consume cold contracts rather than mirror them.

## 6. Leaf Execution & Test Seam

- **Implementation File(s):** `src/graphgraph/surface.py`, `planning/routing.py`, `representation/`, `platform/compiler.py`, `scanner/files.py`, `cli/parser.py`.
- **Test Surface Seam:** `tests/test_surface_constants.py`, `tests/test_module_boundaries.py`, `tests/test_public_contracts.py`.

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (no regression, `direction: lower`).
- **Harness Path:** `components/agent-interfaces/measure.sh`.
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh` plus `components/maintainability/checks.sh`.
- **Telemetry Surface:** resident/cold timing JSON from the agent-interface harness.
- **Branching Policy:** land as one catalog migration; delete compatibility copies rather than wrapping them.

## 8. Technology Resolution

- **Decision class:** BUILD.
- **Selected:** immutable Python 3.10 dataclasses/tuples in an import-light in-repo catalog.
- **Standard / protocol:** Python import semantics and the existing public schema contracts.
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Keep `surface.py` mirrors plus parity tests | Preserves two authorities and makes drift a test-time discovery rather than an impossible state. |
  | Import Linter 2.13 | Can forbid eager imports but cannot make duplicated enum/default values atomic. |
  | LibCST 1.8.6 codemod | Useful for repeating migrations; this is one small catalog migration and the new dependency would remain after its value ended. |

- **Justification:** trivial and stable custom contract; catalog semantics are GraphGraph-specific and directly preserve its cold-start differentiator.
- **Fit gap:** Python still executes the package `__init__` before submodules, so the authority must remain at an import-light package seam.
- **Seam:** replacement cold catalog imported by `cli/parser.py` and runtime owners.
- **Exit cost:** LOW — internal imports plus public-name parity tests.
- **Cost model:** no added dependency; cold import must remain within the current agent-interface tolerance.
- **Liability transferred:** none.
- **Operational owner:** us.
- **Failure mode:** an eager dependency fails `ParserImportWeightTest`; schema drift fails public-contract tests.
- **Open questions:** none.
