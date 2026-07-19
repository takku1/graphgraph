# Locus Black-Box Validation — Remediation Retest

**Date:** 2026-07-19

This is the source-informed resolution ledger for
`2026-07-19-locus-black-box-validation.md`. The original report remains the
pre-fix observation record.

## Outcome

The high-risk trust failures were reproduced against the Locus graph, fixed
behind regressions, and retested through the public CLI.

The most important change is not that every broad query is now complete. It is
that GraphGraph distinguishes three cases:

1. grounded evidence satisfies the request;
2. relevant evidence exists but the packet is incomplete or truncated;
3. no grounded evidence supports an answer.

The second and third cases must not be presented as answerable.

## Black-box acceptance retest

| Target | Result | Evidence |
|---|---|---|
| Exact Stochastic Processes roadmap row | **PASS** | `doc_summary` selected `gap-analysis.md:60` after a one-file refresh |
| Implemented/unproved roadmap facets | **PASS** | Both facets fulfilled; actionable status became `answerable` |
| Explicit Markdown path routing | **PASS** | Automatic route is `doc_summary` with reason `explicit document path and summary intent` |
| Explicit Markdown path scope | **PASS** | Embedded path compiles to strict `docs/roadmap/gap-analysis.md` scope |
| Zero-grounding answerability | **PASS** | `doc_summary` with zero grounded body nodes is `incomplete` and abstains |
| Registration/test facet consistency | **PASS** | Registration and exercise facets consume selected structural evidence |
| Positive behavior test discovery | **PASS** | All three stochastic-process tests are direct, including `markov_gemv_emits_refutable_transition_hypothesis` |
| Focused Cargo command | **PASS** | `cargo test -p locus-advisors --test suite stochastic_processes_test` |
| Directory integration target | **PASS** | `tests/suite/main.rs` maps to `--test suite`, never `--test main` |
| Cargo wildcard workspace | **PASS** | Locus status reports six resolved members for `members = ["crates/*"]` |
| Harness flag parity | **PASS** | Published wrapper exposes `--test-command`, `--test-timeout`, and `--saved-reports` |
| Harness explicit queries | **PASS** | Supplied queries replace derived defaults |
| Harness Cargo detection | **PASS** | Root `Cargo.toml` selects `cargo test --workspace` |
| Planner-gate diagnostics | **PASS** | Failed predicates produce non-empty expectation/actual reasons |
| Global topology calibration | **PASS** | Call-dependent Locus packets report local and global coverage; current global status is `low` |
| Concept-link calibration | **PASS/PARTIAL** | Full-graph scope and lexical fallback are explicit; concept coverage itself remains sparse |

## Defect ledger

### GG-LOCUS-001 — Documentation misrouting and false answerability

**Status: resolved**

- Exact Markdown paths plus summary/incomplete/acceptance wording receive a
  strong `doc_summary` route prior.
- A graph-known document path embedded in the query becomes strict retrieval
  scope.
- `doc_summary` with zero grounded section/paragraph facts is forced to
  `incomplete` with abstention.
- Router and planner contract versions were advanced so persistent response
  caches cannot reuse packets produced by the older semantics.

The route may still return incomplete for a genuinely broad enumeration. That
is correct behavior when the bounded packet does not satisfy every requested
facet.

### GG-LOCUS-002 — Exact Markdown bullet missed

**Status: resolved**

Root cause: Markdown paragraph extraction split ordered list items but collapsed
consecutive unordered `*`, `-`, and `+` items into one paragraph. The bounded
fact field then truncated later bullets even though source snippets could still
read the section.

The scanner now:

- recognizes ordered and unordered Markdown list markers;
- creates one paragraph node per list item;
- strips either marker from the paragraph label;
- handles list content immediately after a heading without requiring a blank
  line.

The Locus row at line 60 is now its own grounded paragraph node.

### GG-LOCUS-003 — Facets contradicted selected topology

**Status: resolved**

Facet coverage now accepts relationship evidence for relationship-shaped
facets:

- registration is supported by registry/default/domain functions referencing
  the requested root;
- exercise is supported by selected test calls/references to the root or one of
  its owned methods.

Reverse test-oriented lookup also promotes owned behavior methods such as
`examine` and admits direct `calls`, `references`, and `tests` edges. A response
can still be incomplete when the reverse-neighbor budget omits known neighbors;
that is a separate, valid completeness gate.

### GG-LOCUS-004 — Invented Cargo target `main`

**Status: already resolved before this sweep; regression strengthened**

Manifest-aware target derivation recognizes
`tests/<target>/main.rs` as the `<target>` integration binary. A direct
regression now covers the changed-path form.

### GG-LOCUS-005 — Positive behavior test omitted

**Status: resolved**

Affected-test traversal treats a requested type's directly owned methods as
root behavior surfaces. Tests calling those methods cover the owning type at
distance one.

The Locus retest returns all three direct tests:

- `markov_gemv_emits_refutable_transition_hypothesis`;
- `generic_matrix_vector_product_stays_silent`;
- `transition_names_do_not_override_wrong_structure_or_semiring`.

### GG-LOCUS-006 — Cargo wildcard workspace reported as one member

**Status: resolved**

Project status now expands workspace member globs against directories containing
`Cargo.toml`, applies `workspace.exclude`, preserves declared pattern order, and
reports both:

- resolved `members`;
- raw `member_patterns` and `exclude_patterns`.

Locus now reports `members=6`.

### GG-LOCUS-007 through GG-LOCUS-011 — Live harness drift

**Status: already resolved before this sweep; verified**

The current harness:

- exposes `--test-command` and `--test-timeout`;
- delegates to the Python environment owning the installed `graphgraph`
  launcher when the caller cannot import the package;
- detects Cargo workspaces with `cargo test --workspace`;
- treats a successful command selecting zero tests as failure;
- replaces defaults when explicit `--query` arguments are supplied;
- records every failed gate predicate in `failure_reason`.

The published skill wrapper and installed implementation are covered by parity
tests.

### GG-LOCUS-012 — Active/live edge-count difference unexplained

**Status: resolved diagnostically**

The harness receipt now declares `graph_mode=independent_full_scan`,
`active_graph_comparable=false`, and explains that it uses its own exclusions,
`generic_mentions=false`, no history, and no previous incremental snapshot.
Therefore its edge count is not expected to equal the active project graph.

This does not claim the two graphs are equivalent.

### GG-LOCUS-013 — Transient import failure during concurrent editing

**Status: not reproduced; development-race classification retained**

The remaining `scanner/core.py` edit was audited, syntax-checked, linted, and
tested before publication. The change itself is valid: only
`SOURCE_SUFFIXES` enter source-symbol extraction, while documents use the
document extractor.

An editable install can still observe a file while an external editor performs
a non-atomic write. GraphGraph cannot make an arbitrary editor atomic. Release
and production use should prefer immutable installed artifacts; repository
automation should use atomic patch/write operations.

### GG-LOCUS-014 — Project/Codex MCP registration absent

**Status: supported, project action remains explicit**

`graphgraph install --project --platform codex` is the one-command project
installation path. Installation tests verify the complete Codex plugin,
portable `graphgraph-mcp` entry, skill parity, and marketplace metadata.

The tool does not silently mutate an unrelated project's MCP configuration
during ordinary queries.

### GG-LOCUS-015 — Global call topology partial

**Status: calibration resolved; extraction coverage remains partial**

Call-dependent packets now combine:

- selected-packet call trust;
- global resolved, ambiguous, unknown-receiver, and unmatched call counts.

A locally clean slice cannot claim high topology trust when repository-wide call
resolution is low. The Locus retest reports:

- local status where applicable;
- global coverage ratio;
- global status `low`;
- scope `selected_packet+global_extraction`.

Improving receiver/type resolution remains separate extraction work.

### GG-LOCUS-016 — Concept linking sparse

**Status: telemetry corrected; semantic coverage remains open**

Incremental updates previously overwrote concept coverage with only the changed
files' counts. The scanner now recomputes the final full-graph concept snapshot
after restoring unchanged nodes and edges, while retaining a separate
`last_update` receipt.

Retrieval quality reports:

- full-graph linked/eligible counts;
- coverage status;
- telemetry scope;
- `lexical_document_fallback` or `lexical_structural_fallback` when concept
  coverage is sparse.

This is a trust fix, not a claim that concept coverage is now sufficient.

## Scanner core audit

The concurrent `scanner/core.py` change is correct after cleanup:

```text
source-symbol extractor input = SOURCE_SUFFIXES
document extractor input      = DOC_SUFFIXES
```

Previously, `PARSEABLE_SUFFIXES` included Markdown/HTML formats, so documents
could also be passed through the source-language frontend. The change removes
that cross-domain work. A capturing-extractor regression proves that `app.py`
reaches source extraction while `README.md` does not, and also proves the
document section still exists.

## Verification commands

```text
python -m pytest tests/test_scanner.py tests/test_retrieval.py
python -m pytest tests/test_planning.py tests/test_cli_mcp.py tests/test_live_validation.py
ruff check <changed Python files and tests>
python .agents/skills/graphgraph/scripts/validate_live.py --help
graphgraph status
graphgraph context "<Stochastic Processes query>" --query-class doc_summary --scope docs/roadmap/gap-analysis.md --json --validate
graphgraph context "<affected tests query>" --query-class affected_tests --json --details --validate
```

Focused suites and lint pass. Full-suite and executable acceptance results are
recorded at publication time.

## Remaining work

1. Improve Rust receiver/type resolution; calibration now exposes the gap but
   does not create missing call edges.
2. Improve concept coverage with measured, closed-world linking strategies.
3. Reduce broad reverse-query noise from trait-wide implementor expansion while
   preserving completeness receipts.
4. Add an immutable installed-artifact concurrency stress test if editable
   source races recur outside active development.
