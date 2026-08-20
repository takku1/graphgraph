# Strategy Handoff — OW-AC-03 increment 3

## Target

- Contract: `docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md`
- Ticket: `OW-AC-03-3`

## Goal

Make held-out-style conceptual retrieval continuously testable without
depending on third-party checkouts. Measure the existing locus task file if
a local clone exists. Do not regress exact self-eval (4×1.0 + RED 0.0) or
local conceptual mean 1.0.

## Non-goals

- T-B04 head-to-head against other tools
- Cloning flask/express/ripgrep/requests
- Tuning retrieval against conceptual-v1 (that suite retires if used to tune)
- Claiming OW-AC-03 ≥0.80 on held-out corpora that are still absent

## Required invariants

- [Ubiquitous] Exact identifier hits SHALL still score 1.0 on `eval/graphgraph-self.json` green tasks; the RED task SHALL stay 0.0.
- [Ubiquitous] Local conceptual mean recall SHALL stay 1.0 on `eval/graphgraph-local-conceptual.json`.
- [Event-driven] WHEN a lexically disjoint fixture query names an idea only in a summary/doc THE SYSTEM SHALL retrieve the intended code node or record a measured miss.
- [Event-driven] WHEN a red-control query names a capability absent from the fixture THE SYSTEM SHALL abstain.

## Test and observation seams

- `tests/test_proof_lanes.py`
- `tests/test_conceptual_heldout.py`
- `eval/graphgraph-self.json`
- `eval/graphgraph-local-conceptual.json`
- `eval/retrieval-v1/locus.json` (observation if locus clone exists)

## KEEP gate

Human review required. No independent checker is configured.
