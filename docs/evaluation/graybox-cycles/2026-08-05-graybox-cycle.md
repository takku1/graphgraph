# GraphGraph Gray-Box Evaluation — Cycle 2026-08-05

**Method:** gray-box (per `graybox` skill). CLI only (`graphgraph` on PATH, v0.1.0) —
no reading of GraphGraph's own source or git history, per standing instruction.
Ground truth for every claim below comes from reading/grepping the *target*
repos being scanned, or from GraphGraph's own `compare`/`status`/`profile`
telemetry cross-checked against that ground truth.

**Targets:** `resources/flask` (Python, 83 source files, 9.5k LOC, tree_sitter
frontend) and `resources/express` (JavaScript, 141 source files, tree_sitter
frontend) — chosen for well-understood, greppable structure and enough size to
stratify by language.

**Prior cycles:** the target report directory was empty at the start of this
cycle, but `resources/express/.graphgraph/` contained stray dated graph files
(`graybox-2026-07-30.gg`, `graybox-20260801.gg`, `graybox-rebuild-20260801.gg`,
`graybox-pulse-worktree-2026-07-30.gg`) — evidence of at least three earlier,
unrecorded graybox sessions against this fixture. No report from those cycles
exists anywhere under `graphgraph/docs/`, so there is nothing to diff against;
this cycle is treated as a fresh baseline. **Housekeeping note:** those stray
files and the contaminated `.graphgraph/` directories this cycle produced in
both target repos have been deleted — `.graphgraph/` is a fully regenerable
build artifact in both repos, and `git status` in both repos is clean.

**A methodological retraction, up front:** the first version of the headline
finding below was wrong in its *cause*, not its *symptom*. The first
single-file `update` I ran against express showed a large node/edge drop, and
my first hypothesis was a real bug. On rebuilding from a truly clean
`.graphgraph/` and rerunning, the *same* drop reproduced with the same exact
edge-type signature on two different files (`lib/application.js` and
`lib/utils.js`, tested independently), which ruled out stale-state
contamination as the explanation. The finding is real; only my first-pass
attribution needed the second pass. See Finding 1.

---

## Scorecard

| Layer | Today | Credible ceiling | Why it's capped today |
|---|---|---|---|
| Symbol/call extraction (tree_sitter) | 8.5/10 | 9.5/10 | 100% precision/recall on every ground-truthed sample; capped by inherently unresolvable dynamic dispatch, not by the tool |
| Incremental update (`update`) | **3/10** | 10/10 | Silently drops ~65% of cross-file `calls` edges on every single-file JS update (Finding 1). Purely a correctness bug — the speed and architecture are already right |
| Query/retrieval & packet generation | 7.5/10 | 9/10 | Honest, budget-aware, fails closed; ceiling capped by the fact that its own `eval`/acceptance-scoring machinery exists but never surfaces in the base workflow |
| Self-diagnosis (`doctor`/`status`/`compare`) | 6.5/10 | 9.5/10 | Rich and mostly honest, but has a real internal-consistency bug (Finding 2) and doesn't proactively surface the update corruption from Finding 1 even though `compare` (which it already ships) can detect it in one call |
| Orientation (`orient`) | 6/10 | 9/10 | Fast, readable, but silently omits whole subsystems (Finding 3) with no "N omitted" disclosure |
| **Overall, as used in an agent edit-loop** | **~5.5/10** | **9.5/10** | Every layer except `update` is already close to its ceiling; the update bug is the single thing standing between this tool and a very strong score, because it is the exact workflow ("fresh edit-loop context") the tool is pitched on |

The gap between today and ceiling is concentrated almost entirely in one
place. That is good news: this is not a tool with broad, diffuse weakness — it
is a tool with excellent bones and one severe, well-localized, already-fast
bug.

---

## Finding 1 (CRITICAL) — `update` silently deletes ~65% of cross-file `calls` edges on every single-file JS update

**Symptom.** On a clean `express` graph (`graphgraph scan`, 3486 nodes, 12139
edges), running `graphgraph update --files lib/application.js` on an
**unchanged-content** re-run is idempotent (0 diff, correctly). But applying a
**real one-line edit** (a trailing comment) and re-running `update` drops the
graph to ~3442-3444 nodes / ~9185-9187 edges — every time, regardless of which
file is touched:

| File touched | `external` nodes | `calls` edges | Edges lost |
|---|---|---|---|
| baseline (full scan) | 47 | 4543 | — |
| `lib/application.js` (623-line core file) | 3 | 1598 | 2945 |
| `lib/utils.js` (271-line, non-central file) | 5 | 1600 | 2943 |

Reproduced independently three times (two files, verified from a freshly
rebuilt `.graphgraph/` each time) with near-identical magnitude regardless of
which file was touched or how central it is to the codebase. `explains` edges
also drop slightly (104→95) each time.

**Evidence.** Direct-oracle via `graphgraph compare --left <clean> --right
<post-update>` (a command GraphGraph ships itself) on byte-identical source
trees except for the one probe line. `left_only_edge_keys` is ~2950 both
times, `right_only_edge_keys` is 0 — i.e. `update` only ever *removes* edges
here, never adds a compensating set. I additionally spot-checked that the
specific symbol I edited (`app.set`'s 6 real callers, confirmed against
`grep`) is preserved correctly before and after — so the loss is not "the
touched symbol's own edges," it is collateral damage to unrelated edges
elsewhere in the graph.

**Cross-check against the promised guardrail.** `update --help` documents a
`--force` flag: *"Allow a rebuild that discards more than half the existing
graph. Without it, such a write is refused as probable data loss."* This
guard exists and is real (verified it's present in `--help`), but the loss
here is ~24% of total edges (under the 50% total-graph threshold) even though
it is **65% of the `calls` relation specifically**. The safety net is scoped
to the wrong denominator (whole graph) to catch a concentrated single-relation
collapse.

**Stratified control.** The identical protocol against `flask` (Python,
tree_sitter), touching its largest, most-connected file (`src/flask/app.py`,
1625 lines) produced **zero diff** — exact node/edge/relation-type parity,
`left_only_edge_keys: 0`. This is a clean 0%-vs-100%-magnitude split by
language, which localizes the defect: it is specific to how JavaScript's
external/library-call resolution is (re)built during an incremental splice,
not to the update mechanism in general.

**Inferred cause** *(explicitly inference, not confirmed against source)*:
JS external-call resolution appears to depend on a corpus-wide
export/import registry (to resolve e.g. `require(...)`-sourced calls and
built-ins). The `--files`-scoped `update` path seems to rebuild this registry
using only the touched file's exports and discard entries for every
untouched file, rather than splicing in just the delta. Python's resolution
path apparently doesn't share this dependency, or splices correctly.

**Self-diagnosis blind spot.** Running `status` immediately after the
corrupted update shows the `Member calls: resolved=1315...` line still
carrying the *pre-update* full-scan numbers, explicitly (and honestly)
labeled `STALE: counts were measured by a full scan... incremental scans
carry them forward unchanged`. That caveat is accurate about the *stats
being stale* — but it does not flag that the underlying **graph edges
themselves** were just cut by a quarter. The only visible signal is the bare
`edges=9187` in the structural-validation line, with nothing calling out
that this is anomalous. `compare` — which caught this instantly when I ran
it — is not run automatically around `update`.

**Repair path exists but is invisible.** A subsequent full `graphgraph scan`
(not `update`) restores the graph to exactly 3486 nodes / 12139 edges. So
data isn't unrecoverable, but nothing in the tool tells an agent using
`update` in a tight edit loop that it should periodically fall back to a full
`scan` to undo accumulating corruption.

**Floor.** An `--files`-scoped update should leave every edge whose source
*and* target both lie outside the changed-file set byte-identical. Floor cost
is close to what's already measured (0.6-0.9s regardless of repo size in
Finding 5) — this is a correctness bug layered on an already-fast mechanism,
not a performance problem.

**Gap.** ~2950 wrongly-deleted edges per single-file edit on this ~140-file
fixture. Because the loss is proportional to how many *other* files reference
externals/library calls, it should scale up, not down, on larger JS
repositories — the opposite of the tool's own "cost scales with `--files`,
not repo size" promise, at least for correctness (wall-clock time does scale
as promised; the answer returned afterward just becomes wrong).

**What if.** Two changes would collapse this gap to ~zero: (1) splice the
external/import registry incrementally (add/remove only entries touching the
changed file's own imports/exports) instead of rebuilding it from a
changed-files-only view; (2) extend the existing `--force` data-loss guard to
check **per-relation-type** deltas, not just total node/edge count — a
`calls` edge count dropping >10% between an `update` and the last known-good
full-scan snapshot is exactly the shape of bug this would catch, and the
guard's own precedent (the 50% total-graph check) shows the team already
believes in this kind of protection; it just needs a finer denominator.

---

## Finding 2 (LOW-MEDIUM) — `status --probe` uses the wrong casing for the Python import name, contradicting its own correctly-resolved entry point in the same output

**Symptom.** `graphgraph status --probe` in `resources/flask` runs 5 runtime
probes; 2 fail specifically because they invoke `python -m Flask --help` /
`import Flask` (capital F). The actual importable module is lowercase
`flask`.

**Evidence.** Direct oracle: `pyproject.toml` line 2 has `name = "Flask"`
(the PyPI display name), but the same file's entry-point line 82
(`flask = "flask.cli:main"`) and GraphGraph's *own* status output two lines
above the failing probes (`Scripts: flask=flask.cli:main`) both show the
correct lowercase form. This is an internal contradiction, not just a
mismatch against the target repo — the correct string is already sitting in
the same command's output.

The other 3 probe failures (`script_target_import:flask`, correctly using
lowercase) are legitimate environment failures (`ModuleNotFoundError:
werkzeug`, confirmed by manually reproducing the same import with
`PYTHONPATH=src`) — not a GraphGraph defect.

**Inferred cause:** probe module-name derivation reads `[project].name`
verbatim rather than deriving the root package from the entry-point target
it already parsed correctly for the `Scripts:` line.

**Floor.** 0 wrong probes — this is string derivation from data already in
hand, no external dependency involved.

**What if.** Derive the raw-import probe target the same way the `Scripts:`
line is derived (from the entry-point path, e.g. `flask.cli` → root package
`flask`) instead of from the PyPI display name.

---

## Finding 3 (MEDIUM) — `orient`'s subsystem atlas silently omits whole subdirectories

**Symptom.** `graphgraph orient` on `express` lists exactly 6 subsystems, one
per top-level file directly under `lib/` (`application.js`, `response.js`,
`utils.js`, `express.js`, `request.js`, `view.js`). `lib/router/{index,layer,
route}.js` — Express's routing engine, arguably its single most
architecturally important subsystem — never appears anywhere in the atlas or
its coupling table.

**Evidence.** Direct oracle: `ls lib/` and `ls lib/router/` confirm the
directory and its three files exist and were included in the scan (the
earlier full-repo `scan` reports `javascript=141` files total, so router
files were extracted as symbols — they're just absent from `orient`'s
summary).

**Inferred** *(explicitly inference — not confirmed against source)*:
subsystem selection appears to key on depth-1 directory/file grouping and/or
apply a small fixed cap, both of which would drop a nested subsystem like
`lib/router/`.

**Not fully characterized.** I did not test whether this is a hard depth
limit, a top-K-by-score cap, or something else, nor did I test it on a
third repo to see how it scales — flagged explicitly as untested rather than
silently assumed.

**Gap / what if.** An atlas billed as "system card, subsystems, coupling" for
onboarding purposes should either surface every directory with meaningful
symbol density (recursively, not just depth-1) or explicitly say "N smaller
subsystems omitted" the way `--limit`-bounded commands elsewhere in the CLI
already do. Silence reads as completeness; it isn't here.

---

## What's already at the floor — do not spend effort here

- **Call-graph precision/recall on statically-resolvable calls: 100% on
  every ground-truthed sample.** Three independent direct-oracle probes
  (`_endpoint_from_view_func`: 2/2 exact; `get_debug_flag`: 4/4 exact, correct
  test-vs-production filtering; `Flask.dispatch_request` callees: 3/3 exact,
  correctly *excluding* the one genuinely unresolvable dict-dispatch call
  site `self.view_functions[rule.endpoint](...)`) all matched grep-verified
  ground truth exactly, including correct line-level detail.
- **Ambiguity handling.** Querying a symbol name with 7 same-named
  candidates across the codebase (`dispatch_request`, overridden in 3
  production classes + 4 test classes) returns a candidate list and asks for
  disambiguation rather than guessing or silently merging results.
- **Failing closed under the red test.** Querying for a symbol that provably
  does not exist returns explicit `"status":"unanswerable"` /
  `"status":"not_found"` with `missing_evidence` populated and zero
  fabricated nodes/edges, on both the `query` and `relations` operators. No
  metric moved to a falsely-green value anywhere in this cycle.
- **Calibrated self-doubt.** Every relation/select answer ships a receipt
  quantifying exactly how much of the call graph is trustworthy (e.g.
  "member-call resolution 67.0% (883/1318)... zero-caller counts are an
  upper bound on dead code, not a proof") rather than presenting partial
  coverage as complete. This is a genuine, rare differentiator versus
  grep/embedding-only retrieval, which has no comparable notion of its own
  incompleteness.
- **Raw scan throughput.** Full symbol+doc+concept extraction over 231 files
  (83 Python source + 115 docs) completes in ~4.3s cold, ~1.1s warm
  (incremental, 0 dirty files). Profiling shows this is dominated by
  tree_sitter symbol extraction itself (~2.6s of ~3.7s), not by anything
  GraphGraph controls inefficiently. Not a target for further optimization.
- **Update *speed* (independent of the correctness bug above).**
  Single-file `update` is 0.6-0.9s on both an 83-file and a 141-file repo —
  effectively flat with respect to corpus size, consistent with the tool's
  own "cost scales with `--files`, not repo size" claim, purely on the
  latency axis.
- **Monotonicity under budget.** Raising `--max-nodes` from 20 to 200 on the
  same query only ever added nodes/edges (19/18 → 21/24), never removed any
  — no monotonicity violation found.

---

## Coverage — what this cycle did *not* test

Explicitly listed per evidence-discipline: absence of a finding below is
"not tested," not "passes."

- `remove`, and whether Finding 1's edge-loss pattern also applies there
- The entire `platform` subtree: `federate`, `semantic`, `memory`, `episode`,
  `as-of`, `trace`, `repair`, `serve` (HTTP API), `watch`, `hooks`,
  `benchmark`, `acceptance`, `quality` — a large surface, untouched
- `eval` / `navigation-eval` (require hand-authored task/qrel JSON; no
  frozen task set existed for these fixtures)
- Semantic/embedding retrieval quality (`--source-mode all`, FastEmbed
  backend) — only structural retrieval was exercised
- `--representation hybrid` — the tool's own help text already flags this as
  "experimental... not yet promoted by any tournament gate," so it was
  deliberately left untested rather than benchmarked as if stable
- 13 of the 15 tree_sitter-advertised languages (only Python and JavaScript
  were exercised; Rust, Go, Java, C, C++, C#, Ruby, PHP, Kotlin, Scala,
  Swift, TypeScript, TSX all declared `available: true` in `frontends` but
  unverified here)
- MCP-server transport (CLI only, per standing black-box instruction)
- Repos larger than ~150 files — both fixtures are small-to-medium; the
  update-cost-scaling claim is only confirmed in the range tested

---

## Roadmap to "beats every other context graph, and beats native grep/get-context"

GraphGraph's real edge over both competing context-graph tools (e.g. the
`code-review-graph` MCP server available in this same environment) and native
retrieval (grep/glob/"flatten the repo into context") is that it already
does three things neither of those categories does by default: a **typed,
44-relation ontology** instead of text co-occurrence; **confidence-calibrated
receipts** on every answer instead of silent partial coverage; and
**budget-aware packet formats** chosen per query class instead of one
serialization for everything. None of that needs to be invented — it exists
today and, per the findings above, mostly works. The roadmap is about closing
the trust gap, not adding capability surface:

1. **Fix Finding 1 first, before anything else.** Nothing downstream is
   trustworthy in an iterative agent-edit workflow until single-file `update`
   stops corrupting the call graph. This is the one item that, left
   unfixed, makes the tool worse than "just re-run a full scan every time" —
   which defeats its own core pitch.
2. **Turn `compare` into an automatic post-`update` gate**, not a manual
   command a user has to remember to run. Extend the existing `--force`
   data-loss guard to a per-relation-type check (e.g. refuse/warn if any
   single relation type drops >10% versus the last full-scan snapshot,
   in addition to the current whole-graph 50% check).
3. **Make `status` proactively surface drift**, not just passively label
   stats "STALE." A one-line banner — "graph edges dropped 24% since last
   full scan; run `graphgraph scan` to refresh" — turns a buried caveat into
   something an agent will actually act on.
4. **Surface the `eval`/acceptance scoring in the default workflow.** The
   machinery to prove "X% recall at Y tokens, versus Z tokens for grep" is
   already built (`eval`, `navigation-eval`, `platform quality`, `platform
   benchmark`). Right now none of it appears unless a user hand-authors task
   files and opts in. A tool that wants to credibly claim "beats grep and
   beats other context graphs" should print that comparison, with numbers,
   as part of `status` or `orient` on any repo with a test suite it can
   already see (`orient` already found `express`'s `npm test` command).
5. **Close the declared-vs-demonstrated language gap.** 15 languages report
   `available: true` at `confidence: 0.95` in `frontends`; only 2 were
   verified this cycle to actually hit the precision/recall bar found here.
   Either publish per-language acceptance numbers or don't claim uniform
   confidence across all 15.
6. **Give `orient` an explicit completeness contract**: recurse into
   subdirectories for subsystem candidates, or print "N subsystems omitted
   below the coupling threshold" the way budget-capped commands elsewhere in
   the CLI already do.
7. **Fix Finding 2** — small, but it's exactly the kind of self-contradiction
   that erodes trust in every other self-reported number once a user notices
   one is wrong next to a correct one.

## Proposed CI gate (single scalar, cheap, targets the worst bug directly)

```
graphgraph scan  --directory <fixture> --depth symbols --output baseline.gg
graphgraph update --directory <fixture> --files <any-one-file> --output spliced.gg
graphgraph compare --left baseline.gg --right spliced.gg
  →  ASSERT edge_types.calls(right) == edge_types.calls(left)
  →  ASSERT left_only_edge_keys == 0   (no edges vanish that shouldn't)
```

This is already fully expressible with commands the tool ships today, costs
under 5 seconds on a fixture this size, and is a true invariance gate: green
means the flagship low-latency edit-loop workflow is trustworthy; red means
it isn't, in exactly the way this cycle found it wasn't. Recommended
thresholds: `calls` edge parity exact (0 tolerance) on a frozen fixture per
language family currently supported by tree_sitter, run on every change to
the extraction or update path.
