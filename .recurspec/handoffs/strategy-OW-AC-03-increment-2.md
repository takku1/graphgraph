# Strategy Handoff — OW-AC-03 increment 2

## Target

- Contract: `docs/architecture/information-retrieval/structural-retrieval/SYSTEM.md`
- Ticket: `OW-AC-03`

## Goal

A conceptual query can rank a code node from *container* prose (module
docstring) and from a docstring that sits after a wrapped signature.
Do not special-case the local eval probes. Do not regress exact lookup.

## Non-goals

- Claiming 0.80 closed
- FastEmbed warmup
- Thesaurus aliases

## Required invariants

- [Ubiquitous] A docstring immediately after a multi-line signature SHALL
  be captured on the definition node.
- [Ubiquitous] A file's opening module docstring SHALL be stored on the
  file node.
- [Conditional] IF two or more distinctive query terms occur in a code
  node's own summary *or* its file's module docstring THEN that node
  SHALL receive `summary_multi_terms`.

## Test seams

- `tests/test_scanner.py` or `tests/test_scanner_frontends.py`
- `tests/test_retrieval.py`
- `eval/graphgraph-local-conceptual.json` (observation)
- `eval/graphgraph-self.json` (no exact-task regression)
