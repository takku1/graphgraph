# Locus Black-Box Validation Cycle 3 — Resolution

**Date:** 2026-07-19
**Source report:** `2026-07-19-locus-black-box-validation-cycle-3.md`
**Implementation scope:** GraphGraph installation, diagnostics, response cache,
retrieval/facet compilation, affected-test receipts, tests, and the published
Codex validator
**Comparison tool:** Graphify was not used or integrated.

## Outcome

Cycle 3's release-contract failures and actionable retrieval failures are fixed
in the current source and installed Codex skill. The final validation was run
through:

```text
C:\Users\dcarn\.codex\skills\graphgraph\scripts\validate_live.py
```

against Locus, with two explicit queries and:

```text
cargo test -p locus-engine game_theory::tests --lib
```

Final installed-path receipt:

- packets: 2 / 2 valid;
- queries: 2 / 2 valid and actionable;
- planner gates: 2 / 2 valid;
- focused Locus tests: 13 passed, 0 failed, 0 ignored;
- graph: 13,138 nodes / 46,438 edges;
- overall validator result: pass.

Repository verification:

- focused cycle-3 regressions: 7 passed;
- retrieval/scanner/CLI-MCP suites: 330 passed;
- full pytest: 555 passed plus 57 subtests;
- Ruff: pass.

The installed validator now exposes `--test-command`, `--test-timeout`, and
`--saved-reports`. `graphgraph doctor` reports both the installed Codex skill
contract and live validator as `Current (OK)`.

## Finding ledger

### GG-LOCUS3-001 through GG-LOCUS3-005 — Installed validator contract

**Status:** fixed.

The canonical source already contained most cycle-3 harness behavior, but
`graphgraph install --platform codex` never refreshed
`~/.codex/skills/graphgraph`. The globally published skill therefore invoked a
stale 396-line standalone validator while its `SKILL.md` documented the newer
wrapper contract.

The installer now writes the canonical skill and validator to the global Codex
skill directory. An isolated installation regression starts with deliberately
stale files and requires both installed artifacts to equal the packaged
content. Doctor independently compares the two published artifacts and emits
one deterministic repair command when either is missing or stale.

The installed-path acceptance proves:

- `--test-command` is accepted and recorded exactly;
- Cargo output is parsed as 13 passed, 0 failed, 0 ignored;
- two supplied queries produce exactly two evaluated queries;
- planner gates pass and failed gates retain nonblank diagnostic fields;
- harness queries use the same router/compiler path as normal GraphGraph
  queries.

### GG-LOCUS3-006 — Literal roadmap status evidence

**Status:** already fixed before this sweep and rechecked.

Literal marker queries are typed status operands. Legend prose and conflicting
`[~]`/`[x]` rows cannot satisfy an absent-row request. When no matching
capability row exists, GraphGraph returns an empty packet and an explicit
abstention instead of claiming answerability from the legend.

### GG-LOCUS3-007 — Compound document plus code retrieval

**Status:** fixed.

`From the Game Theory roadmap row` now compiles to one topic-local paragraph
root instead of treating every paragraph in the strict file scope as
interchangeable. When code candidates are also in scope, the compiler preserves
one strongest symbol-level code root and then reserves facet evidence by
structural proximity.

The final Locus query contains:

- the exact Game Theory roadmap row;
- the `mixed_nash_2x2` implementation neighborhood;
- `verify_mixed_nash_2x2`;
- the API-connected dominant/degenerate abstention test.

The route remains `doc_summary`, but test intent now produces a typed hybrid
`affected_tests` receipt. That receipt is why the live validator can prove the
compound response actionable instead of merely noticing a test-shaped node.

### GG-LOCUS3-008 — Explicit blast-radius routing

**Status:** fixed/reconfirmed.

The literal blast-radius query routes to `blast_radius`, not `doc_summary`.
Blast-radius retrieval is now facet-aware, so explicit evidence requirements
participate in answerability instead of being discarded after routing.

### GG-LOCUS3-009 — Requested roadmap evidence in blast radius

**Status:** fixed.

The `roadmap paragraph` facet carries the qualified API identity operands:

```text
roadmap + paragraph + game_theory + mixed_nash_2x2
```

It can no longer be fulfilled by an arbitrary audit paragraph that happens to
live below `docs/roadmap`. On Locus, the natural blast query returns
`docs/roadmap/gap-analysis.md` and the exact Game Theory row. Missing that
grounded row would leave the facet unfulfilled and the receipt incomplete.

### GG-LOCUS3-010 — Present behavior reported missing

**Status:** fixed.

Facet compilation and evidence matching now translate the agent-facing request
to graph-level operands:

- `2×2` and `2x2` normalize to the same term;
- a `returns` edge proves the result-type facet;
- `verify_*` proves self-verification;
- `no solution`, `returns None`, and dominant/degenerate cases are bounded
  abstention forms;
- structural proximity prefers the abstention test calling the selected API
  over a same-file zero-sum test.

The final compound query fulfills all five facets with no missing evidence.

### GG-LOCUS3-011 — Cross-topic roadmap attribution

**Status:** fixed.

Strict document scope is only a file boundary. The named roadmap row is now an
additional topic boundary. The Game Theory query is grounded solely in the Game
Theory paragraph and cannot borrow `up to 20 domain points` from Statistical
Learning Theory.

The bounded-contract matcher recognizes both numeric ceilings and fixed
dimensional shapes. The real `two-player 2×2 general-sum game` phrase now proves
the requested bounded input contract, while `remain absent` proves unsupported
scope.

### GG-LOCUS3-012 — `runs` lexical noise and incomplete command coverage

**Status:** fixed.

The phrase:

```text
smallest exact Cargo command that runs every one
```

compiles to one output-contract facet:

```text
smallest exact command covering all direct tests
```

Operational words are removed from the anchor program, so an unrelated
document containing `one run` cannot become a root. The command selector now
distinguishes root coverage from direct-test coverage and publishes:

- `covered_direct_tests`;
- `uncovered_direct_tests`;
- the selected algorithm contract.

When all direct tests are requested, the broader inline module command wins
over a one-test filter. The final Locus receipt found four direct tests and
selected:

```text
cargo test -p locus-engine game_theory::tests --lib
```

with zero uncovered roots and zero uncovered direct tests.

### GG-LOCUS3-013 — Active versus harness graph reconciliation

**Status:** fixed in the current validator.

The report identifies the harness as an independent full scan, records its
build settings, compares it with the active graph, and categorizes node/edge
deltas. In the final run the two artifacts were identical:

- added nodes/edges: 0 / 0;
- removed nodes/edges: 0 / 0.

### GG-LOCUS3-014 — Concept linking

**Status:** still an explicit product boundary.

No unsupported semantic claim was added. Concept health remains unavailable
when verified linkage is below the published 20% threshold, and retrieval
identifies its lexical/structural fallback mode. Improving foreign-repository
concept links remains separate work; it was not simulated through aliases or
receipt changes in this fix.

### GG-LOCUS3-015 — Codex MCP availability

**Status:** installer artifacts fixed; current-session activation remains a
client boundary.

The global Codex skill and plugin are now refreshed correctly. A process cannot
hot-load MCP operations into an already-running Codex session, so a fresh
session is still required to prove tool exposure. Doctor continues to state
that a bundle on disk is not proof that the current session loaded the MCP
server and preserves CLI fallback as the supported path.

## Additional defect found during resolution

The Locus rerun initially returned an old affected-test receipt even though the
interpreter had loaded the patched module. The persistent response cache keyed
graph state and planner version but not the semantic response contract.

Query responses now carry an explicit semantic cache-contract version. This
invalidates pre-fix whole-response entries while preserving normal cache hits
within one contract version. A regression stores a response under a legacy
contract and proves the current query misses that entry.

## Re-evaluation

The cycle-3 report's 1/10 installed-validator score no longer describes the
published installation: its exact acceptance workload now passes end to end.
The routing, compound retrieval, facet attribution, blast-document grounding,
and affected-test command failures used to justify the 6/10 overall score also
pass their executable regressions and the real Locus queries.

GraphGraph still should not claim semantic/concept support on Locus, and MCP
availability still requires fresh-client verification. Those two residual
boundaries remain visible rather than being folded into a higher unsupported
score.
