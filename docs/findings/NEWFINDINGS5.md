# New Findings

Investigation date: 2026-07-24  
Environment: Linux, Python 3.12.3, GraphGraph 0.1.0

> **Resolution (2026-07-25):** GG-NEW-001 is fixed. `docs/new-helpful-concepts.md`
> now links to the committed benchmark scripts (`real_project_packet_balance.py`,
> `frontier_policy_benchmark.py`) instead of the git-ignored `out/` reports, and
> the summarized evidence remains linked via `docs/empirical-findings.md`. The
> full documentation-contract suite passes on a clean checkout. No other defect
> in this report required a code change.

## Summary

I found one confirmed repository defect:

| ID | Severity | Area | Result |
| --- | --- | --- | --- |
| GG-NEW-001 | Medium | Documentation / clean-checkout CI | Two committed Markdown links target generated files that are ignored and absent |

After rebuilding the self-graph with the intended tree-sitter frontend, all
runtime, scanner, retrieval, calibration, CLI/MCP/HTTP parity, and static
analysis checks passed. The final full suite result was:

- 805 passed
- 4 skipped
- 1 failed
- 69 subtests passed
- 810 tests collected

The single failing test is the confirmed finding below.

## GG-NEW-001: Committed documentation links to absent, ignored benchmark output

**Severity:** Medium

**Affected file:** `docs/new-helpful-concepts.md`, lines 43-44

The page links to:

```text
../benchmarks/context_graph/out/real_projects/real_project_packet_balance.md
../benchmarks/context_graph/out/real_projects/frontier_policy_report.md
```

Neither target exists in this checkout. More importantly,
`.gitignore` line 28 excludes the entire `benchmarks/context_graph/out/`
directory. A clean clone therefore cannot contain these targets through the
normal tracked-file workflow.

### Impact

- Readers receive two broken links from a committed documentation page.
- The page says its claims are supported by those benchmark outputs, but a
  reader of a clean checkout cannot inspect that evidence.
- The repository's own documentation contract fails:
  `DocumentationContractTest.test_local_markdown_links_resolve_without_file_uris`.
- CI will remain red whenever it runs the complete suite on a clean checkout.

### Reproduction

From the repository root:

```bash
.venv/bin/python -m pytest -q \
  tests/test_docs_contract.py::DocumentationContractTest::test_local_markdown_links_resolve_without_file_uris
```

Observed result:

```text
docs/new-helpful-concepts.md links missing path
'../benchmarks/context_graph/out/real_projects/real_project_packet_balance.md'

docs/new-helpful-concepts.md links missing path
'../benchmarks/context_graph/out/real_projects/frontier_policy_report.md'
```

Direct filesystem checks also confirm that both files are absent.

### Root cause

The committed documentation treats transient benchmark output as a durable
documentation target, while repository policy explicitly excludes that output
directory.

### Suggested fix

Choose one durable source of truth:

1. Move the two reviewed reports to a committed location such as
   `benchmarks/context_graph/canonical_results/` and update the links; or
2. Replace the links with committed evidence already summarized in
   `docs/empirical-findings.md`, plus links to
   `benchmarks/context_graph/real_project_packet_balance.py` and
   `benchmarks/context_graph/frontier_policy_benchmark.py` for reproduction.

Do not merely remove the ignore rule for all of `out/`; it is documented as a
large generated-output directory.

## Environment and dependency setup

A new `.venv` was created at the repository root. The project was installed
editable with its runtime and development requirements.

Key installed packages:

| Package | Version |
| --- | --- |
| graphgraph | 0.1.0 |
| pytest | 9.1.1 |
| ruff | 0.16.0 |
| tree-sitter | 0.26.0 |
| tree-sitter-language-pack | 1.10.9 |
| pathspec | 1.1.1 |
| keyring | 25.7.0 |
| tiktoken | 0.13.0 |

`pip check` reported: `No broken requirements found.`

## Verification performed

### Static analysis

```bash
.venv/bin/ruff check .
```

Result: `All checks passed!`

### Full test suite

The final suite was run with loopback sockets enabled because four integration
tests start local HTTP servers.

Result: 805 passed, 4 skipped, 1 failed, with the only failure being
GG-NEW-001.

### Graph build and validation

The repository was scanned with:

```bash
.venv/bin/graphgraph scan \
  --directory . \
  --depth symbols \
  --frontend tree_sitter \
  --docs \
  --exclude .agents plugins .codex \
  --no-incremental \
  --output .graphgraph/graph.gg
```

Build receipt:

- 8,943 nodes
- 32,833 edges
- tree-sitter frontend
- 0 parse fallbacks
- 0 parse failures
- 358 resolved member calls
- structural validation passed

An independent validation also passed:

```text
STRUCTURAL PASS graph.gg nodes=8943 edges=32833
```

A validated reverse lookup for `select_symbols` used the exact fast path and
returned both real callers, `cmd_select` and `handle_select_symbols`.

### Self-evaluation and calibration

`eval/graphgraph-self.json` passed its intended behavior:

- all four hand-verified caller queries had node recall 1.0;
- the deliberately nonexistent red-test symbols had node recall 0.0.

`eval/graphgraph-calibration.json` produced ECE 0.067317, below the required
0.10 gate.

### Distribution and runtime health

- `graphgraph artifacts --check`: passed.
- CLI import and `python -m graphgraph --help`: passed.
- Package console commands: present.
- All configured tree-sitter language grammars: ready.
- Offline semantic retrieval correctly selected the documented hash fallback
  because no external embedding backend was configured.

## Investigated failures that were not program bugs

These were reproduced and then ruled out:

1. **Network-denied tiktoken failures.** The first sandboxed run could not
   download tiktoken's encoding data. After the one-time download was allowed,
   all affected acceptance tests passed.
2. **Loopback socket permission failures.** Four HTTP integration tests failed
   only while the sandbox prohibited opening local sockets. They passed when
   rerun with loopback access.
3. **Self-eval and calibration failures on a regex graph.** An initial graph
   used the regex frontend and therefore had no typed member-call evidence.
   Rebuilding from scratch with the documented tree-sitter frontend made all
   caller-recall and calibration gates pass. This was an invalid analysis
   precondition, not a source defect.

## Second bug pass

**Pass date:** 2026-07-24  
**Outcome:** No additional confirmed bugs were found.

This was a separate second bug pass, not just another execution of the first
pass's full-suite command. GG-NEW-001 remains the only confirmed defect in this
report.

### Additional coverage

#### Clean wheel build and isolated installation

I built `graphgraph-0.1.0-py3-none-any.whl`, inspected its contents, and
installed it with dependencies into a separate disposable virtual environment.
The wheel contained:

- all GraphGraph Python packages;
- both console-script entry points;
- the graph schema;
- the packaged skill, MCP settings, and live-validation assets;
- package metadata and license data.

From outside the source checkout, the installed wheel then:

- imported successfully;
- reported version 0.1.0;
- passed `pip check`;
- scanned a new two-file sample project with tree-sitter;
- produced a structurally valid graph;
- retrieved the real `run -> helper` caller relationship;
- produced a packet whose mechanical and semantic receipt validation passed.

All 166 modules discovered in the installed wheel imported successfully.
Additionally, all 26 top-level CLI subcommands loaded their `--help` paths
without an import or parser failure.

#### Hash-seed determinism

The retrieval, evaluation, packet, and tree-knapsack tests were run under both
`PYTHONHASHSEED=1` and `PYTHONHASHSEED=987654`.

- 147 tests passed under the first seed.
- The same 147 tests passed under the second seed.
- `eval/graphgraph-self.json` produced byte-identical JSON for both seeds.
- All four real self-eval queries retained node recall 1.0.
- The deliberate red test retained node recall 0.0.

No ordering-dependent behavior was found.

#### Warning and bytecode checks

- Every Python file under `src/`, `scripts/`, and `benchmarks/`, plus
  `setup_graphgraph.py`, passed `compileall`.
- 196 graph-core, I/O, scanner, frontend, and delta-storage tests passed with
  Python warnings promoted to errors.
- The project's configured Ruff rules remained clean.

I also ran Ruff's additional bug-oriented `B` and `PLE` rule sets. They emitted
advisories that are not enabled by the project configuration. The highest
signal candidates were late-bound-closure warnings in
`retrieval/anchors.py` and `retrieval/facets.py`. Source inspection confirmed
that each local callback is created and consumed immediately within the same
loop iteration; neither callback escapes the loop, so later iteration binding
cannot affect it. The remaining diagnostics were exception-chaining,
explicit-`zip`, unused-loop-variable, or equivalent maintainability/style
advisories. None produced incorrect runtime behavior in targeted tests.

#### Packaged live validator

The repository's packaged live-validation harness was run with a reverse
caller query for `select_symbols`.

```text
packets: 1/1 valid
queries: 1/1 valid
gates:   2/2 valid
overall: passed
```

The generated validation graph contained 9,110 nodes and 33,482 edges.

### Second-pass conclusion

No new bug ID was added because every new candidate either passed independent
reproduction or was shown not to affect runtime behavior. The broken,
ignored-output documentation links described in GG-NEW-001 remain
reproducible and unresolved.

## Scope notes

- No source-code fixes were applied; this task requested bug findings and a
  report.
- `.venv/` and `.graphgraph/` are ignored local analysis artifacts.
- Repository Git history was unavailable in this supplied workspace because
  its `.git` metadata is incomplete; history-based diagnostics were therefore
  not used as evidence.
