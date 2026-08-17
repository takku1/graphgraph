# Strategy Handoff — OW-D-04

## Target

- Contract: `docs/architecture/application-services/SYSTEM.md`
- Ticket: `OW-D-04`

## Goal

When the OW-AC-06 1.15× clamp fires on a JSON envelope, keep a compact
JSON object that still has `packet`, `control`, `anchors`, `query_class`,
and `workflow`. Do not replace the envelope with `{packet, packet_format,
workflow:{}}`.

## Non-goals

- Changing the 1.15× ratio
- Pretty-print as the machine default
- FAN-02 typed-fact join

## Required invariants

- [Conditional] IF the machine response is JSON THEN THE SYSTEM SHALL keep
  routing keys (`control`, `anchors`, `query_class`, `workflow`) when the
  packet-ratio clamp fires.
- [Ubiquitous] Pretty-print whitespace SHALL NOT be treated as evidence that
  requires dropping the envelope.

## Test and observation seams

- `tests/test_response_surface.py`
- `tests/test_cli_mcp.py`

## KEEP gate

Human review required. No independent checker is configured.
