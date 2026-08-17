# Strategy Handoff — FAN-04 / OW-AC-08

## Target

- Contract: `docs/architecture/agent-interfaces/SYSTEM.md`
- Ticket: `FAN-04` / `OW-AC-08`

## Goal

Publish packed exact-relation latency with graph-size strata, without thrashing
the current in-process baseline.

## Non-goals

- FAN-01 / FAN-02 / FAN-03
- Ranking or retrieval algorithm changes
- Treating cold CLI spawn as core retrieval latency

## Context rule

Load only this handoff and the Agent Interfaces contract. Do not keep sibling
items in this packet.

## Required invariants

- [Ubiquitous] Benchmarks that time repeated CLI calls SHALL label cold-start; they are not core retrieval latency.
- [Event-driven] WHEN transport is a one-shot CLI process THE SYSTEM SHALL report cold-start latency separately from resident retrieval latency.

## Baseline that must exist first

Record the current packed exact-relation p50/p95 on at least three graph-size
strata before changing code. Adjacent optimization without that baseline is
OW-Q10 and stays deferred.

## Test and observation seams

- `components/agent-interfaces/measure.sh`
- `components/agent-interfaces/checks.sh`

## Implementation note

Baseline recorded at `components/agent-interfaces/relation_latency_baseline.json`
for 100 / 1_000 / 5_000 node synthetic call chains. `measure.sh` now includes
`relation_latency` strata next to resident exact-query p95. No hot-path
algorithm change.

## KEEP gate

Human review required. No independent checker is configured.
