# Locus Black-Box Validation Cycle 2 — Resolution

**Date:** 2026-07-19
**Source report:** `2026-07-19-locus-black-box-validation-cycle-2.md`
**Implementation scope:** GraphGraph source, tests, packaged live validator, and
public diagnostics
**Comparison tool:** Graphify was not used or integrated.

## Outcome

Cycle 2's actionable retrieval, command, and validator defects are resolved in
the current GraphGraph source. The final live run against Locus passed:

- query packets: 2 / 2;
- query actionability: 2 / 2;
- planner gates: 2 / 2;
- Cargo tests: 5 passed, 0 failed, 0 ignored;
- selected command:
  `cargo test -p locus-engine learning_theory::tests --lib`;
- structural graph validation: pass.

The scanner fix also recovered 736 Rust calls hidden inside macro token trees in
the independent Locus graph. This is a topology improvement, not merely a
receipt workaround.

Two boundaries remain explicit:

1. source-concept linkage is still too sparse to support semantic-graph claims;
   GraphGraph now publishes a 20% minimum support threshold and declares the
   feature unavailable/sparse below it;
2. a plugin bundle on disk cannot hot-load an MCP server into an already-running
   Codex session. Doctor now says so and provides the reinstall plus fresh-session
   verification command.

## Finding ledger

### GG-LOCUS2-001 — Broad documentation retrieval

**Status:** fixed and recalibrated.

Broad absent-capability requests now compile to literal Markdown status markers.
Only capability-shaped rows count; legend text such as
`` `[ ]` absent or not reliable enough to claim `` is rejected.

The current Locus `gap-analysis.md` no longer contains a real `[ ]` capability
row after Statistical Learning Theory moved to `[~]`. GraphGraph therefore
returns an explicit abstention:

```text
no literal absent capability rows were found in the requested roadmap documents
```

This satisfies the acceptance contract's second branch instead of fabricating a
capability from the checkbox legend.

### GG-LOCUS2-002 — Malformed facets

**Status:** fixed.

The facet compiler now emits:

- `bounded input contract`, never `bounded input contract have`;
- `covered cases`, never `cases they`.

Numeric contract language such as `up to 20 domain points` fulfills the bounded
input facet. Covered-case evidence is taken from structural test edges rather
than unrelated prose.

### GG-LOCUS2-003 — Changed documentation omitted from blast radius

**Status:** fixed.

Markdown, RST, HTML, and text files are valid exact changed-path roots. The
three-path Locus acceptance run returned:

- `learning_theory.rs`;
- `lib.rs`;
- `gap-analysis.md`.

All three appeared both as roots and actionable change points. The changed
roadmap receipt is `primary_root`, not a lexical fallback.

### GG-LOCUS2-004 — Incomplete affected-test command

**Status:** fixed.

Command selection now considers both exact test filters and aggregate inline
Rust module filters. It greedily covers requested roots, broadens when needed,
and lets a changed-path module command supersede a narrower command only when
the broader command covers more tests.

On final Locus verification:

- exact roots: `finite_vc_dimension`, `shatters`;
- direct tests: all 5;
- command: `cargo test -p locus-engine learning_theory::tests --lib`;
- uncovered roots: 0;
- the narrower one-test command is recorded under
  `superseded_commands`.

When topology is incomplete but a module command is safe, the receipt separates
structurally uncovered roots from roots verified by bounded inline-test source
inspection.

### GG-LOCUS2-005 — Generic `runs` benchmark anchor

**Status:** fixed.

Affected-test anchor compilation strips operational prose and compiles exact
symbols as the anchor program. Output-contract facets such as `runs`,
`exercise`, and `covered cases` cannot become implementation anchors.

Unique exact symbol-table labels also outrank inflectional relatives. This
prevents `shatters` from resolving to `shattered_points`.

### GG-LOCUS2-006 — Concept linking at zero or near zero

**Status:** calibrated; underlying semantic breadth remains intentionally open.

GraphGraph now publishes:

- `minimum_supported_coverage_ratio: 0.20`;
- `supported: true|false`;
- `status: unavailable|sparse|partial|strong`;
- a machine-readable `diagnostic_reason`;
- the lexical fallback mode used by retrieval.

Zero links are `unavailable`, not an active semantic capability. The current
GraphGraph self-graph reports 28 / 2,391 linked nodes (1.17%), classifies this
as `sparse`, and states that it is below the 20% semantic-evidence threshold.
No unsupported semantic claim is made.

### GG-LOCUS2-007 — Cargo tests not detected by live validator

**Status:** fixed in current source; the report exercised a stale installed
harness.

The canonical harness detects root Cargo workspaces and supports an explicit
override. Test receipts now include:

- exact command;
- return code;
- passed, failed, and ignored counts;
- duration;
- zero-test rejection.

Final Locus receipt: 5 passed, 0 failed, 0 ignored, return code 0.

### GG-LOCUS2-008 — Supplied queries appended to defaults

**Status:** fixed in current source.

Repeatable `--query` values replace derived defaults. The final run supplied two
queries and evaluated exactly two queries.

### GG-LOCUS2-009 — Planner gates lack reasons

**Status:** fixed in current source.

Every failed gate carries:

- expected packet format/edge predicate;
- observed format/count;
- machine-readable errors;
- non-empty `failure_reason`.

The final Locus run passed both gates.

### GG-LOCUS2-010 — Skill/harness flag drift

**Status:** fixed in current source.

All three shipped harness entry points are byte-identical and expose:

- `--repo`;
- `--max-nodes`;
- repeatable `--query`;
- `--skip-tests`;
- `--test-command`;
- `--test-timeout`;
- `--saved-reports`.

The canonical skill and installed help now agree.

### GG-LOCUS2-011 — Active and harness graphs unexplained

**Status:** fixed.

The harness explicitly identifies itself as an independent full scan and now
loads the active graph for a categorized identity delta.

Final Locus comparison:

- active: 11,094 nodes / 47,577 edges;
- live: 12,674 nodes / 45,959 edges;
- added nodes: 1,587 documentation;
- removed nodes: 7 documentation;
- added edges: 2,460, including 736 `calls`;
- removed edges: 4,078, including 3,944 `references`.

The report also records both build settings and graph artifact paths. Counts are
no longer presented as if the snapshots were directly equivalent.

### GG-LOCUS2-012 — Codex MCP integration

**Status:** installer and diagnostics fixed; current-session activation requires
client restart.

The repository carries a valid Codex plugin bundle and one-step repair command:

```text
graphgraph install --project --platform codex
```

Doctor no longer claims that a bundle on disk proves the running Codex session
loaded its MCP server. It instructs the user to start a fresh Codex session and
verify that `graphgraph/query_context` is exposed. CLI fallback remains valid
until then.

## Additional defect found during resolution

### Rust calls inside macro token trees

Two Locus tests called `finite_vc_dimension` or `shatters` inside `assert!` /
`matches!` macro token trees. Tree-sitter intentionally leaves those expressions
unparsed, so the normal `call_expression` walker could not see them.

GraphGraph now performs a bounded token-tree pass:

- accepts an identifier immediately followed by a parenthesized token tree;
- rejects macro heads followed by `!`;
- rejects method/path continuations preceded by `.` or `:`;
- resolves only through the existing callable symbol table;
- emits `tree_sitter_macro_token_tree` provenance at reduced confidence.

This recovered all five direct Locus learning-theory tests and added 736 real
call edges in the final independent scan.

## Verification

- complete GraphGraph test suite: pass;
- Ruff across all changed Python files: pass;
- focused retrieval, scanner, planning, CLI, and harness suites: pass;
- Locus three-path refresh: approximately 2 seconds, zero stale paths;
- Locus affected-test query: answerable, two exact roots, five direct tests,
  one complete module command, zero uncovered roots;
- Locus live harness: overall pass;
- `git diff --check`: pass.
