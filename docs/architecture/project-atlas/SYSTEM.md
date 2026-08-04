# Project Atlas & Navigation (L1)

> **Code map:** `services/project_atlas.py`, `analysis/navigation.py`  
> **Children:** [orientation-engine.md](./orientation-engine.md), [project-memory.md](./project-memory.md), [navigation-benchmark.md](./navigation-benchmark.md)

## 1. Intent

Higher-level **repository orientation**: compact atlas artifacts, navigation benchmarks, and project-memory architecture so agents can answer “where do I start?” without dumping the full graph.

## 2. Documents

| Doc | Role |
|-----|------|
| [orientation-engine.md](./orientation-engine.md) | Orientation architecture proposal |
| [project-memory.md](./project-memory.md) | Project memory architecture |
| [navigation-benchmark.md](./navigation-benchmark.md) | Atlas / navigation benchmark |
| Research agenda | [../../research/project-navigation-research-agenda.md](../../research/project-navigation-research-agenda.md) |

## 3. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Atlas APIs SHALL be promoted only with held-out navigation tasks and evidence standards.
  - `EvidenceStage: Unknown` — the held-out panel is open work (OW-AC-10); this invariant currently constrains promotion rather than describing a passed gate.
- **[Conditional]** IF atlas claims reduce tokens THEN quality on orientation tasks SHALL NOT regress.
  - `EvidenceStage: Sampled` — `tests/test_navigation_eval.py`.
- **[Ubiquitous]** An orientation answer SHALL cite graph evidence rather than summarizing from file names alone.
  - `EvidenceStage: Observed` — otherwise the atlas is a directory listing with extra steps.

## 4. ADRs

- **ADR-PA-001:** The atlas is a *derived artifact*, not a second graph. It is rebuilt from the IR so it cannot drift into an independent source of truth.
- **ADR-PA-002:** "Where do I start?" is treated as a retrieval query with its own evaluation, not as a templated report. That is why this node carries a benchmark child rather than a format specification.

## 5. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `services/project_atlas.py`, `analysis/navigation.py` |
| **Test surface** | `tests/test_project_atlas.py`, `tests/test_navigation_eval.py` |
| **Benchmark spec** | [navigation-benchmark.md](./navigation-benchmark.md) |

## 6. Measurement seams

| | |
|--|--|
| **Primary metric** | Orientation-task success on a held-out repository panel (`direction: higher`) |
| **Cost metric** | Tokens to first useful orientation (`direction: lower`) |
| **Panel gate** | ≥5 language/runtime strata, rotating (OW-AC-10) |
| **Caution** | Orientation quality is the metric most exposed to lexically-easy task sets; see [ADR-IR-001](../information-retrieval/SYSTEM.md) — a panel where the query names the answer measures very little |

## 7. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo atlas construction over the existing IR and retrieval stack; stdlib only
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | LLM-generated repository summaries (wiki-style) | A model call per repository, restated rather than derived, and stale the moment code moves; the atlas is rebuilt from the graph instead |
  | Static conventions (README + directory tree) | Already available to any agent for free — if the atlas cannot beat it on orientation tasks, the atlas is not earning its tokens |
  | Community-detection libraries | The clustering primitives are already present in the IR layer; importing a graph library for this one artifact is not justified |

- **Fit gap:** the atlas answers "where do I start", not "why is it built this way" — architectural rationale lives in this documentation tree, not in a derived artifact.
- **BUILD justification:** differentiator — cheap, graph-derived orientation is a claim the project is specifically testing against the free baseline above.
- **Seam:** `services/project_atlas.py::build_project_atlas`
- **Exit cost:** **LOW** — derived artifact; deleting it costs a capability, not the pipeline.
- **Operational owner:** us
- **Failure mode:** with no validated active graph the atlas is unavailable rather than approximate.
- **Open questions:** OW-AC-10 plus navigation research items — [open-work.md](../../open-work.md)
