# Strategy — OW-AC-03 semantic-store candidate

## Target contract and resolution

- Contract: `docs/architecture/information-retrieval/SYSTEM.md`
- Ticket: `OW-AC-03`
- Candidate: `candidate/ow-ac-03-semantic-store`
- Decision: **BUILD** the store/ranking seam; **ADOPT** the already-selected
  optional `fastembed>=0.3.0` backend. Technology resolution is complete.
- Prior correction: `.recurspec/handoffs/correction-ow-ac-03-semantic-store.md`

## Goal

Deepen the semantic-index module so a current real-embedding index is usable by
default non-exact queries within the existing cold/warm envelope and supplies
implementation plus prose evidence without a global-rank multiplier.

## Non-goals

- Do not tune against sealed expected answers or read sealed corpora.
- Do not change the embedding model or make `scan` build dense vectors.
- Do not weaken latency, acceptance, freshness, exact-query, or abstention gates.
- Do not remove the dependency-free hash fallback.
- Do not edit the target contract, roadmap, baselines, or evaluator from the
  Implementor branch.

## EARS invariants

- WHEN a real embedding backend builds an index, THE SYSTEM SHALL persist its
  true vector dimension in a memory-mappable dense representation instead of
  materializing a JSON dictionary per vector on query.
- WHEN a current dense store is queried, THE SYSTEM SHALL compute one score
  vector and expose category-aware top-k so callers can reserve code and prose
  without requesting an arbitrary global top-N multiplier.
- WHEN both code and prose candidates exist, a balanced query SHALL reserve half
  its requested capacity for code; shortages SHALL yield unused capacity to the
  other category.
- WHEN artifacts are published, THE SYSTEM SHALL make a complete generation
  visible atomically; interrupted publication SHALL leave the prior generation
  usable.
- WHEN legacy dense JSON is encountered, THE SYSTEM SHALL classify it honestly
  and provide an explicit rebuild/migration action rather than silently paying
  its cold decode on default queries.
- WHEN the backend is hash-only, THE SYSTEM SHALL retain dependency-free JSON
  build/load/query behavior without importing NumPy or FastEmbed.
- WHEN `auto` receives a non-exact query and a current dense store exists, THE
  SYSTEM SHALL consume balanced semantic evidence regardless of lexical coverage
  or process warmness.
- WHEN `auto` receives an exact query, THE SYSTEM SHALL avoid semantic
  load/embed/score.
- IF the semantic state is missing, stale, or incompatible, THE SYSTEM SHALL
  avoid implicit builds and report an actionable state.

## Required checks

- Test-first dense-format coverage: true dimensionality, round trip, current and
  stale classification, atomic publication/interruption, and balanced top-k when
  the first code candidate is outside global top-24.
- Planner coverage: current dense auto consumption under strong lexical scores
  and a cold backend; exact bypass; missing/stale non-building behavior.
- Hash-backend build/load/query without importing the dense dependency path.
- Legacy dense JSON is actionable non-current state and never decoded on a
  default cold query.
- Focused semantic/planner/CLI suite, complete pytest, Ruff, and diff check.

## Baseline vector

- Prior rejected cold query: 10,812 ms.
- Prior JSON load: 4,533.5 ms.
- Prior semantic seed composition: 0 code / 6 prose.
- Structural-only cold control: 2,078 ms query / 2,328 ms total.
- Prototype only: 1,089.1 ms cold embed+scan; 4.2 ms mmap open; 20.55 MB
  artifact; 3 code / 3 prose.
- No accepted Recurspec baseline exists. A KEEP does not promote one; promotion
  happens explicitly only after merge.

## Evaluation module and gates

Run from the isolated candidate worktree:

`recurspec evaluate semantic-store candidate/ow-ac-03-semantic-store`

The module SHALL fail before emitting its metric vector if an absolute gate is
missed, because an absent first baseline is neutral in Recurspec and must not
waive an SLO.

- Hard: correctness suite and Ruff pass.
- Hard: cold non-exact complex-query p95 ≤ 3,000 ms over at least 10 fresh
  processes on a current dense store.
- Hard: warm complex-query p95 ≤ 1,500 ms over at least 30 resident calls.
- Hard: exact fast path is semantic-free; missing/stale auto never builds.
- Hard: current dense results contain code and prose when both exist; shortages
  yield capacity without empty slots.
- Target: conceptual full recall ≥ 0.80 with no exact-task regression.
- Observation: rebuild duration, artifact bytes, and phase timings.

If no non-sealed own-repository conceptual task set is available, report the
recall target as UNVERIFIED and do not claim full completion or 10/10.

## Authority

The Implementor owns only candidate source and tests. The Architect owns this
handoff, evaluation instruments, verdict, reconciliation, merge, and baseline.
Maker and checker must differ.
