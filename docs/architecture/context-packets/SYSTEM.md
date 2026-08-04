# Context-Packet Encoding (L1)

> **Package:** `packets/`  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Packet Formats

## 1. Intent

Serialize a selected subgraph into an **LLM-facing context packet**. Choose format by **measured token cost** and **mechanical validation**, not a universal aesthetic floor.

Distinguish:

| Artifact | Role |
|----------|------|
| Binary `.gg` store | Persistence |
| Context packet (`gg`, `gg_lex`, hybrid, SVO, …) | Prompt boundary |
| JSON receipt | MCP/CLI control envelope |

## 2. Decomposition

| Concern | Module map |
|---------|------------|
| Renderers | `packets/renderers.py`, `formats.py` |
| Validation | `packets/validation.py` |
| Packet metrics | `packets/metrics.py` |

Public formats must generate and validate end-to-end or be unadvertised (OW-Q05-A). Names: compact `gg` is the accepted CLI/API name (older research text may say `gg_max`).

## 3. Invariants

- **[Ubiquitous]** IF validation fails THEN THE SYSTEM SHALL not claim structural success.
- **[Conditional]** IF selecting a cheaper encoding THEN identity-safe semantics SHALL be preserved.
- **[Ubiquitous]** Token claims for ranking formats SHALL use calibrated estimators (OW-AC-07 done).

## 4. Open work

OW-Q05-*, OW-AC-06 — [open-work.md](../../open-work.md).
