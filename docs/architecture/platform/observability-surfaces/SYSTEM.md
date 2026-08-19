# Observability and Local Surfaces (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Record what actually happened over time — runtime traces, episodes, memories, and revision-to-revision change packets — measure the compiler against fixed cases, and serve the result on a local host; does not schedule compiler passes, own the evidence cache, or implement an analysis.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One append-then-project shape over observed history, and the local surface that exposes it.

## 3. Interface Contracts

- **Inputs:** `graph_ir`, `platform_state`, `optional_evidence`
- **Outputs:** `longitudinal_records`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF the local HTTP server binds a non-loopback host THEN it SHALL require an API token rather than start open.
  - `EvidenceStage:` Observed
- **[Event-driven]** WHEN a coverage-format trace names only the executed function THE SYSTEM SHALL attribute it to a `runtime:coverage` caller with `runtime_trace` provenance, so statically-derived `calls` stay distinguishable from observed ones.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** The episode store SHALL be append-only, and a superseded episode SHALL be deactivated by a later record rather than rewritten in place.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Every longitudinal record SHALL be written under `PLATFORM_STATE_VERSION` behind a file lock.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A benchmark run SHALL report `ok` only when every configured gate and every individual case passes.
  - `EvidenceStage:` Observed
- **[Conditional]** IF a benchmark case's project graph is absent THEN the case SHALL be recorded as failed rather than skipped silently.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-OS-001:** Observed history is append-only with supersession, never in-place edit. "What did this project look like at time T" is only answerable if the record was never rewritten.
- **ADR-OS-002:** Runtime-observed calls are a distinct edge type with distinct provenance from static calls. Merging them would let a trace silently overwrite a structural fact, and coverage formats do not even name a caller.
- **ADR-OS-003:** The local server is loopback-first and token-gated off loopback, because this leaf can invoke a scan and install hooks — an open bind is a code-execution surface, not just a read surface.
- **ADR-OS-004:** Gates are declared as data (`BenchmarkGates`) rather than asserted inline, so a measured claim and the threshold it was judged against travel together in the receipt.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/platform/benchmarking.py`, `src/graphgraph/platform/change.py`, `src/graphgraph/platform/evaluation.py`, `src/graphgraph/platform/memory.py`, `src/graphgraph/platform/server.py`, `src/graphgraph/platform/temporal.py`, `src/graphgraph/platform/tracing.py`
- **Test Surface Seam:** `tests/test_platform.py`, `tests/test_runtime_coverage.py`, `tests/test_context_compiler.py`

## 7. Measurement Seams

- **Primary Metric:** `optional_pass_marginal_recall` (`direction: higher` vs the pass being off)
- **Correctness Backpressure:** `components/platform/checks.sh`
- **Telemetry Surface:** benchmark gate table and per-case receipts, trace format and event counts, episode and memory versions, change-packet cursor.
- **Branching Policy:** isolated candidate; platform checks must pass.
- **Known granularity gap:** this component has no evaluation probe script at all, and the parent's `optional_pass_marginal_recall` does not describe this leaf at all — the benchmark harness here *produces* measurements rather than being gated by one. The component-level metric for this leaf is undesigned, so it is stated as a gap rather than filled with a number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable — an append-only JSONL record, a stdlib `ThreadingHTTPServer` on loopback, and a timing loop. Every alternative below introduces a service or an agent into a cold-start local process to replace roughly a page of code each.
- **Selected:** in-repo stores on Python 3.10; `http.server` and `hmac` from the standard library
- **Standard / protocol:** HTTP on loopback; JSON and JSONL for records; V8/Istanbul coverage and native JSON/JSONL on the trace-ingest side
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | OpenTelemetry collector | An agent and an exporter pipeline for a per-workspace local file. |
  | ASGI framework (FastAPI/Starlette) | A dependency and a server model for a handful of loopback routes. |
  | `pytest-benchmark` / `asv` | Harness-shaped, not graph-shaped; the gates here are recall and token budget, not wall time alone. |
  | Event-sourcing framework | Vocabulary for one append-only file with a `supersedes` field. |

- **Fit gap:** single-host, single-workspace. There is no aggregation across machines and none is a stated goal.
- **Seam:** `src/graphgraph/platform/server.py`
- **Exit cost:** LOW — nothing on the compile path reads these records; removing the surface loses history, not answers.
- **Cost model:** local disk and CPU; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** a failed ingest or an unavailable port is reported and the compile path is unaffected.
- **Open questions:** OW-Q08
