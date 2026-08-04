# Platform & Evidence Services (L1)

> **Package:** `platform/`  
> **Do not conflate** optional platform evidence with unimplemented scanner modes.

## 1. Intent

Cross-cutting and optional capabilities: CPG-style evidence providers, bounded Horn-style edge inference, temporal/memory stores, embeddings hooks, federation, repair, benchmarking helpers.

## 2. Decomposition (conceptual)

| Capability | Academic framing | Notes |
|------------|------------------|-------|
| CPG evidence provider | Control/data/type evidence when pass requested | Implemented path when requested |
| Scanner `cpg` frontend | Selectable scan mode | **Not** the same; may be planned only |
| `infer_edges` | Bounded optional inference | Off by default, budget-capped |
| Temporal / memory | Bi-temporal / session memory experiments | Research-sensitive; evidence standards apply |
| Semantic / embeddings | Optional semantic indexes | Must version with graph topology |
| Service façade | Platform service, hooks, change | `service.py`, git hooks path via `git rev-parse` |

## 3. Invariants

- **[Ubiquitous]** Optional passes SHALL not be advertised as default behavior without measurement.
- **[Conditional]** IF a semantic sidecar mismatches active graph topology THEN THE SYSTEM SHALL reject it as stale.

## 4. Open work

OW-Q08-*; research registry under `research/`. Historical platform essays in archive.
