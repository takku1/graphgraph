---
name: graphgraph
description: Use GraphGraph for fast graph-backed codebase orientation, dependency/caller/path/blast-radius retrieval, fresh edit-loop context, status, and packet validation.
---

# GraphGraph operational contract

Use GraphGraph across Codex, Claude Code, and other MCP/CLI agents for
structural codebase questions before broad source reading.
MCP and CLI are transports over the same
`SYNC -> EXTRACT -> NORMALIZE IR -> ANCHOR -> EXPAND -> SELECT -> PACK`
instruction set.

For richer workflows, keep the same low-level contract. Use MCP
`compile_context` or CLI `graphgraph platform compile` when evidence providers,
bounded inference, or hierarchy are needed. Memory, temporal episodes,
federation, traces, and repair inputs must be projected into normal GraphGraph
nodes/edges before retrieval; do not reason from a parallel store as if it were
structural evidence. Inspect the returned compiler receipt and validate the
packet.
Normal `context`/`query` calls automatically use the bounded source planner;
use `--source-mode off` only for a structural baseline. Evidence compilation
uses versioned per-source CPG IR and exact merge/truncation receipts.

> [!IMPORTANT]
> **Check availability.** Use `graphgraph/query_context` when that MCP tool is
> registered for this client. Otherwise use the CLI commands below; never
> translate MCP tool names into guessed CLI flags. `graphgraph doctor` reports
> installed frontends and client registration.

> [!IMPORTANT]
> **Audit exclusions before building.** Before the first build, an intentional
> rebuild, or indexing a materially changed repository layout:
>
> 1. Read root and nested `.gitignore`/`.ignore` rules.
> 2. Inspect top-level and unusually large path names. Look for generated/build/
>    cache/coverage outputs, vendors/dependencies, bundles/minified assets,
>    binaries, logs, datasets, copied repos, graph/tool outputs, secret-bearing
>    environment/config files, and temporary investigation corpora. Inspect
>    names/rules without opening secrets.
> 3. Do not blindly exclude tests, fixtures, benchmarks, migrations, or docs;
>    retain them when they provide likely task evidence.
> 4. Record exclusions and reasons. Pass directory names through MCP
>    `build_graph.exclude_dirs` or CLI `scan --exclude`. `include_dirs`/
>    `--include` only overrides a built-in skip name; it is not an allowlist.
> 5. Build only after this audit. Later, `query_context` with `sync: "git"`
>    reconciles paths made stale by new ignore rules.

> **Default query path.** For an existing healthy graph, use
> `query_context`. After edits, pass exact `changed_paths`/`deleted_paths`; if
> that list was lost, pass `sync: "git"`. CLI equivalent:
> `graphgraph context "<query>" --sync git`. Leave `query_class` and node
> budgets automatic unless testing a known policy.

> **Development-loop receipt.** For one machine-readable operation, use
> `graphgraph context "<query>" --changed-files <paths...> --json --validate`.
> The envelope includes refresh and validation state, inferred/explicit scope,
> plan rationale, packet-quality metrics, affected-test recommendations, and
> timings. Compound implementation-and-test questions also report per-facet
> evidence, unfulfilled facets, and the merged path/test intents. A stale
> warning means refresh with `--sync git`; dirty does not mean stale when
> manifest hashes already match.

> **Benchmark discipline.** Do not use expected answer keys or fixture answers
> as evidence. Use retrieved packets, source, docs, and requested command output.

## Tool routing

Route on the **shape of the question**, not on familiarity. Costs are measured
medians on a 14.5k-node Rust workspace.

| Question shape | Tool | Cost |
| --- | --- | --- |
| One named symbol: callers, callees, blast radius, "how does X work" | `query_context` / `query` | 0.4s fast path, 2.4s ranked |
| A predicate over **many** symbols: "which functions have no production caller", counts, existence | `select` | ~0.5s |
| Exact literal string, no relationship | `rg` / `git grep` | — |

`query` **cannot answer set predicates at all** — it anchors on named nodes. Do
not emulate one by looping `query` over a symbol list; that is the failure this
tool exists to prevent (a hand-rolled sweep published two contradictory counts
before `select` existed). Use `label in [...]` for batches.

```
graphgraph select "production_callers = 0 and crate contains locus-engine and include_tests = false" --mode count
graphgraph select "callers > 20" --limit 50            # hubs, not islands
graphgraph select "label in [parse, lower, emit]" --json
```

Grammar: clauses joined by `and`. `production_callers`/`callers` with
`= != > >= < <=`; `kind=K`; `path|crate contains S`; `path|crate != S`;
`label contains S`; `label in [a, b, c]`; `include_tests=BOOL`.
Modes: `select` (rows), `count` (integer), `exists` (boolean). `count`/`exists`
never materialize node payloads — prefer them when the answer is a number.
An unsupported clause raises rather than being silently dropped; a returned
answer is always the whole predicate.

## Decision rules

1. Natural-language structural question about a named symbol: call
   `query_context` first; do not preselect IDs unless the user supplied exact
   files/symbols.
2. Missing graph: audit exclusions, `build_graph`/`scan`, validate, inspect the
   build receipt, then query. Do not let `context` auto-build before the audit.
3. Exact known string with no relationship question: `rg`/`git grep` is valid.
   Prefer GraphGraph for callers, dependencies, paths, blast radius, and “how
   does this work?” orientation, and `select` for anything quantified over the
   whole repository.
4. Focus with CLI `--scope src/path` or MCP `search_nodes` then `final_packet`.
   Explicit scope defaults to `--scope-mode strict`; choose `expand` only when
   structurally connected dependency boundary crossings are useful.
5. Validate saved graphs with `validate_packet` or `graphgraph validate-graph`;
   validate rendered packets with `graphgraph validate`.
6. Treat graph output as orientation evidence; verify final claims against
   source or tests before changing code.
7. Accept a build only after checking: ignore files honored, rule/default paths
   pruned, selected frontend, fallback/failure counts, validation, and file or
   symbol/document truncation. CLI scans emit timed phases, document counts,
   slowest documents, and source-concept timings to stderr. MCP `build_graph`
   returns `frontend`, `exclusions`, and a machine-readable `phase_profile`.
8. For documentation answers, require grounded section/paragraph facts. Treat
   `document_warning`, zero grounded doc nodes, or unfulfilled requested phrases
   as a retrieval failure to narrow, refresh, or report—not a successful heading
   match.
9. Qualify same-named members as `Type::method` in queries. For affected tests,
   inspect each recommendation's `covers` receipt and use the emitted command;
   Rust commands are manifest-derived and distinguish an integration target
   from a module/filter. Execute the focused command before claiming it passes.

## Main operations

| Need | MCP | CLI |
| --- | --- | --- |
| Natural-language packet, optionally fresh | `query_context` | `context "<query>" [--sync git] [--json]` |
| Build after exclusion audit | `build_graph` | `scan --depth symbols --docs --exclude <dirs...>` |
| Exact edited/deleted splice | `query_context` with changed/deleted paths | `update --files ...` / `remove --files ...` |
| Low-level splice tools | `update_graph_files` / `remove_graph_files` — both **require** a `paths` array (repo-relative or absolute) | `update --files ...` / `remove --files ...` |
| Resolve labels/paths | `search_nodes` | `query "<text>" --show-anchors` |
| Packet from known IDs | `final_packet` | `final --query-class <class> --starts <ids...>` |
| Bounded exact source | `source_snippets` | `snippets --starts <ids...>` |
| Whole-repo predicate / counts / batch symbol lookup | `select_symbols` | `select "<predicate>" [--mode count\|exists] [--json]` |
| Project/install health, resolution + staleness receipts | `project_status` | `status --probe` / `doctor` |
| Validate | `validate_packet` | `validate-graph` / `validate` |
| Compile advanced graph passes | `compile_context` | `platform compile` |
| Enforce multi-repo gates | - | `platform benchmark --config <json>` |
| Migrate platform state | - | `platform migrate --directory .graphgraph` |
| Issue/error repair context | `repair_context` | `platform repair` |
| Structural snapshot diff | `graph_change` | `platform change` |
| Scoped memory | `memory_context` | `platform memory` |
| Historical graph view | `graph_at_time` | `platform as-of` |

`full_graph` is an exceptional escape hatch and refuses large graphs by
default. `describe_formats`, `describe_ontology`, `describe_frontends`, and
`describe_traversal` expose the low-level contract. CLI `--starts` belongs only
to `final` and `render`, not `context` or `query`.

Query classes: `direct_lookup`, `reverse_lookup`, `subsystem_summary`,
`blast_radius`, `multi_hop_path`, `affected_tests`, `doc_summary`, `negative_query`, and
`recent_changes` (requires a scan with `--history`). Compact `gg` is the
normal token floor; choose larger formats only for columns they uniquely carry.

## Live validation harness

Run `python scripts/validate_live.py --repo <repo>` from this skill directory
to scan and validate live packets against any repository. The harness derives
default queries from that repository and detects Cargo, Go, npm, pytest, or
unittest tests.

- Override detection with `--test-command "<command>"`.
- Use `--skip-tests` when tests are intentionally out of scope.
- Add repeatable `--query "<question>"` values to replace derived defaults.
- Enable `--saved-reports` only for GraphGraph self-validation; foreign
  repositories do not fail because GraphGraph benchmark reports are absent.

## Reading the output: what each receipt licenses

Every line below is emitted by the tool. Treat them as preconditions on what
you may assert, not as decoration.

| Receipt | Meaning | What you may conclude |
| --- | --- | --- |
| `-- CAVEAT: member-call resolution N%` on `select` | Unresolved member calls emit no `calls` edge | `production_callers = 0` is an **upper bound on dead code, not a proof**. Output is a candidate list requiring per-symbol verification. Never delete on this alone |
| `GraphGraph partial result: node budget omitted N known direct reverse neighbor(s)` | The list was truncated | The answer is **partial**. Re-run with a larger `--max-nodes` before reporting a count or an absence |
| `anchor=exact_fast_path` vs `anchor=ranked` (`query --show-stats`) | Which anchor route ran | `ranked` means the name was ambiguous or absent, and costs ~4x. If you expected one definition, `ranked` says there are zero or several |
| `!  STALE GRAPH: N changed ...` (`status`, `query`) | Files moved since the scan | Refresh before trusting an absence: `context --sync git` |
| `!  STALE: counts were measured by a full scan ...` (`status`) | Member-call telemetry was carried forward | The resolution numbers describe an older scan, not this graph |
| `Unresolved receivers by shape: ...` (`status`) | Why receivers went untyped | Diagnostic for resolver work. Bucket **size is not addressability** — most large buckets iterate generic/stdlib types that can never name a repo symbol |

Current member-call resolution is ~23.8%. A symbol reported with zero callers
may simply be called through an unresolved receiver. This is the single most
important limitation to carry into any dead-code, island, or blast-radius
conclusion.

## Measurement discipline

- `scan` defaults to **incremental**. A resolver- or extractor-level change
  affects every file, not only changed ones, so an incremental scan shows
  almost no delta and the change appears to have done nothing. Measure with
  `graphgraph scan --depth symbols --docs --no-incremental`.
- `status` reports member-call counts from the last **full** scan and prints a
  `STALE` line when they were carried forward. Numbers without that line are
  current; numbers with it are not.
- `query --show-stats` prints the execution receipt to stderr (packet still on
  stdout). Use it to attribute latency: `anchor=exact_fast_path` skips the
  lexical index build, `anchor=ranked` pays it.
- Warm and cold query latencies differ ~6x. Compare like with like; a
  first-run number is not a steady-state number.

## Noise and receipt rules

Defaults skip VCS, environments, dependencies, builds, caches, generated agent
artifacts, local agent/MCP configuration, graph outputs, vendors, and cloned
references. These defaults are a safety floor, not proof of a clean graph.
Prefer excluding reproducible derivatives while retaining source-of-truth and
relationship-bearing tests/docs. Ignore-matched directories must be reported
as pruned before descent; a scan that merely walks and discards every ignored
file is a performance bug.
`doc_summary` may carry bounded paragraph spans beneath selected headings; use
its grounding telemetry to distinguish an answer from a heading-only match.
