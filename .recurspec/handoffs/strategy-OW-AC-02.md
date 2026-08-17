# Strategy Handoff — OW-AC-02 (+ OW-Q07 no-op)

## Target

- Contract: `docs/architecture/application-services/SYSTEM.md`
- Also: `docs/architecture/storage/SYSTEM.md` empty-delta no-op (OW-Q07)
- Ticket: `OW-AC-02`

## Goal

`project_status` classifies the active native graph as validated / stale /
invalid. An incremental scan whose source delta is empty must not rebuild
or rewrite the store, and must remain `fresh`.

## Non-goals

- Federation across repositories
- Changing Git freshness rules

## Required invariants

- [Ubiquitous] Status SHALL report `active_build` in
  {validated, stale, invalid, unchecked, absent}.
- [Event-driven] WHEN dirty files and removals are both empty THE SYSTEM
  SHALL return the previous graph without a full rebuild and without
  rewriting the store.
- [Ubiquitous] An empty source delta after a validated scan SHALL remain
  `fresh`.
