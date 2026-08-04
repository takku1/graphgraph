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

## 3. Invariants

- **[Ubiquitous]** Default agent entry SHOULD be natural-language context compilation (`query_context` / `graphgraph context`) so anchors are discovered before render.
- **[Ubiquitous]** Process-local graph cache SHALL be reused across service calls in a resident process.

## 4. Open work

OW-AC-01/02 — [open-work.md](../../open-work.md).
