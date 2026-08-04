# Project Representation (L1)

> **Package:** `representation/`
> **Research lineage:** [../../research/global-project-attention.md](../../research/global-project-attention.md)
> **Consumed by:** `services/context.py`, `platform/compiler.py`, CLI `--representation`

## 1. Intent

Choose how a whole project is **shaped** before a packet is rendered: a flat
selection, or an exception-aware multiresolution one that spends resolution
where the query needs it and coarsens elsewhere.

This is the surviving candidate from the global-project-attention line. It is
shipped, versioned, and **opt-in** — `REPRESENTATION_DEFAULT` is `flat`
(`surface.py:54`), and the hybrid path activates only when explicitly selected.

**Does not own:** packet encoding (that is [context-packets](../context-packets/SYSTEM.md)),
or which nodes are retrieved ([information-retrieval](../information-retrieval/SYSTEM.md)).

## 2. Decomposition

Atomic leaf (atomic build). One module, `hybrid.py`, providing:

| Surface | Role |
|---------|------|
| `HYBRID_REPRESENTATION_VERSION` | `hybrid_reserve_v1` — the versioned identity of the shipped candidate |
| `HybridRepresentationConfig` / `HybridRepresentation` | Configuration and compiled result |
| `compile_hybrid_representation` | Build a multiresolution representation over a graph |
| `accept_representation` | Validate a requested representation against supported packets |
| `representation_schema` | Machine-readable capability description |
| `_PathHierarchy`, `_build_path_hierarchy` | Bounded path-hierarchy construction (cached) |

Supported packets: `gg`, `gg_hybrid`, `gg_lex`, `gg_lex_hybrid`.

## 3. Interface contracts

| | |
|--|--|
| **Inputs** | Graph, representation name, branching bound, token budget |
| **Outputs** | A compiled representation plus a version tag; cell markers (`__gg_cell__:`) |
| **Consumers** | `services/context.py`, `platform/compiler.py`, CLI `--representation` |
| **Non-goals** | Being the default. Changing that requires a measured win |

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** The default representation SHALL remain `flat` until a candidate shows a measured win.
  - `EvidenceStage: Observed` — `surface.py:54`.
- **[Conditional]** IF a representation is requested for an unsupported packet format THEN the request SHALL be rejected rather than silently downgraded.
  - `EvidenceStage: Sampled` — `accept_representation`, `tests/test_representation_hybrid.py`.
- **[Ubiquitous]** A compiled representation SHALL carry its version, so a measurement can be attributed to a specific candidate.
  - `EvidenceStage: Observed` — `HYBRID_REPRESENTATION_VERSION`.
- **[Ubiquitous]** Multiresolution coarsening SHALL preserve identity: a coarsened cell names what it summarizes.
  - `EvidenceStage: Sampled` — otherwise the packet trades tokens for unresolvable references, which is a loss disguised as a saving.

## 5. ADRs

- **ADR-RP-001:** Shipped but not default. The global-attention research line produced one candidate worth keeping and several worth refuting; shipping it opt-in makes it measurable in production conditions without betting the default path on it.
- **ADR-RP-002:** The representation is versioned by name (`hybrid_reserve_v1`). An unversioned candidate cannot be compared across runs, and this line has already produced results that inverted under re-measurement.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `representation/hybrid.py` |
| **Test surface** | `tests/test_representation_hybrid.py` |
| **Component gate** | `components/representation/checks.sh` |
| **Benchmark** | `benchmarks/context_graph/global_attention_phase3_recoupled.py` |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Packet tokens at fixed recall, hybrid versus flat (`direction: lower`) |
| **Promotion gate** | Becomes the default only on a measured token win with no recall regression — the comparison that ADR-RP-001 exists to keep honest |
| **Harness path** | `components/representation/measure.sh` — **not yet implemented** (T-B03) |
| **Correctness backpressure** | `tests/test_representation_hybrid.py` |

## 8. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo `hybrid.py`; stdlib only
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Flat selection only | The current default and the baseline to beat; retained precisely so the comparison exists |
  | Graph summarization via community detection (GraphRAG-style) | Optimizes global summarization; this system's queries are local and task-focused, and the cost model is tokens rather than coverage |
  | LLM-generated hierarchy | A model call on the compile path, non-deterministic, and unversionable across runs |

- **Fit gap:** the win is unproven at the default. Until the promotion gate is measured, this is a candidate, not an improvement.
- **BUILD justification:** differentiator — how a project is shaped before rendering is the core research question, not a commodity.
- **Seam:** `representation/__init__.py` (`accept_representation`, `representation_schema`)
- **Exit cost:** **LOW** — opt-in and versioned; removing it restores `flat`, which is already the default.
- **Operational owner:** us
- **Failure mode:** an unsupported combination is rejected at request time rather than degrading the packet.
- **Open questions:** T-B03, and the promotion measurement itself — [open-work.md](../../open-work.md)
