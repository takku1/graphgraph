# Benchmark Probes (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Provide small reproducible probes that answer one measurement question about a graph; does not hold claims, promote candidates, or gate a component.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** Standalone probes with no production caller.

## 3. Interface Contracts

- **Inputs:** `graph_ir`
- **Outputs:** `probe_readings`

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** A probe SHALL report the sample count and the graph revision it measured, so a reading is attributable to a specific state.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Probes SHALL NOT be imported by production code paths.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a probe reading is quoted as evidence THEN it SHALL name the machine it was taken on, because baselines here are machine-local.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-BP-001:** A probe is an instrument, not a gate. It produces a number; deciding whether that number blocks a merge belongs to a component's `measure.sh`.
- **ADR-BP-002:** Readings are machine-local and must be re-recorded on a new host before a delta is trusted.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/benchmark/extraction_density.py`, `src/graphgraph/benchmark/relation_latency.py`
- **Test Surface Seam:** `tests/test_benchmark.py`, `tests/test_relation_latency.py`

## 7. Measurement Seams

- **Primary Metric:** `registry_dangling_sources` (target `0`, `direction: lower`)
- **Evaluation Gate Path:** `components/research/measure.sh`
- **Correctness Backpressure:** `components/research/checks.sh`
- **Telemetry Surface:** probe readings with sample counts and graph revision.
- **Branching Policy:** isolated candidate; a probe change that alters a recorded baseline's meaning re-baselines it rather than comparing across the change.
- **Known granularity gap:** this leaf shares the component's registry metric; a probe is an instrument and is deliberately not gated on its own output.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — each probe is tens of lines over the in-repo graph IR, and a benchmarking framework would add a dependency to time two functions.
- **Selected:** in-repo probes on Python 3.10, stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | `pytest-benchmark` | Couples instruments to the test runner and reports through it; probes are run standalone against real graphs. |
  | `timeit` harness only | Gives timing but not the graph-revision attribution these readings need. |

- **Fit gap:** probes measure this machine; they do not establish cross-host comparability.
- **Seam:** `src/graphgraph/benchmark/relation_latency.py`
- **Exit cost:** LOW — no production caller.
- **Cost model:** local CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a broken probe fails its own test; production behavior is unchanged.
- **Open questions:** none
