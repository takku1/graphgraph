# Cold Contract Authority (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Provide parser-safe names and defaults from one cold-import authority; does not own runtime routing, representation compilation, compiler-pass execution, or scanner behavior.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One import-light catalog consumed by CLI construction and runtime owners.

## 3. Interface Contracts

- **Inputs:** `source_corpus`
- **Outputs:** `cold_catalog`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Each transport-visible name or default SHALL have one authoritative definition, as checked by `tests/test_surface_constants.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN the CLI parser is constructed THE SYSTEM SHALL NOT import planning, representation, scanner, retrieval, platform, `pathspec`, or `asyncio`, as checked by `tests/test_surface_constants.py`.
  - `EvidenceStage:` Sampled
- **[Conditional]** IF a runtime catalog adds an item THEN the parser SHALL expose it without a separately edited compatibility tuple, as checked by `tests/test_surface_constants.py`.
  - `EvidenceStage:` Sampled

## 5. Architectural Decisions (ADRs)

- **ADR-CC-001:** Follow the cold atomic-catalog pattern established by `packet_targets.py`; runtime modules consume cold contracts rather than mirror them.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/surface.py`, `src/graphgraph/cli/parser.py`.
- **Test Surface Seam:** `tests/test_surface_constants.py`, `tests/test_module_boundaries.py`, `tests/test_public_contracts.py`.

## 7. Measurement Seams

- **Primary Metric:** `cli_cold_start_ms` (no regression, `direction: lower`)
- **Evaluation Gate Path:** `components/agent-interfaces/measure.sh`
- **Correctness Backpressure:** `components/agent-interfaces/checks.sh`
- **Telemetry Surface:** resident/cold timing JSON from the agent-interface harness.
- **Branching Policy:** land as one catalog migration; delete compatibility copies rather than wrapping them.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Trivial and stable custom contract; catalog semantics are GraphGraph-specific and directly preserve the cold-start differentiator.
- **Selected:** immutable Python 3.10 dataclasses and tuples in an import-light in-repo catalog
- **Standard / protocol:** Python import semantics and the existing public schema contracts
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Keep `surface.py` mirrors plus parity tests | Preserves two authorities; drift becomes a test-time discovery. |
  | Import Linter 2.13 | Can forbid eager imports but cannot make duplicated values atomic. |
  | LibCST 1.8.6 codemod | Useful for repeating migrations; this is one small catalog. |

- **Fit gap:** Python still executes the package `__init__` before submodules, so the authority must remain at an import-light seam.
- **Seam:** `src/graphgraph/surface.py`
- **Exit cost:** LOW — internal imports plus public-name parity tests.
- **Cost model:** no added dependency; cold import must remain within the agent-interface tolerance.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an eager dependency fails `ParserImportWeightTest`; schema drift fails public-contract tests.
- **Open questions:** none
