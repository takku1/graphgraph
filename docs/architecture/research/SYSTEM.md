# Research Laboratory (L1)

> **Package:** `research/`
> **Written up in:** [../../research/global-project-attention.md](../../research/global-project-attention.md), [../../research/context-system-tournament.md](../../research/context-system-tournament.md)
> **Claim ledger:** `eval/context-system-research.json`

## 1. Intent

Hold candidate mechanisms that are **not in the product** while they are being
falsified. This subsystem exists so that speculative work has somewhere to live
that is neither the hot path nor a document — code that runs, with a registry
that refuses to let a claim drift from its evidence.

**Does not own:** production ranking. A mechanism here is by definition
unpromoted; promotion means moving it into `retrieval/` or `representation/`
behind a measured gate.

## 2. Decomposition

| Concern | Module |
|---------|--------|
| Exact-oracle laboratory for global-project-attention hypotheses | `attention_field.py` |
| Machine-checkable claim / candidate / experiment registry | `registry.py` |
| Path-hierarchy representation candidate | `static_cover.py` |

## 3. Interface contracts

| | |
|--|--|
| **Inputs** | A graph, a claim registry (`eval/context-system-research.json`), experiment parameters |
| **Outputs** | Oracle values, candidate scores, registry validation errors |
| **Consumers** | Benchmarks under `benchmarks/context_graph/`, research write-ups |
| **Non-goals** | Serving a production query |

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Every claim in the registry SHALL resolve to a source path that exists.
  - `EvidenceStage: Proved` — mechanically enforced by `tests/test_research_registry.py`, which fails on any dangling source. This is the strongest evidence class in the tree and it is enforced by construction rather than by review.
- **[Ubiquitous]** A candidate SHALL NOT be described as promotable on a bare field-ranked baseline; it SHALL be measured inside production ranking.
  - `EvidenceStage: Measured` — symmetric coupling improved a field-ranked selection by `+0.066` and then moved production recall and MRR not at all, at 11.9x latency. See [the consolidated influence-field measurement](../../evaluation/graybox-cycles/README.md#influence-field-experiment).
- **[Ubiquitous]** Mechanisms here SHALL be off the production path.
  - `EvidenceStage: Observed` — nothing in `retrieval/` imports `research/`.
- **[Conditional]** IF an experiment is recorded THEN its claim, mechanism, and source SHALL be registered together.
  - `EvidenceStage: Proved` — `registry.py` rejects a claim missing either field.

## 5. ADRs

- **ADR-RE-001:** Research code ships in the package but never on the hot path. Keeping it runnable is what makes falsification cheap; keeping it unwired is what makes it safe.
- **ADR-RE-002:** The claim registry is executable. A research assertion whose source path has been deleted is a test failure, not a stale document — which is how the 2026-08 doc restructure was caught breaking research provenance.
- **ADR-RE-003:** Negative results are retained with the same status as positive ones. The influence-field line is the project's most instructive result and it is a refutation.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `research/attention_field.py`, `registry.py`, `static_cover.py` |
| **Test surface** | `tests/test_research_registry.py`, `tests/test_attention_field_coupling.py`, `tests/test_attention_field_research.py`, `tests/test_static_cover_research.py` |
| **Component gate** | `components/research/checks.sh` |
| **Benchmarks** | `benchmarks/context_graph/global_attention_phase{0,1,2,3}*.py`, `coupling_production_ranking.py` |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Registry referential completeness — dangling sources (`direction: lower`, target 0) |
| **Harness path** | `components/research/measure.sh` — **not yet implemented** (T-B03); the registry check is currently carried by the test suite, which is arguably the right home for a zero-tolerance invariant |
| **Correctness backpressure** | The four suites above |

## 8. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo; stdlib only
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | Notebooks for exploration | Not executable as a gate and not reviewable as a diff; the registry's value is that CI can fail on it |
  | networkx / igraph for the field computations | The oracle is deliberately exact and small so it can serve as ground truth for approximations; a library's optimized approximation is the thing under test, not the reference |
  | Deleting the line after the negative result | The refutation is load-bearing: it is why the ranking agenda now prioritizes a paraphrase task set over further field tuning |

- **Fit gap:** the oracle is exact and therefore does not scale; it is a reference implementation, not a candidate runtime.
- **BUILD justification:** differentiator — falsifying the project's own hypotheses is the research programme.
- **Seam:** `research/registry.py`
- **Exit cost:** **LOW** — unwired from production by construction.
- **Operational owner:** us
- **Failure mode:** a broken registry fails the test suite loudly; no production behavior changes.
- **Open questions:** T-B02, T-B04 — [open-work.md](../../open-work.md)
