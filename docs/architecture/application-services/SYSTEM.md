# Application Services (L1)

> **Package:** `services/`  
> **Related:** [../project-atlas/SYSTEM.md](../project-atlas/SYSTEM.md), [../agent-interfaces/SYSTEM.md](../agent-interfaces/SYSTEM.md)

## 1. Intent

Orchestrate end-user operations above retrieval/planning: natural-language **query compilation**, context rendering, snippets, project status, freshness, lifecycle, and **project atlas** construction.

## 2. Major operations

| Operation | Academic framing | Map |
|-----------|------------------|-----|
| `query` / `execute_query` | Query understanding → retrieve → packet | `services/query.py` |
| `query_context` / `render_query_context` | One-shot NL context packet | `services/context.py` |
| `final_packet` | Packet from known anchors | `services/context.py` |
| `source_snippets` | Source window materialization | `services/snippets.py` |
| Project status / freshness | Store health, delta awareness | `project_status.py`, `freshness.py` |
| `build_project_atlas` | Repository orientation artifact | `project_atlas.py` |
| Native scan orchestration | Corpus extraction driver | `native.py`, `native_context.py` |
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

## 5. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `services/` (12 modules): `query.py`, `context.py`, `snippets.py`, `project_status.py`, `freshness.py`, `project_atlas.py`, `native.py`, `lifecycle.py`, `control.py` |
| **Test surface** | `tests/test_project_atlas.py`, `tests/test_mcp_project_status.py`, `tests/test_cli_mcp.py` |
| **Note** | Service behavior is largely exercised through the transport tests — a thin orchestration layer is correctly tested at its boundaries |

## 6. Measurement seams

| | |
|--|--|
| **Primary metric** | End-to-end context-compilation latency, resident (`direction: lower`) |
| **Cache metric** | Packet cache hit rate (`direction: higher`) — a fixed key delivered roughly **18.8x** on the repeated-pipeline path |
| **Freshness gate** | An empty source delta implies a fresh graph (OW-AC-02) |
| **Receipts** | [caching and compression prototypes](../../evaluation/graybox-cycles/2026-07-31-caching-and-compression-prototypes.md) |

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

- **Fit gap:** none identified; this layer exists to keep the transports thin.
- **BUILD justification:** genuinely trivial and stable — it is glue, and glue with a dependency is worse than glue.
- **Seam:** `services/query.py`, `services/context.py`
- **Exit cost:** **LOW** — internal; no external contract depends on its shape.
- **Operational owner:** us
- **Failure mode:** a missing or invalid active graph surfaces through `project_status` with a re-scan instruction rather than an empty answer.
- **Open questions:** OW-AC-01/02 — [open-work.md](../../open-work.md)
