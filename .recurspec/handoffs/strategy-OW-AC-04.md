# Strategy Handoff — OW-AC-04

## Target

- Contract: `docs/architecture/information-retrieval/SYSTEM.md`
- Ticket: `OW-AC-04`

## Goal

When effective answer confidence (shape confidence × noisy-OR grounding)
is below 0.2, abstain instead of emitting a large low-value packet.
Rendered packet ≤ 50 real tokens.

## Non-goals

- Closing OW-AC-03 (held-out conceptual recall ≥ 0.80)
- Warming or rebuilding FastEmbed on auto
- Changing ranking so the two remaining local conceptual probes hit
- Treating budget-truncated exact reverse lookups as unanswerable

## Required invariants

- [Conditional] IF the selected anchors have neither exact identifier
  evidence nor a code-node distinctive summary match (two or more
  summary terms, at least one hyphenated or length ≥ 10) THEN THE SYSTEM
  SHALL mark the receipt `unanswerable`, abstain, cap confidence at 0.2,
  and emit no subgraph.
- [Ubiquitous] Exact identifier hits SHALL still return a packet.
- [Ubiquitous] A paraphrase whose top code anchor carries distinctive
  summary evidence SHALL remain answerable.
- [Ubiquitous] The existing red-control cases (absent facet, doc-only
  incomplete, scattered terms present) SHALL keep their current status.

## Test and observation seams

- `tests/test_abstention_red_controls.py`
- `eval/graphgraph-self.json` (exact tasks stay 4×1.0; RED tokens ≤ 50)
- `eval/graphgraph-local-conceptual.json` (observation: misses may now
  abstain; the instruction-set hit must not)

## Baseline (2026-08-16, this repo)

- RED task: `node_recall=0.0`, **1858 tokens**, status `partial`
- Local conceptual misses: answerable, 1829 / 1852 tokens, conf 0.24 / 0.27
- Local conceptual hit: answerable, 1777 tokens, conf 0.318, MRR 1.0

## KEEP gate

Human review required. No independent checker is configured.

ROADMAP lists this ticket as blocked by OW-AC-03. The OW-AC-03 increment
landed; the 0.80 gate is not met. This ticket addresses the independently
measured failure on those misses (large non-abstaining packets), not the
recall gate.
