# Static Analysis & Corpus Extraction (L1)

> **Packages:** `scanner/`, `scanner/frontends/`  
> **Detail docs:** [language-frontend-ir.md](./language-frontend-ir.md), [receiver-type-inference.md](./receiver-type-inference.md)

## 1. Intent

Turn a repository (and optional documents) into **graph intermediate representation** via deterministic **language frontends**: file collection, AST walks (tree-sitter), import graphs, document section extraction, typed local facts, and optional history. This is static program analysis plus document structure extraction—not runtime tracing (runtime edges carry separate provenance).

## 2. Decomposition

| Child | Academic role | Implementation map |
|-------|---------------|--------------------|
| Language frontends | Per-language extractors (Py, JS/TS, Rust, Go, Java, C#, C++) | `scanner/frontends/*` |
| Receiver-type inference | Bind call sites to callees via local type facts + obligations | `type_facts`, `persistent_facts`, binding providers |
| Document extraction | Headings, paragraphs, concept links | `scanner/doc.py` |
| Scope / structural owners | Scope-graph style ownership | `scope_graph.py` |
| [language-frontend-ir.md](./language-frontend-ir.md) | Frontend IR strategy | — |
| [receiver-type-inference.md](./receiver-type-inference.md) | Name resolution / receivers | — |

## 3. Interfaces

| | |
|--|--|
| **Inputs** | Repo root, scan depth (`files` / `symbols`), docs flag, incremental path sets, exclude dirs |
| **Outputs** | Nodes, edges, facts, telemetry: resolved / ambiguous / unknown receivers |
| **Consumers** | IR merge → native store; retrieval ranking features |

## 4. Invariants (EARS)

- **[Ubiquitous]** Unknown receivers SHALL remain explicit; name-only guess edges are not trusted topology.
- **[Conditional]** IF concrete type facts conflict THEN THE SYSTEM SHALL join to `ambiguous`.
- **[Ubiquitous]** Runtime `observed_calls` SHALL keep provenance distinct from static edges.
- **[Event-driven]** WHEN scanning incrementally THE SYSTEM SHALL re-join only affected fact keys when persistent facts are enabled (OW-Q02-C).

## 5. ADRs

- **ADR-SA-001:** Tree-sitter first; optional compiler-grade tiers (e.g. Rust THIR) only as measured secondary paths (OW-P1-08).
- **ADR-SA-002:** Bounded k-hop obligation discharge, not whole-program fixpoint by default.

## 6. Open work

OW-Q02-*, OW-AC-05, OW-D-01/02 — [open-work.md](../../open-work.md).

## 7. Research grounding (expand only with citations)

- Scope graphs / name resolution (PL / language-server literature).
- Constraint-based local type inference with provenance.
- Gray-box multi-language ceilings: [archive findings](../../evaluation/graybox-cycles).
