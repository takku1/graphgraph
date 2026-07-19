# Acceptance harness

Black-box gate checks for the GraphGraph 10/11 acceptance spec
(`docs/bugs/2026-07-19-graphgraph-10-11-acceptance-spec.md`). It drives
GraphGraph only through its public native retrieval surface, parses the compact
`#gg` packet, and scores it against sealed ground truth — ground truth is
used only to score a packet that was already produced, never fed back as a
retrieval seed.

## Run

```bash
graphgraph platform acceptance --repo ../locus
graphgraph platform acceptance --repo ../locus --json
graphgraph platform acceptance --repo ../locus --case GG10-LC-003
graphgraph platform acceptance --repo ../locus --output acceptance/out/scoreboard.md
GG_ACCEPT_EXEC=1 graphgraph platform acceptance --repo ../locus
graphgraph platform quality
```

`python -m graphgraph.acceptance run ...` is the equivalent package-level
entry point. Exit code is `1` while any P0/P1 case has failed
(`release_floor = blocked`) or still lacks evidence (`release_floor = pending`).
Only a clear release floor exits `0`.

`GG_ACCEPT_EXEC=1` enables recommended test commands. Without it, execution
gates remain `PENDING`; the board never claims a command is valid merely because
it was emitted. On PowerShell, set `$env:GG_ACCEPT_EXEC = "1"` first.

`graphgraph platform quality` runs hermetic token/recall/precision fixtures
against the committed deterministic baseline. Real tokenizer counts remain
telemetry; the regression unit is GraphGraph's environment-independent proxy.
Token growth beyond tolerance fails unless recall or precision improves.

## Layout

| File | Role |
| --- | --- |
| `tasks.py` | Canonical GG10-LC cases + sealed `GroundTruth`. |
| `runner.py` | Drives `render_native_context`, parses the packet, records a reproducible graph identity. |
| `service.py` | Shared application service used by both CLI entry points; rejects unknown cases and writes requested reports. |
| `gates.py` | Total `(probe, task) -> GateResult` primitives. Inapplicable gates return `NA`. |
| `model.py` | Plain-data model; `ProbeResult.irrelevant_ratio` flags containment-only sibling nodes. |
| `test_exec.py` | Multi-language command execution and selected-test classification; zero-selected success is a failure. |
| `affected_tests_case.py` | Type/reference evidence, exact-test requirements, minimum-cover commands, and optional live execution. |
| `tokens.py` | Worse-of `cl100k`/`o200k` when `tiktoken` is present, labelled proxy otherwise. |
| `scoreboard.py` | Markdown/JSON with the `release_floor` rule (a high pass-rate cannot hide an open P0/P1). |

## Gates

- `required_call_edges` — required relationships exist as typed `calls` edges, not merely matching prose.
- `callees_present` / `symbols_present` — required grounded node labels or source-path fragments are in the packet.
- `no_false_complete` — a packet may claim complete only if every required symbol is present.
- `completeness` — the answerable/incomplete decision matches the task's expectation.
- `token_ceiling` — packet within the task's token budget (worse encoder controls).
- `irrelevant_ratio` — ≤10% of nodes are sibling noise (reachable only via `contains`).
- `packet_count_parity` — JSON receipt counts agree with the parsed packet.
- `required_tests` / `type_reference_evidence` — test recommendations satisfy sealed structural contracts.
- `command_selects_test` — an executed recommendation selected at least one test; skipped execution is pending.

The GG10-LC-011 hermetic case separately compares the complete logical packet
across CLI plain text, CLI JSON, and MCP transports.

## Adding a case

Add a `Task` to `tasks.py`. Establish ground truth from repository source (not
from a GraphGraph packet), keep it sealed in `GroundTruth`, and leave the case
`pending` until its ground truth is mechanically codified. Runtime-dependent
evidence should use a `PENDING` gate, never `NA` or a synthetic pass. Hermetic
mechanics are locked in `tests/test_acceptance.py`; the Locus integration tests
skip when the graph is absent.
