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

## 3. Invariants

- **[Ubiquitous]** Atlas APIs SHALL be promoted only with held-out navigation tasks and evidence standards.
- **[Conditional]** IF atlas claims reduce tokens THEN quality on orientation tasks SHALL not regress.

## 4. Open work

Track under research navigation items and service exposure; see [open-work.md](../../open-work.md) and research agendas.
