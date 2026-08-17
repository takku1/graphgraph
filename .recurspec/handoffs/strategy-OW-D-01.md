# Strategy Handoff — OW-D-01

## Target

- Contract: `docs/architecture/static-analysis/name-resolution/SYSTEM.md`
- Also: `docs/architecture/static-analysis/SYSTEM.md` (`observed_calls` provenance)
- Ticket: `OW-D-01`

## Goal

Ingest a real Express-shaped coverage artifact (Istanbul/`coverage-final.json`
or V8 `--experimental-test-coverage`) into `observed_calls` with
`runtime_trace` provenance. Fixtures prove provenance preservation; a live
mocha run is not required.

## Non-goals

- Running Express tests in CI
- Replacing static `calls` edges
- Name-only guess edges when two same-named functions cannot be disambiguated
  by path

## Required invariants

- [Ubiquitous] Runtime `observed_calls` SHALL keep provenance distinct from static edges.
- [Event-driven] WHEN coverage reports a zero hit count THE SYSTEM SHALL emit no edge.
- [Event-driven] WHEN two same-named functions exist THE SYSTEM SHALL prefer the node whose path matches the coverage URL.

## Test and observation seams

- `tests/test_runtime_coverage.py`
- `tests/test_platform.py`

## KEEP gate

Human review required. No independent checker is configured.
