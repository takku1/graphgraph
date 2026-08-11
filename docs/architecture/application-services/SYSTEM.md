# Application Services (L1)

> **Package:** `services/`  
> **Related:** [../project-atlas/SYSTEM.md](../project-atlas/SYSTEM.md), [../agent-interfaces/SYSTEM.md](../agent-interfaces/SYSTEM.md)

## 1. Intent

Orchestrate end-user operations above retrieval/planning: natural-language **query compilation**, context rendering, snippets, project status, freshness, lifecycle, and **project atlas** construction.

## 2. Major operations

| Operation | Academic framing | Map |
|-----------|------------------|-----|
| `query` / `execute_query` | Query understanding → retrieve → packet | `services/query.py` |
| `CompilerDriver.compile` | One-shot NL context packet and workflow receipt | `services/compiler_driver.py` |
| `final_packet` | Packet from known anchors | `services/context.py` |
| `source_snippets` | Source window materialization | `services/snippets.py` |
| Project status / freshness | Store health, delta awareness | `project_status.py`, `freshness.py` |
| `build_project_atlas` | Repository orientation artifact | `project_atlas.py` |
| Compiler driver | Project refresh → compile → cache → validate → receipt | `compiler_driver.py`; lifecycle, freshness, and project status are direct domain seams |
| Lifecycle / control receipts | Gate control | `lifecycle.py`, `control.py` |

## 3. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** The default agent entry SHOULD be natural-language context compilation (`query_context` / `graphgraph context`) so anchors are discovered before render.
  - `EvidenceStage: Observed` — the alternative requires the caller to already know node IDs.
- **[Ubiquitous]** A process-local graph cache SHALL be reused across service calls in a resident process.
  - `EvidenceStage: Measured` — this is the whole resident-transport win; see [agent-interfaces](../agent-interfaces/SYSTEM.md).
- **[Conditional]** IF a packet cache key is computed THEN it SHALL exclude the tool's own `.graphgraph/` artifacts.
  - `EvidenceStage: Measured` — otherwise the key self-invalidates every run (0% hit rate observed on external repositories).
- **[Event-driven]** WHEN a service reports project status THE SYSTEM SHALL distinguish a validated active build from a stale one (OW-AC-02).
  - `EvidenceStage: Sampled` — `tests/test_mcp_project_status.py`.

## 4. ADRs

- **ADR-AS-001:** Services orchestrate; they do not re-implement retrieval or planning. A behavior that belongs to retrieval and appears here is duplication, and the duplicate will drift.
- **ADR-AS-002:** Anchor discovery is the service's job, not the caller's. `query_context` exists so an agent never has to guess a node ID to ask a question.
- **ADR-AS-003:** `CompilerDriver.compile(DriverRequest)` is the single external
  Seam for project lifecycle, compilation, whole-response caching, validation,
  timing, and workflow receipts. `ContextCompiler` remains the semantic graph
  compiler. Transport adapters SHALL NOT reproduce either schedule.

## 5. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `services/`: `compiler_driver.py`, `cache_identity.py`, `query.py`, `context.py`, `snippets.py`, `project_status.py`, `freshness.py`, `project_atlas.py`, `lifecycle.py`, `control.py` |
| **Test surface** | `tests/test_project_atlas.py`, `tests/test_mcp_project_status.py`, `tests/test_cli_mcp.py` |
| **Note** | Driver behavior is exercised through its Interface plus transport parity. Query cache/control ownership is local to `compiler_driver.py`; stable, full, and known-anchor final packet rendering remains in `context.py`; deterministic cache identities shared by both live in `cache_identity.py`. |

## 6. Measurement seams

| | |
|--|--|
| **Primary metric** | End-to-end context-compilation latency, resident (`direction: lower`) |
| **Cache metric** | Packet cache hit rate (`direction: higher`) — a fixed key delivered roughly **18.8x** on the repeated-pipeline path |
| **Freshness gate** | An empty source delta implies a fresh graph (OW-AC-02) |
| **Receipts** | [consolidated cache measurements](../../evaluation/graybox-cycles/README.md#instrument-and-representation-measurements) |

## 7. Technology resolution

- **Decision class:** **BUILD** (orchestration only)
- **Selected:** in-repo service modules; stdlib only
- **Standard / protocol:** none — this layer is internal; the protocol boundary is [agent-interfaces](../agent-interfaces/SYSTEM.md)
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | A workflow/orchestration framework | The orchestration is a handful of sequential calls per operation; a framework would add vocabulary and indirection without removing any decision |
  | A task queue or job runner | Operations are synchronous and sub-second on the resident path; asynchrony would add failure modes to a path that has none |
  | Pushing orchestration into the CLI/MCP layers | Would duplicate it across both transports — precisely what ADR-AI-002 forbids |

- **Fit gap:** lifecycle, cache, validation, and receipt decisions are substantial
  enough to drift when transports coordinate them independently.
- **BUILD justification:** the compiler driver creates Locality across CLI, MCP,
  HTTP, Python, and acceptance callers without introducing a workflow framework.
- **Seam:** `services/compiler_driver.py`
- **Exit cost:** **LOW** — internal; no external contract depends on its shape.
- **Operational owner:** us
- **Failure mode:** a missing or invalid active graph surfaces through `project_status` with a re-scan instruction rather than an empty answer.
- **Open questions:** OW-AC-01/02 — [open-work.md](../../open-work.md)
