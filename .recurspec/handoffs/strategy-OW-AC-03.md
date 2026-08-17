# Strategy Handoff — OW-AC-03

## Target

- Contract: `docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md`
- Ticket: `OW-AC-03`

## Goal

Let a lexically disjoint (label-disjoint) conceptual query still retrieve the
code node whose summary or semantic seed names the idea. Do not regress exact
identifier lookup.

## Non-goals

- OW-AC-04 abstention
- Building FastEmbed on every auto query
- Claiming the held-out conceptual-v1 panel (corpora not on disk)
- A general thesaurus

## Required invariants

- [Ubiquitous] Exact identifier hits SHALL still bypass heavy ranking.
- [Conditional] IF the top lexical hit is not an exact label/path/id match THEN THE SYSTEM SHALL consult a current semantic index when one exists, without requiring `_weak_lexical`.
- [Conditional] IF two or more distinctive query terms occur in a code node's summary THEN that node SHALL outrank a node that only matches generic query words.

## Test and observation seams

- `tests/test_retrieval.py`
- `tests/test_planning.py`
- `eval/graphgraph-self.json` (no exact-task regression)
- `eval/graphgraph-local-conceptual.json` (observation; may remain below 0.80)

## KEEP gate

Human review required. No independent checker is configured.
