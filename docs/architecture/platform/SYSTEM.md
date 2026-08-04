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

## 3. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Optional passes SHALL NOT be advertised as default behavior without measurement.
  - `EvidenceStage: Observed`.
- **[Conditional]** IF a semantic sidecar mismatches active graph topology THEN THE SYSTEM SHALL reject it as stale.
  - `EvidenceStage: Sampled` — `tests/test_platform.py`.
- **[Ubiquitous]** The working `CpgEvidenceProvider` SHALL NOT be described as the scanner `cpg` frontend.
  - `EvidenceStage: Observed` — the provider emits control/data/type evidence when its pass is requested; the scanner `cpg` *mode* is advertised as planned and is not selectable. Conflating them is the specific documentation error this node exists to prevent.
- **[Ubiquitous]** Every research claim in the registry SHALL resolve to a source path that exists.
  - `EvidenceStage: Proved` — mechanically enforced by `tests/test_research_registry.py`, which fails on any dangling source.

## 4. ADRs

- **ADR-PL-001:** Inference is a bounded, Horn-style, budget-capped **optional** compiler pass — off by default. An earlier claim that "no inference exists" is superseded; the correct statement is that none runs unless requested.
- **ADR-PL-002:** SQLite is acceptable here because the evidence store's access pattern is genuinely relational and SQLite is embedded stdlib — no daemon, so [ADR-ST-001](../storage/SYSTEM.md) still holds.
- **ADR-PL-003:** Platform capabilities are research-sensitive by default: they carry the [evidence standards](../../guides/evidence-standards.md) bar before promotion into the default path.

## 5. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `platform/` (22 modules): `service.py`, `evidence_store.py`, `embeddings.py`, `contracts.py`, `source_planner.py` |
| **Test surface** | `tests/test_platform.py`, `tests/test_research_registry.py` |
| **Claim ledger** | `eval/context-system-research.json` — executable provenance for research claims |

## 6. Measurement seams

| | |
|--|--|
| **Primary metric** | Marginal retrieval quality per optional pass (`direction: higher`), measured against the pass being off |
| **Cost metric** | Added latency and tokens when the pass is requested (`direction: lower`) |
| **Promotion gate** | An optional pass moves to default only on measured gain — [empirical-evaluation.md](../../evaluation/empirical-evaluation.md) § Promotion Gate |
| **Registry gate** | `tests/test_research_registry.py` — referential completeness of every claim's source |

## 7. Technology resolution

- **Decision class:** **BUILD** (evidence providers, inference) / **ADOPT** (`sqlite3` stdlib; `fastembed` optional)
- **Selected:** in-repo providers; `sqlite3` for the evidence store; `fastembed>=0.3.0` (`semantic` extra) for real embeddings
- **Standard / protocol:** SQL for the evidence store; ONNX runtime for the optional model
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | A full CPG engine (e.g. Joern) | Heavyweight and JVM-hosted; this subsystem needs evidence *when asked*, not a second permanent analysis platform |
  | A general reasoner / Datalog engine | The inference is deliberately bounded and Horn-style; an unbounded solver is the opposite of the budget cap that makes it safe to offer |
  | Hosted embedding APIs | A network call and a per-token bill inside a local-first tool; the local ONNX path keeps it offline |
  | A temporal graph database (e.g. Graphiti) | Useful model, but it requires a database plus LLM/embedding services; temporal validity is kept as optional graph facts instead — see [external-tool-interoperability-audit.md](../../evaluation/external-tool-interoperability-audit.md) |

- **Fit gap:** these capabilities are optional by construction. None of them may become load-bearing for the default path without passing the promotion gate.
- **BUILD justification:** the fit gap is fatal for off-the-shelf options — every alternative brings a daemon or a service into a tool whose defining constraint is a cold-start local process.
- **Seam:** `platform/service.py` (capability façade), `platform/contracts.py`
- **Exit cost:** **LOW** — optional by design; removing a provider degrades an opt-in capability, not the core pipeline.
- **Operational owner:** us
- **Failure mode:** a provider that cannot run reports unavailable; the requesting query proceeds without that evidence rather than failing.
- **Open questions:** OW-Q08-* — [open-work.md](../../open-work.md)
