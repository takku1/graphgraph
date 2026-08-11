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

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Unknown receivers SHALL remain explicit; name-only guess edges are not trusted topology.
  - `EvidenceStage: Observed` — [receiver-type-inference.md](./receiver-type-inference.md) § precision by construction.
  - **Re-confirmed 2026-08-05** (consolidated gray-box static-analysis measurement): `state = self.make_setup_state(...)` then `state.add_url_rule(...)` in real Flask source (`sansio/blueprints.py:321,324`) drops the call site entirely rather than resolving it, because `state`'s type requires return-type-flow propagation this frontend does not perform. Verified this is the deliberate consequence of this exact invariant, not an oversight: `scanner/frontends/syntax.py:871-878`'s own comment explains that emitting a `calls_candidate` edge whenever the callee *name* matches something (without receiver-type evidence) "would turn `list.append()`/`dict.get()` collisions into graph topology" — i.e., the report's own suggested fix (emit `calls_candidate` when the name uniquely matches one method) was already weighed against this exact false-positive risk and rejected in favor of dropping the call site with disclosed telemetry (`call_topology_status: partial`, `receiver_resolution_ratio`) instead. Not a wiring gap; closing the ~33% gap for real needs return-type-flow inference or a compiler-grade tier (already tracked as OW-P1-08 / this doc's Technology Resolution item on Rust THIR), not a wiring change here. See [the measurement ledger](../../evaluation/graybox-cycles/README.md#static-analysis-findings).
- **[Conditional]** IF concrete type facts conflict THEN THE SYSTEM SHALL join to `ambiguous`.
  - `EvidenceStage: Sampled` — `tests/test_scanner_frontends.py`.
- **[Ubiquitous]** Runtime `observed_calls` SHALL keep provenance distinct from static edges.
  - `EvidenceStage: Observed`.
- **[Event-driven]** WHEN scanning incrementally THE SYSTEM SHALL re-join only affected fact keys when persistent facts are enabled (OW-Q02-C).
  - `EvidenceStage: Measured` — [consolidated static-analysis measurements](../../evaluation/graybox-cycles/README.md#static-analysis-findings).
- **[Ubiquitous]** Receiver-type-resolved member-call edges SHALL hold ≥98% independently-verified precision, per language (OW-AC-05).
  - `EvidenceStage: Measured` (2026-08-05) — the 7-language `polyglot-scope-2026-07-31` fixture (0 automated test previously wired to it) re-run by hand: 0/7 false positives on its `helper::Middle` precision oracle, all 7 languages still resolving the three historically-hardest edge classes (self-recursion, same-file collision, receiver-typed member call). A random 15-edge sample of `tree_sitter_type_resolved` calls from a fresh scan of `takku1/locus@76d80f9` (Rust, 396 files) was grep-verified against real source one edge at a time: 15/15 (100%) correct. Not yet covered: a real-repo independent sample for the other 6 languages, and a per-language call-volume table.
- **[Conditional]** IF a tree-sitter grammar cannot be loaded THEN THE SYSTEM SHALL record the reason and skip that language rather than abort the scan.
  - `EvidenceStage: Observed` — `_LANGUAGE_LOAD_ERRORS` in `scanner/frontends/languages.py:112-152`.

## 5. ADRs

- **ADR-SA-001:** Tree-sitter first; optional compiler-grade tiers (e.g. Rust THIR) only as measured secondary paths (OW-P1-08).
- **ADR-SA-002:** Bounded k-hop obligation discharge, not whole-program fixpoint by default.
- **ADR-SA-003:** Grammar loading is lazy and failure-tolerant — a missing grammar degrades one language, never the scan. Cost: per-language coverage becomes an environment property, so `graphgraph doctor` is the authority on what is actually parseable, not this document.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `scanner/` (8 modules), `scanner/frontends/` |
| **Grammar boundary** | `scanner/frontends/languages.py` — the only lazy-import site for `tree_sitter` |
| **Test surface** | `tests/test_scanner.py`, `test_scanner_frontends.py`, `test_scanner_imports.py`, `test_scanner_incremental.py`, `test_scanner_docs.py`, `test_scanner_history.py`, `test_scope_graph.py` |
| **Environment probe** | `graphgraph doctor` (`cli/diagnostics.py:110-111`) |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Receiver-resolution precision — target **≥98%**, independently scored (`direction: higher`, OW-AC-05). Measured 2026-08-05: **100% (15/15)** grep-verified on real Rust source; **0/7 false positives** on the 7-language synthetic oracle. See §4 invariant above. |
| **Secondary metric** | Scan wall time (`direction: lower`); profiled via `cProfile` over `graphgraph scan --depth symbols` |
| **Correctness backpressure** | The scanner test surface above, plus a canonical timestamp-free graph dump — byte-identity is the gate that let the hot-path work land safely |
| **Receipts** | [consolidated scan and language measurements](../../evaluation/graybox-cycles/README.md#static-analysis-findings) |
| **Fixture** | `../../evaluation/graybox-cycles/fixtures/polyglot-scope-2026-07-31/` — seven languages with an `ORACLE.md` |

## 8. Technology resolution

- **Decision class:** **ADOPT** (parsing) + **BUILD** (name resolution on top)
- **Selected:** `tree-sitter>=0.22`, `tree-sitter-language-pack==1.10.9`, `pathspec>=0.12` (ignore-file semantics)
- **Standard / protocol:** tree-sitter grammar ABI; `.gitignore` pattern syntax via pathspec
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Language servers (LSP) | A per-language daemon per repository; incompatible with the cold-start CLI budget this project measures |
  | Compiler frontends (e.g. Rust THIR) | Highest fidelity, but one toolchain per language and a build step per scan; held as a measured secondary tier (OW-P1-08) |
  | Regex-only extraction | The earlier tier; cannot carry scope or receiver facts — see [language-frontend-ir.md](./language-frontend-ir.md) |

- **Fit gap:** tree-sitter yields syntax, not semantics. It does not bind a call site to a callee. **Receiver-type inference is therefore the BUILD**, and it is where the subsystem's difficulty actually lives.
- **BUILD justification:** differentiator — cheap cross-language name resolution without a compiler or daemon is the capability the project is testing.
- **Seam:** `scanner/frontends/languages.py` (grammar acquisition isolated behind `_language_for_name` / `_parser_for_language`)
- **Exit cost:** **HIGH** — the grammar ABI and per-language node-type assumptions are spread across the frontends.
- **Operational owner:** us (vendored grammars, no service dependency)
- **Failure mode:** a missing or broken grammar records into `_LANGUAGE_LOAD_ERRORS` and that language is skipped; the fallback chain tries `tree_sitter_language_pack` first, then per-language grammar modules.
- **Open questions:** OW-Q02-*, OW-AC-05, OW-D-01/02 — [open-work.md](../../open-work.md)

## 9. Research grounding (expand only with citations)

- Scope graphs / name resolution (PL / language-server literature).
- Constraint-based local type inference with provenance.
- Gray-box multi-language ceilings: [graybox cycles](../../evaluation/graybox-cycles/README.md).
