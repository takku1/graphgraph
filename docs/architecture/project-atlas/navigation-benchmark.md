# Project atlas and navigation benchmark

Status: first vertical slice implemented on 2026-08-01. This is an
implementation and measurement note, not evidence that the research
hypotheses have passed on held-out repositories.

## Outcome

GraphGraph now has a deterministic, source-grounded cold-orientation view:

```powershell
graphgraph orient
graphgraph orient --json
graphgraph orient --json --pretty
```

MCP clients use the existing `project_status` tool with `view: "atlas"`. This
keeps the public surface at 24 tools and the recurring compact tool schema at
11,994 characters (2,999 proxy tokens), below the 12,000-character gate. A
separate twenty-fifth tool was rejected by that gate.

The atlas returns:

- manifest-grounded project identity, ecosystems, and executable entry points;
- production languages derived from indexed source paths;
- path-defined subsystems with exact symbol, path, kind, and line evidence;
- typed cross-subsystem coupling with a concrete edge witness;
- indexed test roots and manifest-derived or explicitly marked candidate test
  commands;
- validation, freshness, truncation, and exclusion receipts;
- omitted-row and phase-timing receipts.

It is a derived view over the saved graph and manifests, not a second truth
store. The default is an explicit 8,000-character evidence budget, not fixed
subsystem/coupling row counts. A prerequisite-aware greedy optimizer maximizes
indexed-symbol and typed-coupling coverage per serialized character. Selecting
a coupling pays for both endpoint subsystem rows if they are not already
present. Optional row caps remain available as hard operational constraints;
omissions and the binding constraint remain visible in the receipt.

## Constants policy

An unexplained number is a hypothesis. New and existing values should be
classified before they are changed:

1. **Structural invariant:** determined by the data/claim contract, such as
   requiring at least one source witness for a named subsystem. Keep fixed and
   test it as an invariant.
2. **Resource budget:** supplied by the caller or product envelope, such as
   source lines, wall time, or output characters. Keep explicit in the request
   and receipt; do not pretend data can infer the user's cost ceiling.
3. **Normative preference:** trade-off weights in navigation loss. Version and
   serialize the profile. These can be chosen or sensitivity-tested, but a
   hidden fitted model cannot turn a preference into a fact.
4. **Empirical threshold:** a value intended to predict quality or cost. Fit it
   on training repositories, validate it on held-out strata, attach provenance,
   and reject it when a graph/task-shaped formula or dominance rule performs as
   well.
5. **Derived quantity:** compute directly from graph shape, measured costs, or
   constraints. Prefer this over a tuned constant when the additional runtime
   is immaterial.

The atlas row caps were category 4 masquerading as defaults and have been
removed. Selection now uses exact candidate byte costs and exact shares of
indexed symbols/cross-subsystem edges. The 8,000-character default remains a
category-2 product budget and is exposed as `--evidence-budget-chars`.

The default navigation-loss weights remain category 3 by design. Every report
contains them, and a profile file can replace them; adapting them silently to
make one retriever win would invalidate the comparison.

## Executable equal-budget evaluation

The research loss and SWE-Explore-style line-budget protocol now have a local
scorer:

```powershell
graphgraph navigation-eval --tasks eval/navigation-tasks.json `
  --runs eval/navigation-runs.json --pretty
```

Task qrels are independent of the tested strategy:

```json
{
  "tasks": [{
    "id": "cold-1",
    "stratum": "cold_orientation",
    "relevant_regions": [
      {"path": "src/pkg/api.py", "start_line": 1, "end_line": 40}
    ],
    "facets": ["languages", "entry_points", "tests", "subsystems"],
    "budget": {
      "source_lines": 200,
      "tokens": 2000,
      "actions": 12,
      "milliseconds": 30000
    }
  }]
}
```

A run records observations and costs, not answer keys:

```json
{
  "runs": [{
    "task_id": "cold-1",
    "strategy": "rg+get-content",
    "regions": [
      {"path": "src/pkg/api.py", "start_line": 1, "end_line": 20}
    ],
    "facets": ["languages"],
    "source_lines": 160,
    "tokens": 1400,
    "actions": 9,
    "milliseconds": 8000,
    "complete_claimed": false,
    "abstained": false,
    "unsupported_claims": 0,
    "freshness_risk": 0
  }]
}
```

The report includes line coverage, area under the evidence-coverage/line-budget
curve, MRR, nDCG@10, facet completeness, budget compliance,
false-complete/false-incomplete counts, and an explicit navigation loss. The
default interactive-orientation weights are serialized in every result and can
be replaced by a versioned profile. Unknown weights and task IDs fail closed.

The same scorer can compare adaptive `rg + Get-Content`, LSP, GraphGraph, and
hybrid traces without embedding a strategy in the metric implementation.

## First self-measurement

One cold `uv run graphgraph orient --json` observation on this repository after
the first implementation produced this attribution:

| Phase | Time |
| --- | ---: |
| Graph load | 206.124 ms |
| In-memory structural validation | 10.406 ms |
| Package metadata and freshness | 233.707 ms |
| Atlas construction | 55.187 ms |
| Internal total | 505.677 ms |
| Cold command wall time | 853.54 ms |

The compact output before the final evidence-budget reduction was 15,831
characters for twelve subsystems, two entry points, twenty coupling rows, and
98 indexed test files. The atlas correctly identified Python as the production
language; polyglot test fixtures no longer inflate that inventory.

This is a diagnostic observation, not a benchmark result. The saved graph was
stale and reported 39 truncated documents, so it cannot support a promotion
claim.

After replacing the row caps with budgeted selection and precomputing candidate
costs, another single cold observation emitted 8,488 total characters. The
evidence view used 7,957 of its 8,000-character budget, selecting 12 of 19
candidate subsystems and 7 of 150 candidate coupling rows. Atlas construction
was 105.311 ms, internal total 570.424 ms, and wall time 882.45 ms. Thus the
dynamic selector roughly halved output size at a roughly 29 ms wall-time cost
relative to the first compact-budget implementation. This is an acceptable
interactive trade in the current slice, but held-out repeated measurements must
replace both single-run numbers.

## Storage decision

This atlas result alone did not license a storage rewrite. The later dedicated
canonical-storage tournament did: GGB4 preserved full fidelity and full-load
latency while materially improving exact relations. Atlas still materializes
the full graph because freshness/package work and process startup dominate its
remaining cost; section-selective atlas reads need their own attributable gate.

The next attributable experiment is a narrow, crash-safe derived atlas cache
keyed by the graph fingerprint and invalidated by every scan/update/remove
commit. Reject it unless:

- cached and uncached payloads are logically identical;
- stale fingerprints never license a cache hit;
- interrupted writes retain the previous valid view;
- cold latency improves materially beyond measurement noise;
- update cost remains proportional to changed/affected evidence.

The persistent exact-relation sidecar remains a separate experiment for caller
and callee workloads. Neither result licenses a new base format by itself.

## Promotion gates still open

1. Freeze held-out cold-orientation tasks and qrels across language/build-system
   strata.
2. Record the adaptive primitive-agent (`rg` plus bounded source reads)
   baseline with the same model, prompt, budgets, and environment.
3. Record atlas-assisted traces without exposing qrels to either strategy.
4. Test H1: at least 20% lower median actions and source lines with no answer or
   false-complete regression; use paired intervals rather than a self-repo
   anecdote.
5. Only then tournament the derived cache or another `.gg` specialization.

See [Project Navigation Research Agenda](../../research/project-navigation-research-agenda.md),
[Orientation Engine](orientation-engine.md),
and [Native Graph Store](../storage/native-graph-store.md)
for the research basis and later delivery slices.
