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

## Decision rules

1. Natural-language structural question: call `query_context` first; do not
   preselect IDs unless the user supplied exact files/symbols.
2. Missing graph: audit exclusions, `build_graph`/`scan`, validate, inspect the
   build receipt, then query. Do not let `context` auto-build before the audit.
3. Exact known string with no relationship question: `rg`/`git grep` is valid.
   Prefer GraphGraph for callers, dependencies, paths, blast radius, and “how
   does this work?” orientation.
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
| Project/install health | `project_status` | `status --probe` / `doctor` |
| Validate | `validate_packet` | `validate-graph` / `validate` |
| Compile advanced graph passes | `compile_context` | `platform compile` |
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
