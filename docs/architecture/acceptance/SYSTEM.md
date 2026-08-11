# Acceptance & Qualification (L1)

> **Package:** `acceptance/` (21 modules)
> **Spec of record:** [../../evaluation/acceptance-evaluation-harness.md](../../evaluation/acceptance-evaluation-harness.md)
> **Evidence bar:** [../../guides/evidence-standards.md](../../guides/evidence-standards.md)

## 1. Intent

Decide whether a GraphGraph build **qualifies** — that is, whether it answers a
sealed set of repository questions well enough, cheaply enough, and honestly
enough to ship. This is the subsystem that turns "it seems better" into a
verdict.

It is a **black-box** harness by construction: it drives GraphGraph only through
the public retrieval surface, and ground truth is used *solely to score a packet
that was already produced*. Expected node IDs, golden paths, and fixture answers
are never injected as retrieval seeds.

**Does not own:** the retrieval behavior being judged, or the research question
of which representation is cheapest. It owns the *verdict procedure*.

## 2. Decomposition

| Concern | Module map |
|---------|------------|
| Canonical task set (GG10-LC-001..012) | `tasks.py` |
| Black-box probe driver | `runner.py` |
| Gate primitives (symbols present/absent, call edges, token ceiling, irrelevant ratio, callers, completeness) | `gates.py` |
| Per-case suites | `affected_tests_case.py`, `boundary.py`, `cache_latency.py`, `delete_rename.py`, `docs_case.py`, `incremental.py`, `parity.py`, `qualification.py`, `scope_case.py` |
| Token accounting | `tokens.py` |
| Token-vs-quality loop | `quality.py` |
| Live model validation | `live_validation.py` |
| Result rendering | `scoreboard.py` |
| Data model / execution / CLI | `model.py`, `execution.py`, `__main__.py` |

## 3. Interface contracts

| | |
|--|--|
| **Inputs** | Target repository path, canonical task set, optional live-model credentials |
| **Outputs** | Per-case `GateResult`s, a Markdown/JSON scoreboard, token accounting |
| **Entry points** | `python -m graphgraph.acceptance run --repo <path>` · `graphgraph platform acceptance` |
| **Non-goals** | Mutating the graph under test; seeding retrieval with ground truth |

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Ground truth SHALL be used only to score a produced packet, never as a retrieval seed.
  - `EvidenceStage: Observed` — this is the property that makes the harness an instrument rather than a rehearsal; violating it makes every downstream number meaningless.
- **[Conditional]** IF a probe reports completeness THEN the harness SHALL verify required symbols are actually present before accepting it (`gate_no_false_complete`).
  - `EvidenceStage: Sampled` — `tests/test_acceptance.py`.
- **[Ubiquitous]** Token ceilings and irrelevant-context ratios SHALL be gated per case, not averaged across the board.
  - `EvidenceStage: Observed` — `gate_token_ceiling`, `gate_irrelevant_ratio`.
- **[Conditional]** IF live-model scoring is requested THEN its verdict SHALL be reported separately from mechanical gate results.
  - `EvidenceStage: Observed` — a model judgment is not structural proof ([evidence-standards](../../guides/evidence-standards.md)).
- **[Ubiquitous]** A case SHALL fail closed: an unrunnable probe is not a pass.
  - `EvidenceStage: Sampled` — `tests/test_acceptance_exec.py`.

## 5. ADRs

- **ADR-AC-001:** Black-box only. A harness that can see the expected answer measures the fixture, not the system — so the seed/score boundary is an invariant rather than a convention.
- **ADR-AC-002:** Cases are named and numbered (GG10-LC-001..012) against recorded defects, so a regression points at a specific historical failure rather than a diffuse score drop.
- **ADR-AC-003:** Mechanical gates and live-model scoring are separate verdicts. Only the mechanical ones may block; a model judgment is evidence, not a gate.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `acceptance/` — 21 modules |
| **Test surface** | `tests/test_acceptance.py`, `tests/test_acceptance_exec.py`, `tests/test_acceptance_quality.py`, `tests/test_live_validation.py` |
| **Component gate** | `components/acceptance/checks.sh` |
| **External corpus** | Canonical Locus regression repository (`--repo ../locus`) |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Acceptance gate pass-rate at a fixed corpus (`direction: higher`) |
| **Secondary** | Packet tokens per case (`direction: lower`), from `tokens.py` |
| **Harness path** | `components/acceptance/measure.sh` — **not yet implemented** (T-B03): the metric requires an external corpus, so it must declare `unavailable` rather than emit a number when that corpus is absent |
| **Correctness backpressure** | The four suites above |

## 8. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo harness; stdlib only, with `tiktoken` (`benchmark` extra) for real token accounting
- **Standard / protocol:** none — the task set is project-specific by design
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | SWE-bench / public code benchmarks | Measure end-to-end patch success, not context representation cost; kept as a separate protocol ([swe-bench-protocol.md](../../evaluation/swe-bench-protocol.md)) |
  | A generic assertion framework (pytest alone) | The gates are domain judgments over packets — token ceilings, irrelevant ratios, false-completeness — not assertions over return values |
  | LLM-as-judge as the primary gate | Non-deterministic and unfalsifiable as a blocking signal; retained as a separately-reported verdict per ADR-AC-003 |

- **Fit gap:** the canonical corpus is one external repository. Generalization to a rotating multi-language panel is open work (OW-AC-10).
- **BUILD justification:** differentiator — the qualification procedure *is* the project's standard of proof, and ADR-006 at L0 makes it the subsystem that must carry any superiority claim.
- **Seam:** `acceptance/execution.py`, `acceptance/runner.py`
- **Exit cost:** **LOW** — the harness observes the public surface, so replacing it does not touch the system under test.
- **Operational owner:** us
- **Failure mode:** a missing target corpus yields no verdict rather than a default pass.
- **Open questions:** OW-AC-10, T-B03, T-B04 — [open-work.md](../../open-work.md)
