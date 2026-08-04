# Persistent Storage (L1)

> **Packages:** `storage/`, `runtime/`, `io/`  
> **Children:** [native-graph-store.md](./native-graph-store.md), [incremental-update-protocol.md](./incremental-update-protocol.md)  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Native Storage Contract

## 1. Intent

**Native graph store** for project-local persistence: full-fidelity sectioned `.gg` (GGB4 family) with identity/detail/edge/relation sections and checksums. Legacy formats are migration inputs via `load_any` / ingest—not auto-selected active stores.

```text
source → Graph IR → binary graph.gg → selected subgraph → context packet
                                              ↘ JSON control receipt
```

## 2. Decomposition

| Child | Role |
|-------|------|
| [native-graph-store.md](./native-graph-store.md) | Sectioned store architecture (v4 proposal lineage) |
| [incremental-update-protocol.md](./incremental-update-protocol.md) | Delta / refresh protocol |
| Atomic state & locks | `runtime/state.py` (OS advisory locks; age alone does not revoke live owners) |
| Manifest / cache | `runtime/manifest.py`, `runtime/cache.py`, `io/cache.py` |
| Discovery | Active graph path resolution (`io/discovery.py`) |

## 3. Interfaces

| | |
|--|--|
| **Inputs** | Full or delta IR, output path overrides |
| **Outputs** | `.graphgraph/graph.gg`, fingerprints for process memoization |
| **Invariants** | Auto-discover `.graphgraph/graph.gg` unless overridden |

## 4. Invariants

- **[Ubiquitous]** Active store discovery SHALL prefer native `.gg` over legacy interchange.
- **[Event-driven]** WHEN source delta is empty THE SYSTEM SHOULD avoid full rebuild (OW-Q07-A).
- **[Ubiquitous]** Packet `#gg` text is **not** the binary store encoding.

## 5. Open work

OW-AC-02, OW-Q07-* — [open-work.md](../../open-work.md).
