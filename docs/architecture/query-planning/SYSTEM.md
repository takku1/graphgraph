# Query Planning (L1)

> **Package:** `planning/`  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Query Classes  
> **Confidence detail:** [../information-retrieval/confidence-and-routing.md](../information-retrieval/confidence-and-routing.md)

## 1. Intent

Map natural-language or typed requests to a **query class**, expansion budget, **context-packet** encoding choice, and policy set. Deterministic routing is default; fitted models only after held-out utility gains (OW-Q03-A).

## 2. Query classes

| Query class | Purpose |
|-------------|---------|
| `direct_lookup` | Definition / focused symbol |
| `reverse_lookup` | Callers, references, dependents |
| `affected_tests` | Test impact attribution |
| `multi_hop_path` | Dependence / call / data-flow path |
| `blast_radius` | **Change-impact neighborhood** |
| `subsystem_summary` | Architectural slice summary |
| `doc_summary` | Document-grounded sections |
| `negative_query` | Absence / isolation evidence |
| `recent_changes` | History-qualified evidence |
| `spreading_activation` | Explicit multi-step activation |

Typical encoding heuristics (not hard law): direct/reverse → 1-hop compact packet; path/blast → 2-hop; zero-edge → semantic arrow; summary → structural or `doc_summary`.

## 3. Decomposition

| Concern | Module map |
|---------|------------|
| Query compiler (NL → typed) | `query_compiler.py` |
| Routing | `routing.py` |
| Budgets / shape | `budgets.py`, `shape.py` |
| Packet choice | `packet.py` |
| Policies | `policies.py` |
| Token cost model | `token_cost.py` |

## 4. Invariants

- **[Ubiquitous]** Semantic invariants remain hard gates; continuous scores must not blur valid/invalid.
- **[Conditional]** IF routing is automatic THEN explicit class overrides SHALL still win.
- **[Ubiquitous]** Read-only query facades SHALL not imply mutation or silent full reindex.

## 5. Open work

OW-Q03-A/B/C, OW-P1-03 — [open-work.md](../../open-work.md).
