# GraphGraph Gray-Box Evaluation — 2026-08-07

**Method:** Gray-box. GraphGraph source and git history were never read. All
findings come from CLI execution plus GraphGraph's own telemetry, corroborated
against ground truth derived independently from the *target* repositories
(Python `ast`, `grep`, `tiktoken`).

**Version under test:** `graphgraph 0.1.0`, Python 3.11.15, Windows,
tree-sitter frontend, `fastembed:BAAI/bge-small-en-v1.5` active.

**Fixtures:**

| Repo | Language | Files | Nodes | Edges | Scan (cold) |
|---|---|---|---|---|---|
| `resources/flask` | Python | 231 | 5,868 | 16,703 | 4.1 s |
| `resources/beads` | Go | 2,863 | 47,315 | 187,589 | 40.8 s |
| `resources/express` | JavaScript | 141 | 3,485 | 12,139 | — |
| `resources/bollard` | Rust | 94 | 5,077 | 13,821 | — |
| `resources/chartr` | Go | 110 | 7,977 | — | — |

---

## ⚠️ Retraction (published before conclusions, per evidence discipline)

My first semantic-equivalence measurement reported **Jaccard 0.00** between
paraphrases of the same question — a dramatic "retrieval is completely unstable"
result. **That number was wrong, and it was my error.**

Cause: my extraction script parsed `#gg`-format rank lines (`^\d+ label @path`).
One paraphrase was rendered in `#svo` format instead, which has no rank lines, so
my parser silently returned a near-empty set and I computed overlap against
garbage. I concluded absence from a parser that had stopped matching.

Corrected, format-agnostic measurement appears as **F4** below: the real figure is
Jaccard **0.07** between two same-format paraphrases — still a genuine finding,
but a different and smaller one than what I nearly published.

The methodological error is instructive twice over: the silent parser break is
itself the evidence for **F5** (packet-format instability). An agent consuming
this output would fail exactly the way I did, and just as quietly.

---

## What is already at the floor — do not touch these

These are the parts a rewrite would most likely make worse. Several are
genuinely rare in this class of tool.

### 1. Extraction recall is *exact* — 100%, not "good"

Ground truth derived by walking Python's `ast` over all 83 files in flask,
stratified by nesting depth, then compared set-wise against `graphgraph select`
output (full lists, `truncated: false` verified — no head-truncation):

| Stratum | Truth | Found | Missing | Recall |
|---|---|---|---|---|
| module-level functions | 519 | 519 | 0 | **100.0%** |
| methods | 309 | 309 | 0 | **100.0%** |
| nested functions | 335 | 335 | 0 | **100.0%** |
| top-level classes | 69 | 69 | 0 | **100.0%** |
| nested classes | 68 | 68 | 0 | **100.0%** |
| **union** | **1,297** | **1,297** | **0** | **100.0%** |

Zero misses **and zero false positives** — `in graph but not in AST: 0`. The
tree-sitter frontend is not approximating. This is the hard part of the problem
and it is finished.

### 2. `orient` is the single best thing in the tool

**279 tokens** (cl100k) for a complete architecture atlas, against **13,727
tokens** to read `src/flask/app.py` once — a **49x** advantage on the orientation
task, and it is *accurate*:

- `Languages: python=24` — exactly the `src/` file count.
- Entry points correctly identified (`flask.cli:main`, `src/flask/__main__.py`).
- Subsystem partition (`flask` / `sansio` / `json`) matches the real package
  structure, and correctly **excludes tests and examples**.
- Coupling broken down *by edge type*: `flask -> sansio: 51 (references=22,
  calls=10, imports=9, imports_from=9, implements=1)`.

It also cross-validated my own work: `orient` reports 406 production symbols;
my independent AST oracle found 441 definitions; the 35-symbol delta is exactly
the collision loss quantified in **F2**. Two independent derivations agreeing.

### 3. Correct abstention on out-of-domain input

| Query | Nodes returned | Output size |
|---|---|---|
| "recipe for chocolate sourdough bread" | **0** — *explicit abstain* | 93 chars |
| "quantum error correction surface codes" | **0** | — |
| "how does the CUDA kernel scheduler allocate warps" | 2 weak doc nodes, flagged partial | 232 chars |

Most retrieval systems cheerfully return top-k garbage for these. GraphGraph
returns nothing and says so. This is rare and it is correct.

### 4. Self-reported caveats are best-in-class

Every `select` call carries, unprompted:

> *"zero-caller counts are an upper bound on dead code, not a proof"*

Plus `truncated: true` flags, `answer_complete: false`, `topology: "partial"`,
`freshness: "unchecked"`, `coverage=partial`, `health=partial`, and explicit
next-action hints (`["sync_if_completeness_required", "verify_absence_or_count"]`).
The tool volunteers precise maps of where its own model is incomplete. This is
better epistemic hygiene than most commercial tooling.

### 5. The `eval` instrument passes the red test

Fed expectations that **cannot** be satisfied (`src/flask/zzz_nonexistent.py::quantum_flux_capacitor`):

```
node_recall: 0.0    mrr: 0.0    ndcg_at_5: 0.0
answerability_status: "unanswerable"
expected_unresolved: ["src/flask/zzz_nonexistent.py::quantum_flux_capacitor"]
note: "...excluded from calibration"
```

The metric moved, no internal contradictions between co-reported values, and
unsatisfiable expectations are quarantined from calibration rather than
silently scored. Correctly designed.

### 6. Idempotence and subsumption — clean pass

- **Idempotence:** byte-identical output across reruns.
- **Subsumption:** budget 10 → 25 → 60 produced 8 → 25 → 42 nodes with **zero**
  set-containment violations. Raising the budget never removed a result.

---

## Findings

### F1 — Routing confidence is a hardcoded constant *(instrument defect — ranked first)*

**Symptom.** `automatic routing confidence is low (0.147)` is emitted with the
*identical* value for every query that takes the fallback path.

**Evidence.** Eight semantically unrelated queries on flask:

| Query | Reported confidence |
|---|---|
| how does Flask dispatch a request | 0.147 |
| chocolate cake recipe | 0.147 |
| blueprint registration | 0.147 |
| session cookie signing | 0.147 |
| zzzz nonsense qqq | 0.147 |
| test coverage for blueprints | 0.147 |
| CUDA warps | 0.147 |
| totally unrelated aardvark banana | 0.147 |

And then on **beads** — a different repo, different language, 8x the nodes:
`chocolate cake recipe` → 0.147, `issue dependency resolution` → 0.147,
`zzz nonsense qqq` → 0.147. The value is invariant to query, to corpus, to
language, and to whether the answer was excellent or nonexistent. It carries
**zero bits of information**.

**Important scope limit:** the *qualitative state* is real and useful —
`"GraphGraph abstained: no matching graph anchors"` vs `"GraphGraph partial
result"` correctly discriminates. Only the **number** is dead. The decision
logic works; the reported scalar does not.

Corroborating signal from `eval --calibration`: mean confidence 0.229 against
accuracy 1.0 → **ECE 0.77**, badly underconfident. *(Single-sample bin — weak
evidence on its own, listed as corroboration only.)*

**Inferred** *(inference, not observation)*: 0.147 is a constant attached to the
"auto-routing fell through" branch rather than a computed per-query score.

**Floor.** Confidence should correlate with realized recall; ECE < 0.10.
**Gap.** Currently uninformative — infinite gap, it is a decorative number.
**What if.** Wire routing confidence to the same anchor-match evidence that
already drives the (correct) abstain/partial decision. The signal clearly
exists — it is simply not being surfaced as the number.

**Gate:** `stdev(routing_confidence) > 0.05` over a 20-query diverse set; `ECE < 0.15`.

---

### F2 — Node-ID collision silently drops 7.9% of production definitions

**Symptom.** Symbol nodes < actual definitions. Recall is 100% at *(file, name)*
granularity but the graph stores fewer **nodes** than the source has
**definitions**: 1,354 nodes vs 1,620 definitions.

**Evidence (direct AST oracle), stratified:**

| Stratum | Definitions | Nodes | Lost | Retained |
|---|---|---|---|---|
| `src/` (production) | 441 | 406 | **35** | **92.1%** |
| `tests/` | 1,145 | 914 | 231 | 79.8% |
| `examples/` | 32 | 32 | 0 | 100.0% |
| **total** | **1,620** | **1,354** | **266** | **83.6%** |

The ID scheme (`path__Class__method`) qualifies **methods** by class — good
design — but does **not** qualify nested functions or `@property`/`@x.setter`
pairs. Collisions therefore keep only the first occurrence.

**All 7 property setters in `src/flask` are silently absent from the graph.**
Verified against source:

```
src/flask/wrappers.py:59  @property        def max_content_length(...)   → node exists
src/flask/wrappers.py:88  @max_content_length.setter                     → NO NODE
src/flask/sessions.py:32  @permanent.setter                              → NO NODE
src/flask/sansio/app.py:562 @debug.setter                                → NO NODE
```

Worst case observed: `tests/test_basic.py::index` — **36** distinct nested route
handlers collapse to **1** node at line 34.

Consequence is on *edges*, not text: a nonexistent setter node has no `calls`
edges, cannot appear in blast-radius, and makes `select "callers = 0"` dead-code
analysis wrong for every property. (GraphGraph's own caveat already warns that
zero-caller counts are an upper bound — this is one mechanism behind that.)

**Floor.** 0% loss. **Gap.** 7.9% of production symbols unaddressable.
**What if.** Append a scope-chain or line disambiguator to the node ID
(`path__Class__method@L88`). Mechanical change; extraction becomes exact.

**Gate:** `graph_symbol_nodes == ast_definition_count` on a Python fixture.

---

### F3 — Go member-call resolution is a categorical outlier: 6.6% vs 62–87%

**Symptom.** Resolution rate collapses on Go. This is not a gradient — it is a
different code path failing.

| Language (repo) | resolved | unresolved | denom | rate |
|---|---|---|---|---|
| JavaScript (express) | 1,315 | 195 | 1,510 | **87.1%** |
| Python (flask) | 883 | 435 | 1,318 | **67.0%** |
| Rust (bollard) | 698 | 429 | 1,127 | **61.9%** |
| **Go (chartr)** | 135 | 522 | 657 | **20.5%** |
| **Go (beads)** | 1,459 | 20,617 | 22,076 | **6.6%** |

Confirmed on **two independent Go repos**, and re-derived a second way via
`graphgraph status` on beads (matches the scan output exactly).

**Evidence for cause.** GraphGraph's own unresolved-shape telemetry on beads:

```
named_local=8,776   short_local=7,420   complex_expression=2,237
field_chain=1,921   call_result=114
```

`short_local` + `named_local` = 16,196 of 20,468 unresolved (79%). In beads,
`:=` appears **82,058** times versus 5,763 explicit `var x T` declarations.

**Inferred** *(inference)*: receiver type inference does not propagate types
through Go's `:=` short variable declaration — which is the dominant, idiomatic
way Go binds every local variable. The failure is concentrated in the single
most common construct in the language.

**Floor.** Go is statically typed with local type inference; the RHS type of
`x := NewThing()` is recoverable from the CST without a full type checker.
Python at 67% is the harder problem and it is being *beaten by 10x*.
**Gap.** ~10x below the tool's own Python baseline; ~13x below JS.
**What if.** One tree-sitter pass binding `:=` and `var` RHS types to receivers
would plausibly move Go from 6.6% to 80%+ and bring it to language parity.

**Gate:** Go member-call resolution > 60% on a fixture.

---

### F4 — Retrieval is lexical-anchor-dominated, not semantic

**Symptom.** Paraphrases that share content words return identical results;
paraphrases that use synonyms return near-disjoint results.

**Evidence** (format-agnostic node-identity extraction, top-25, all on flask):

| Pair | Format | Jaccard |
|---|---|---|
| p1 "how does Flask **dispatch** a **request** end to end" vs p2 "what is the **request dispatch** flow in Flask" | gg / gg | **1.00** |
| p1 vs p4 "trace the path from WSGI entry to view function return" | **gg / gg** | **0.07** |
| p1 vs p3 "explain Flask request routing and handler invocation" | gg / svo | 0.04 |

p1↔p4 is the load-bearing comparison: **same packet format**, so no parsing
artifact — this is apples to apples.

**The answers differ in quality, not just membership.** p1 correctly top-ranks
`full_dispatch_request` and `dispatch_request`, and includes `wsgi_app`,
`finalize_request`, `preprocess_request`, `request_context` — the actual Flask
dispatch chain. p4 **misses all of them** and top-ranks
`_endpoint_from_view_func` (an internal naming helper), followed by
`wsgi_errors_stream` (a logging helper that matched the token "WSGI").

`doctor` reports `fastembed:BAAI/bge-small-en-v1.5 (real embeddings active)`,
so the embedding backend is loaded. **Inferred** *(inference)*: it is not
driving ranking; anchor selection appears to be lexical.

**Floor.** Paraphrase Jaccard > 0.6 for semantically equivalent questions.
**Gap.** 0.07 vs 0.6 target — retrieval quality depends on the user guessing
the codebase's vocabulary, which is precisely what a newcomer cannot do.
**What if.** Route the already-loaded bge-small embeddings into anchor selection
and reranking. This is the single highest-leverage retrieval fix.

**Gate:** paraphrase-invariance suite; min pairwise Jaccard > 0.5.

---

### F5 — Packet format switches silently on paraphrase

**Symptom.** The same question rendered as `#gg` for three phrasings and `#svo`
for a fourth, with no flag change and no announcement.

**Evidence.** p1, p2, p4 → `#gg` (rank-line format). p3 → `#svo` (entity/triple
format). The two formats share no structural syntax.

**This broke my parser silently and produced a false finding** (see Retraction).
Any agent that writes one parser against `graphgraph context` output will hit
the same failure, and will get an empty result rather than an error.

**Floor.** Output format is a function of explicit user choice, or is stable
under paraphrase.
**What if.** Either pin format to the `--packet` flag only, or emit the format
identifier in a stable machine-readable header and keep query-class routing
paraphrase-stable.

**Gate:** all paraphrases of a fixture question yield the same packet format.

---

### F6 — `--pretty` overhead is documented as ~26%, measured at 49–55%

The `--pretty` help text states it *"Costs ~26% more tokens"*. Measured with
`tiktoken` / `cl100k_base` (not chars):

| Payload | Compact | Pretty | Overhead |
|---|---|---|---|
| 10 symbols | 657 tok | 979 tok | **49.0%** |
| 50 classes | 2,834 tok | 4,354 tok | **53.6%** |
| 200 symbols | 11,143 tok | 17,143 tok | **53.8%** |
| 854 symbols | 46,925 tok | 72,541 tok | **54.6%** |

Stable across two orders of magnitude of payload; the documented figure
understates real cost by roughly **2x**. Minor, but it is a self-reported number
that does not survive measurement — and this tool's credibility rests
unusually heavily on its self-reported numbers being trustworthy.

**Gate:** assert documented overhead within ±10% of measured.

---

### F7 — Incremental update does not meet its stated invariance contract

**The contract** (from `graphgraph update --help`):

> *"cost scales with `--files`, not repo size"*

**Measured**, 1-file update, 3 runs each:

| Fixture | Files | Nodes | 1-file update |
|---|---|---|---|
| flask | 231 | 5,868 | 681 / 444 / **418 ms** |
| beads | 2,863 | 47,315 | 1,469 / 1,506 / **1,465 ms** |

**12.4x the files → 3.5x the time.** Sublinear, so the claim is directionally
right, but it is **not invariant** as stated.

**Cost decomposition** (this is the actionable part):

| Measurement | flask | beads |
|---|---|---|
| `graphgraph --version` (interpreter start floor) | ~330–370 ms | ~330–370 ms |
| `graphgraph status` (load + analyze) | 550 ms | 2,973 ms |
| 1-file `update` | 418 ms | 1,465 ms |
| full rescan | 971 ms (warm) / 4.1 s (cold) | 40,785 ms |

Two observations worth separating:

1. **~350 ms of *every* CLI invocation is Python interpreter startup** — that
   is **~80%** of flask's entire 1-file update. On small repos the tool is
   almost entirely paying process-start tax.
2. Graph load scales with corpus (5.9k nodes → ~200 ms; 47k nodes → ~2,650 ms),
   slightly superlinear.

**Credit where due:** 1.47 s vs a 40.8 s full rescan is a **28x** win. The
incremental path unambiguously works.

**Floor.** Reparse one file (~5 ms tree-sitter) + splice O(Δ) edges + persist
O(Δ) bytes ≈ **30–50 ms, invariant to corpus size**.
**Gap.** ~30–50x above floor on beads, and the gap grows with corpus.
**What if.** A persistent daemon eliminates the 350 ms floor outright and keeps
the graph resident, collapsing both terms. **Note:** the MCP server path likely
already amortizes this — these CLI numbers probably *overstate* the cost for the
agent-facing use case, which was not measured here.

**Gates:** `1-file update on a 2,863-file fixture < 300 ms`; and the stronger
**invariance gate** `t(large) / t(small) < 1.5` — which converts "scales
acceptably" into "does not scale at all," the correct target.

---

### F8 — Retrieval precision: 28.6% example-code noise

On "how does Flask dispatch a request end to end", **12 of 42** returned nodes
were from `examples/` — tutorial app code (`login`, `register`, `create`,
`get_post`) irrelevant to framework internals.

Notably `orient` gets this right and scopes to production; `context` does not
inherit that scoping. The fix may be as small as sharing `orient`'s partition.

---

## Cross-tool comparison

### Task: "who calls `get_root_path`?" (ground truth: `Scaffold.__init__`, call at `scaffold.py:96`)

| Approach | Correct? | Output | Notes |
|---|---|---|---|
| **`graphgraph relations`** | ✅ | **562 chars** | Resolves *enclosing symbol*; reports `answer_complete: false`, `topology: partial`, next-action hints |
| **`code-review-graph` MCP** | ✅ | ~1,230 chars | Also gives call-site line 96 + `confidence_tier: EXTRACTED`; absolute paths repeated 6x inflate cost |
| **native `grep -rn`** | ⚠️ | 230 chars | 3 hits, **2 are noise** (the `def` and the `import`); does **not** tell you the enclosing function — needs a follow-up read |

GraphGraph is **2.2x more compact** than code-review-graph for the same correct
answer, and returns relative (portable) paths. code-review-graph wins on giving
the exact call-site line. Grep is cheapest but answers a *different, weaker
question* — it finds text, not callers.

### Task: architecture orientation

| Approach | Tokens | Quality |
|---|---|---|
| **`graphgraph orient`** | **279** | Real entry points; production/test separation; subsystems match package structure; coupling by edge type |
| **`code-review-graph` overview** | ~475 | 13 auto-named communities with cohesion scores; names are noisy (`type-check-hello`, `admin-index`); mixes tutorial code with production; its one coupling warning is about *tutorial example code* |
| **native (read `app.py`)** | 13,727 | Full fidelity, ~49x the cost, single file only |

`orient` is the clear winner here and the strongest argument for the tool.

---

## Coverage — what was NOT tested

Silence below is **not** a pass:

- MCP server path (CLI only) — relevant to F7, where it may materially change results
- `platform`, `memory`, `graph_at_time`, federation, `repair` subcommands
- `navigation-eval` (requires recorded traces)
- `--history` / git `fixes` edges
- `ingest`/`export` round-trip. **Noted asymmetry:** `ingest` accepts
  `.gg/.ggb/.json/.csv/.tsv` but `export` emits **only** `.gg` — there is no
  JSON egress, so external graph analysis requires the `select`/`query` surface
- Languages: Java, C, C++, C#, Ruby, PHP, Kotlin, Scala, Swift, TSX
- `cache` subcommand; concept/semantic-operator layer beyond reported coverage %
- Minor UX papercut, unquantified: `--query` prefix-matches to `--query-class`,
  producing the misleading error `argument --query-class: invalid choice: '<your
  whole question>'`

---

## Score

Decomposed by layer, weighted by the layer that caps the others — **extraction
bounds retrieval**, since you cannot retrieve what was never extracted.

| Layer | Today | Ceiling | Capping issue |
|---|---|---|---|
| Extraction (Python / JS / Rust) | **9.5** | 10 | F2 ID collision only |
| Extraction (Go) | **3.0** | 9.5 | F3 `:=` inference |
| Retrieval ranking | **5.0** | 9.5 | F4 lexical anchors |
| Packet / IR efficiency | **9.5** | 10 | at floor |
| Epistemics & self-reporting | **9.0** | 10 | F1 dead scalar |
| Performance / edit loop | **6.0** | 9.5 | F7 process start + load |

### Today: **6.5 / 10** — Credible ceiling: **9.5 / 10**

**The important thing the score does not convey:** the *hard* parts are done.
Exact extraction, a well-designed relation ontology, a token-efficient IR,
correct abstention, and disciplined caveat reporting are the things that are
genuinely difficult to get right and expensive to retrofit — and all five are
finished to a standard above most commercial tooling. A system with excellent
design and imperfect plumbing is in a far better position than the reverse.

Every remaining gap is **mechanical**, not architectural.

---

## "If we had XYZ, we'd be close to 10/10"

Ordered by (impact ÷ effort):

1. **Scope-qualified node IDs** (F2) — append line/scope to the ID.
   *Small.* → extraction becomes exact; property setters and nested handlers
   become addressable; dead-code analysis stops being an upper bound.
2. **Live routing confidence** (F1) — surface the evidence already driving the
   correct abstain/partial decision. *Small.* → the instrument becomes
   trustworthy, which everything downstream depends on.
3. **Deterministic packet format** (F5) — pin to `--packet` or emit a stable
   format header. *Trivial.* → agents can write one parser.
4. **Go `:=` receiver inference** (F3) — bind short-var-decl RHS types.
   *Small–medium, isolated to one frontend.* → 6.6% → 80%+, language parity.
5. **Persistent daemon** (F7) — kill the 350 ms interpreter tax, keep the graph
   resident. *Medium.* → sub-100 ms edit loop, invariant to corpus size.
6. **Embedding-backed reranking** (F4) — route the already-loaded bge-small
   into anchor selection. *Medium.* → paraphrase-stable retrieval; removes the
   requirement that users guess the codebase's vocabulary.

Items 1–4 are each plausibly a day's work and together move extraction and
epistemics to the floor. Items 5–6 are the two that convert GraphGraph from
"very good graph extractor with a lexical search front end" into "the retrieval
layer an agent should default to."

---

## Proposed CI gates

```
extraction.symbol_nodes == ast_definition_count           # F2, fixture: flask
retrieval.paraphrase_jaccard_min          > 0.50          # F4
retrieval.packet_format_stable_under_paraphrase == true   # F5
extraction.go_member_call_resolution      > 0.60          # F3, fixture: beads
telemetry.routing_confidence_stdev        > 0.05          # F1, 20-query set
telemetry.routing_confidence_ece          < 0.15          # F1
perf.update_1file_large_fixture_ms        < 300           # F7, fixture: beads
perf.update_invariance_ratio              < 1.5           # F7, t(beads)/t(flask)
docs.pretty_overhead_within_10pct_of_measured == true     # F6
```

### Nominated single headline scalar

**`t(1-file update, beads) / t(1-file update, flask)`** — currently **3.5**,
target **< 1.5**.

One number, cheap to compute, no contested assumptions, comparable across any
two fixtures, and it moves the instant either the process-start tax or the
corpus-proportional load cost improves. It is an *invariance* ratio, so it
cannot be gamed by buying a faster machine.

---

## Artifacts created by this evaluation

`.graphgraph/` directories were created in five target repos and left in place
(they are useful caches; none are tracked by the repos' git):

```
resources/flask/.graphgraph      11 MB
resources/beads/.graphgraph      47 MB
resources/express/.graphgraph    16 MB
resources/chartr/.graphgraph    8.1 MB
resources/bollard/.graphgraph   4.2 MB
```

Remove with `rm -rf <repo>/.graphgraph` if not wanted. No target source files
were modified. Scratch analysis scripts live in the session scratchpad only.
