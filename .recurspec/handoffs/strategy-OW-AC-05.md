# Strategy Handoff — OW-AC-05

## Target

- Contract: `docs/architecture/static-analysis/name-resolution/SYSTEM.md`
- Ticket: `OW-AC-05`

## Goal

Measure receiver-resolution precision per language on a multi-file inherited
member-call panel, and publish a volume table. Expand the held-out set from
TS/C# to Python and Go using the same Store/Account/persist shape.

## Non-goals

- Third-party corpus checkouts
- Runtime trace coverage (OW-D-01)
- Changing the unknown-receiver policy (still no name-only `calls` edges)

## Required invariants

- [Ubiquitous] A type-resolved member call on an inherited method SHALL
  bind to the method on the ancestor type, not a same-named method on an
  unrelated type.
- [Ubiquitous] Per-language held-out precision SHALL be ≥ 0.98 with zero
  false owners.
- [Ubiquitous] The report SHALL include a volume table (resolved /
  ambiguous / unknown / unmatched) per language for the polyglot fixture.

## Test seams

- `tests/test_receiver_heldout.py`
- `tests/test_resolution_report.py`
- `components/static-analysis/measure.sh`

## KEEP gate

Human review required.
