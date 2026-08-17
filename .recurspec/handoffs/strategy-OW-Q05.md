# Strategy Handoff — OW-Q05 (packet provenance + grounding module)

## Target

- Contract: `docs/architecture/context-packets/SYSTEM.md`
- Ticket: `OW-Q05`

## Goal

Every advertised packet format that names a code node SHALL carry the same
`@path:line` provenance `gg` already emits, so a clamped machine response
still has a jump target. Keep the OW-AC-04 grounding score in its own
module instead of growing `anchors.py`.

## Non-goals

- Changing the 1.15× clamp ratio
- New packet formats
- OW-AC-03 recall work

## Required invariants

- [Ubiquitous] SVO entity rows SHALL include `_compact_source_context` when
  a node has a path, as checked by `tests/test_packets.py`.
- [Ubiquitous] `graphgraph query --show-anchors` on a scanned symbol SHALL
  still expose `path:line` after clamp, as checked by
  `tests/test_retrieval.py`.
- [Ubiquitous] Grounding score functions SHALL live in
  `src/graphgraph/retrieval/grounding.py` and remain re-exported from
  `anchors.py`.

## KEEP gate

Human review required.
