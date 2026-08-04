# Gray-box evaluation: GraphGraph 0.1.0 across six external repositories

**Date:** 2026-07-30
**Method:** Gray-box — executed as an end user, diagnosed via the tool's own telemetry,
ground truth derived by reading the *target* repositories (never GraphGraph's source).
**Fixtures:** `resources/{flask, ripgrep, express, UniGetUI, redis, mem0}`
**Differential control:** `code-review-graph` MCP on the same repo, same queries.

---

## Verdict in one line

**Precision, telemetry honesty, and token compression are at or near the floor and
should not be touched. Recall is capped by one missing extraction feature, and
"fluidity" is capped by two pieces of plumbing.** The hard parts are done; what
remains is unusually tractable.

**Score today: ~6/10. Credible ceiling: ~9.5/10** — decomposed by layer below.

---

## Phase 0 — Instrument validation (the red test)

Before trusting any number the tool reports, I checked whether its metrics can
produce a *bad* value.

```
query "what calls zzz_nonexistent_alpha"  -> node_recall 0.0, mrr 0.0, returned_nodes 0
                                             answerability_status "unanswerable", confidence 0.0
                                             expected_unresolved: [qqq_fake_beta, www_fake_gamma]
query "quantum flux capacitor subsystem"  -> node_recall 0.0, "unanswerable"
query "what calls full_dispatch_request"  -> node_recall 1.0, mrr 1.0
```

**PASS, and emphatically.** The metric moves, nonsense yields `unanswerable` with
confidence 0.0, unresolved expectations are named explicitly, and there is no
aggregate summary laundering the failure into a green average. Co-reported metrics
are mutually consistent (no `recall=1.0` beside `mrr=0.0`).

`graphgraph eval` is a real measurement. **This is a 10/10 and it is rare.** Most
tools fail here.

---

## The single scalar

The scanner already emits the number that explains almost everything:

```
Member calls : resolved=847 ambiguous=0 unknown_receiver=537 external_or_unmatched=1038
```

**Member-call resolution rate = `resolved / (resolved + unknown_receiver)`.**

One number, already computed, cheap, comparable across repos and languages, moves
the instant extraction improves, and depends on no contested assumption. **Nominate
it as the CI gate.**

| Repo | Language | Nodes | Graph size | Resolution rate |
|---|---|---:|---:|---:|
| redis | C | 8,291 | 3.14 MB | **78.7%** (96/122) |
| flask | Python | 5,868 | 2.26 MB | **61.2%** (847/1,384) |
| mem0 | TS + Python | 29,625 | 13.04 MB | **47.1%** (2,519/5,348) |
| ripgrep | Rust | 4,866 | 1.82 MB | **34.2%** (1,210/3,538) |
| UniGetUI | C# | 6,903 | 2.90 MB | **8.3%** (477/5,723) |
| express | JavaScript | 3,434 | 1.01 MB | **2.2%** (143/6,389) |

A 36x spread between best and worst stratum. This is not a gradient — it is two
different behaviours, and the aggregate would have hidden it.

---

## Finding 1 — Extraction resolves `self.` receivers perfectly and variable receivers not at all

**Symptom.** Reverse lookup is exact when the call is `self.method()` and empty
when the receiver is a local variable, parameter, or module-level proxy.

**Evidence — direct oracle, flask (`src/flask/`), truth derived by AST-walking the target:**

| Symbol | Ground truth | GraphGraph | Result |
|---|---|---|---|
| `full_dispatch_request` | `{wsgi_app}` | `{wsgi_app}` | 1/1 |
| `preprocess_request` | `{full_dispatch_request}` | same | 1/1 |
| `finalize_request` | `{full_dispatch_request, handle_exception}` | same | 2/2 |
| `handle_user_exception` | `{full_dispatch_request}` | same | 1/1 |
| `create_url_adapter` | `{url_for, ctx.__init__}` | same | 2/2 |
| `do_teardown_request` | `{ctx.pop}` | same | 1/1 |
| `raise_routing_exception` | `{dispatch_request}` | same | 1/1 |
| `_split_blueprint_path` | `{inject_url_defaults, blueprints}` | same | 2/2 |
| `ensure_sync` | 12 callers | 9 callers | **9/12** |
| `update_template_context` | `{_render, _stream}` | `{}` | **0/2** |

Aggregate: **18/23 = 78.3% recall, 100% precision**, and every miss is the same
shape:

```python
# templating.py — MISSED
app = ctx.app                       # local var, type flows from `ctx: AppContext`
app.update_template_context(...)

# views.py — MISSED
current_app.ensure_sync(...)        # module-level LocalProxy

# ctx.py — MISSED
ctx.app.ensure_sync(f)              # two-hop attribute chain
```

Same result in Rust: `write_path_hyperlink` truth `{write_path_line,
write_binary_message}` → returned exactly those, **2/2 exact**. Where the receiver
is `self`, extraction is flawless in every language tested.

**Confirmed on the worst stratum (express/JS), direct oracle:**

| Symbol | Ground truth | GraphGraph |
|---|---|---|
| `send` | `{json, jsonp, sendStatus}` | `{sendFile}` ← **false positive** |
| `location` | `{redirect}` | `{}` |
| `status` | `{redirect, send, sendStatus}` | `{}` |

0/7 recall. The `sendFile` result is a genuine **false positive**: `lib/response.js:31`
does `var send = require('send')` and line 403 calls that *npm module*, which was
conflated with the local `res.send` method. This is the only precision defect found
in the entire run — and it is a name-collision between an external import and a
local method, i.e. the same missing type information.

**Inferred (marked as inference):** there is no local variable / parameter type
inference, so receiver resolution is limited to `self`/`cls` inside a class body
plus free functions. Languages whose idiom is `self.x()` (Python, C) score high;
languages whose idiom is `obj.method()` on untyped locals (JS), fields (C#), or
builder chains (Rust) score low.

**This is not an inherent limit of static analysis.** See Finding 2.

---

## Finding 2 — A peer tool resolves the exact edges GraphGraph misses

**Differential control:** `code-review-graph` built on the *same* flask checkout,
queried for the *same* symbols.

| Query | Ground truth | GraphGraph | code-review-graph |
|---|---|---|---|
| `update_template_context` callers | `{_render, _stream}` | **0** | **2/2 correct** |
| `ensure_sync` callers | 12 | **9** | **12/12 correct** |

I verified all 12 line-by-line against the target source before publishing this
(`ctx.py:204`, `views.py:110`, `views.py:191` — precisely GraphGraph's three misses).

**Important nuance, in fairness.** code-review-graph wins these by falling back to
*unqualified name matching* — its edge records for exactly those three show
`"target": "ensure_sync"` as a bare string, versus fully-qualified targets for the
nine it resolved structurally. So this is **recall-first vs. GraphGraph's
precision-first** posture, not a clean superiority. On a name like
`dispatch_request` — which has **7 distinct definitions** in flask — GraphGraph
correctly returns `status: "ambiguous"` with all seven candidates and refuses to
guess, which is the better behaviour.

**The finding stands regardless:** the missing edges are recoverable, and the
information needed (`ctx: AppContext` is annotated; `AppContext.app` is typed) is
present in the source. GraphGraph does not need to adopt name-matching — it needs
one-hop local type inference, which would preserve its precision.

---

## Finding 3 — `update` cost scales with corpus size, contradicting its own contract

The CLI's help text states:

> "No directory walk, no hashing of untouched files — **cost scales with `--files`,
> not repo size**."

**Symptom — observed, single file changed each time:**

| Repo | Graph size | 1-file `update` |
|---|---:|---:|
| express | 1.01 MB | 518 ms |
| flask | 2.26 MB | 654 ms |
| mem0 | 13.04 MB | **2,431 / 2,531 ms** |

**The smoking gun:** re-running `update` on an *unchanged* file — zero real work —
still costs **2,445 ms** on mem0. Cost is a near-linear function of total graph
bytes, not of Δ.

**Inferred:** the whole graph is deserialized and reserialized on every update.

**Floor.** Reparse one file with tree-sitter (~5–15 ms) + splice O(Δ) edges (~1 ms)
+ persist O(Δ) bytes (~10 ms) ≈ **~30 ms, invariant to corpus size.**

**Gap: ~80x above floor on a 13 MB graph, and diverging as the corpus grows.**

This is the direct enemy of the stated goal — context that arrives so fast you stop
thinking about it. On a large repo, the edit loop pays 2.5 s per touched file.

---

## Finding 4 — ~60% of every CLI query is process startup

**Symptom — observed, decomposed:**

```
bare `graphgraph --version`      : 436, 445, 481, 518, 625 ms   (median ~481 ms)
bare `python -c "pass"`          : 144, 161, 162 ms             (interpreter floor)
`relations` query, wall clock    : 748, 899, 960 ms
`relations` query, self-reported : 165, 201, 188 ms
```

So a ~850 ms query is roughly **~480 ms startup + ~190 ms actual work + ~180 ms
load/other**. The tool's own `r.ms` receipt is honest — it reports only its work,
and it is fast.

**The resident path already solves this.** The identical query over MCP returned a
**byte-identical result in 109 ms** with no startup tax. (Cross-path consistency
CLI↔MCP is itself a passed invariant.)

**Note a documentation conflict:** the installed global instruction says to *prefer
the CLI* over MCP tools. That recommends the path that is ~5x slower per query.

**Floor.** Hash-lookup a symbol and walk reverse edges over a 16k-edge in-memory
graph: **<5 ms.** Wall-clock gap for the CLI is **~170x**, almost entirely process
lifecycle rather than algorithmic.

---

## Finding 5 — Semantic retrieval is off by default, and it is what makes NL queries work

**Metamorphic relation tested: semantic equivalence.** Three paraphrases of one
question should retrieve substantially the same anchors.

**Default (`--source-mode auto`)** — all three report `semantic_seeds: 0`:

| Query | Anchors |
|---|---|
| "how does flask dispatch an incoming request through the app" | `full_dispatch_request`, `dispatch_request`, blueprint hooks — **good** |
| "what is the request handling lifecycle in flask" | `test_request_context` (47 nodes, dominant), `_request_from_builder_args` — **test-dominated** |
| "trace the path a HTTP request takes when it arrives" | `tests_test_request_py`, `auto_find_instance_path` — **zero production dispatch code** |

Anchor Jaccard between paraphrases ≈ **0.09**. `lexical_strength` decays
32.4 → 18.9 → 12.6 as phrasing drifts from identifier names. **RELATION VIOLATED.**

**With `--source-mode all`** (`semantic_index_state: "current"`, `semantic_seeds: 6`):

- Q1: improved — adds `docs/appcontext.rst`, `request_context`
- Q2: **materially fixed** — now anchors `finalize_request`, `preprocess_request`,
  `do_teardown_request`, and finds **`docs/lifecycle.rst` section 5**, the literally
  correct document
- Q3: **still fails** — `get_cookie_path`, `tests_test_request_py`

**So the headline capability is disabled out of the box.** The tool is measurably
better at natural-language retrieval than its default configuration reveals. This
is the cheapest high-value fix in the report: change a default.

**Secondary calibration defect (observed).** Q2's answerability confidence was
`0.2298` before and `0.2149` after — it went *down* while retrieval quality went up
substantially. Confidence is not tracking retrieval quality. Given Finding 0 showed
the eval instrument is sound, this specific signal is not.

---

## What is already at the floor — do not touch

- **Instrument integrity.** The red test, the `unknown_receiver` counter, the
  `expected_unresolved` list, `topology: partial`, `answer_complete: false`,
  `graph_complete`, `semantic:index_cold_backend` warnings. The tool volunteers
  precisely where its own model is incomplete. This is the single best thing about
  it and it is what made this evaluation cheap.
- **Precision.** 100% on Python and Rust; exactly one false positive found across
  all six repos, and that one traces to the same missing type info as Finding 1.
- **Ambiguity handling.** 7 definitions of `dispatch_request` → returns all seven as
  candidates with `status: "ambiguous"` and a `retry_candidate_id` action, rather
  than guessing. Correct.
- **Token compression.** Verified with tiktoken (`cl100k_base`) on the flask
  dispatch question:

  ```
  GraphGraph packet          : 1,244 tokens   (4,174 bytes, 41 nodes, 68 edges)
  Reading app.py+ctx.py+views.py : 19,371 tokens
  → 15.6x smaller, 93.6% reduction
  ```

  And I verified the packet is *correct*, not merely small — it contains the exact
  request lifecycle with correct edges: `wsgi_app → full_dispatch_request →
  {dispatch_request, preprocess_request, finalize_request, handle_user_exception}`,
  `dispatch_request → {ensure_sync, raise_routing_exception,
  make_default_options_response}`. This is the product working as designed.

- **Passed invariants:** idempotence (3 identical runs), monotonicity (61 → 110 →
  226 → 226 rows as `--max-nodes` rises, never decreasing), negation/null (red test),
  CLI↔MCP output identity.

---

## Score by layer

Weighted by the layer that caps the others — you cannot retrieve what was never
extracted.

| Layer | Today | Ceiling | Note |
|---|---:|---:|---|
| Instrument / telemetry honesty | **10** | 10 | At floor. Do not touch. |
| Packet format & token efficiency | **9** | 9.5 | 15.6x verified, correct content |
| Exact retrieval (given extraction) | **9** | 9.5 | Flawless where receivers resolve |
| Ambiguity & precision posture | **9** | 9.5 | 1 FP in 6 repos |
| **Extraction recall** | **4** | 9 | **Caps everything. 2.2%–78.7%** |
| NL / semantic retrieval | **5** | 8.5 | Off by default; 2/3 paraphrases fixed when on |
| Latency & incremental fluidity | **3** | 9 | ~80x and ~170x above floor |
| Confidence calibration | **6** | 9 | Doesn't track quality changes |
| **Overall** | **~6** | **~9.5** | |

The shape of this matters more than the number: **the difficult, design-heavy half
is done and is excellent.** The deficits are one extraction feature and two pieces
of plumbing — a much better position than a fast tool with an untrustworthy model.

---

## Proposed CI gates (thresholds that can fail)

| # | Gate | Current | Rationale |
|---|---|---|---|
| **G1** | **Invariance:** 1-file `update` on 13 MB graph ≤ 1.5x the same op on a 1 MB graph | **4.7x** | Converts "scales acceptably" into "does not scale at all" — the correct target |
| **G2** | 1-file `update` < 300 ms on any fixture | 2,431 ms | Edit-loop fluidity |
| **G3** | No-op `update` (unchanged file) < 100 ms | 2,445 ms | Zero work must cost near zero |
| **G4** | Member-call resolution ≥ 40% for every tree-sitter language | JS 2.2%, C# 8.3% | The single scalar |
| **G5** | CLI cold start < 200 ms | ~481 ms | Or make MCP/daemon the documented default |
| **G6** | Anchor Jaccard ≥ 0.5 across 3 paraphrases of one question | ~0.09 | Guards NL retrieval |
| **G7** | Red-test task stays at `node_recall == 0.0` | passing | Regression guard on the instrument itself |

---

## "What if" — the one capability that collapses the gap

**One-hop local type inference.** Bind local variables and parameters to types
already present in the source (`ctx: AppContext` → `AppContext.app: Flask` →
`app.update_template_context` resolves), plus a small per-language receiver table
(JS `require()` bindings and prototype assignment; C# field declarations; Rust
`let` bindings).

This single feature would:
- close Finding 1 (78.3% → near-100% on Python)
- close Finding 2 (the peer tool's advantage disappears, *without* adopting its
  lossy name-matching)
- eliminate the only false positive found (the `send` npm-module collision)
- move JS and C# off the floor — the two catastrophic strata
- raise the capped layer that is currently holding the whole system at 6

Everything else in the report is plumbing: flip the semantic default, make writes
O(Δ), and make the resident path the default entry point.

---

## What if — the shape of a version with virtually no bottlenecks

The gates above fix what is broken. This section is different: it describes what
using GraphGraph would *feel* like if every remaining friction point were removed.
Capabilities, not implementations.

Working through this evaluation, I hit the tool the way an agent actually does. Six
frictions showed up. None of them are bugs — they are all "the tool did its job and
I still had to do work around it." That residue is the real ceiling.

**1. The decision to ask.**
Today I must notice I need context, choose a command, choose a query class, and
phrase a query. That is four decisions before any information arrives, and each one
can be wrong — Finding 5 is entirely a story about phrasing. *What if context were
ambient rather than requested:* the tool observes which files are open and which
symbols were just touched, and the relevant neighbourhood is simply **already
present**, refreshed as attention moves. The correct number of context queries an
agent should issue is zero. You do not query your peripheral vision.

**2. The round trip.**
Every answer today costs a full request/response cycle, and ambiguity costs two —
`status: "ambiguous"` is the right behaviour, but it means the useful answer arrives
on the *second* call. *What if the first response were always terminal:* ambiguous
targets return the disambiguation **and** the packet for the most likely reading,
so the second call is only needed when the guess was wrong. Speculative, not
interrogative.

**3. Not knowing what you don't know.**
The tool is admirably honest — `answer_complete: false`, `topology: partial`,
`freshness: "unchecked"`. But honesty transfers the burden: I still have to decide
whether "partial" matters for *this* question, and I usually can't. *What if
incompleteness were scoped to the question rather than the graph:* not "this graph
has unresolved receivers somewhere," but "the three unresolved receivers that could
affect **this** answer are at these lines." Then partial knowledge stops being a
warning I must interpret and becomes a finite, checkable list. This is the single
biggest jump in *trust* available, and it costs nothing in latency.

**4. Freshness as a question rather than a fact.**
`freshness: "unchecked"` means every answer carries an implicit "…as of whenever you
last scanned." I either pay to check or accept unquantified staleness. *What if the
graph were never stale:* edits fold in as they happen, so freshness stops being a
field in the receipt because it is structurally always true. Findings 3 and 4 are
both really this — the graph is a *file to be rebuilt* rather than a *model that is
simply current*. Remove that and both findings evaporate together.

**5. Cost that is felt at all.**
The token win is already excellent (15.6x, verified). The remaining cost is
temporal: ~850 ms per CLI query, 2.5 s per edit. Both are small in isolation and
both are large enough to change behaviour — a tool that costs a noticeable pause is
a tool you ration. *What if retrieval were cheaper than deciding whether to
retrieve:* under roughly 50 ms, the calculus inverts. You stop budgeting calls and
start asking freely, which is when a context engine actually earns its keep. The
work is already ~190 ms of a ~850 ms query and the MCP path already proves 109 ms —
this is nearer than it looks.

**6. Confidence you can act on.**
Finding 5 showed confidence moving the *wrong direction* while quality improved. A
number I cannot act on is a number I must ignore. *What if confidence were a
decision rather than a score:* a calibrated signal that reliably answers "is this
enough to act on, or should I read source?" — such that acting on high confidence is
correct as often as the number claims. Not a better score; a signal with a
guarantee attached.

**The composite.** Put those together and the interaction is: you change a file, and
the graph is already current. You start reasoning about a symbol, and its callers,
callees, tests, and the doc section explaining it are already in front of you,
complete, with the specific unknowns named. Nothing was requested. Nothing was
waited for. No decision was made about whether the context was worth fetching.

That is the "snap your fingers" target, and it is worth being precise about the
distance: **it is not a rewrite.** Frictions 3 and 6 are presentation and calibration
over data the tool *already computes* — it knows `unknown_receiver=537`, it just
reports it globally instead of per-answer. Friction 4 collapses into Findings 3 and
4. Friction 5 is the resident path that already exists and is already fast. Friction
1 is the only genuinely new capability, and it is an integration concern rather than
an analysis one.

Which is the encouraging read of this whole report: **the expensive half — a
trustworthy model of the code, an honest instrument, and a genuinely compact packet
format — is built.** What is left is making it arrive without being asked.

---

## Coverage — what was NOT tested

Explicitly listed so silence is not read as a pass:

- `select`, `profile`, `compare`, `ingest`, `export`, `platform`, `artifacts`,
  `cache`, `graph_at_time`, `memory_context`, `repair_context`, federation
- Java (neo4j was scanned-eligible but excluded for run time), Go, Ruby, PHP,
  Kotlin, Scala, Swift, C++
- Concurrent access, corrupted-graph recovery, very large monorepos (>30k nodes)
- Doc-retrieval quality in isolation (`doc_summary` query class)
- graphify was **not** benchmarked — only `code-review-graph` was used as the
  differential control

One observation worth a follow-up: the document phase is a large share of scan cost
(flask 7.4 s of 16.5 s; mem0 13.7 s of 47.9 s) and reports `truncated=32` /
`truncated=63`. Not investigated here.

---

## Artifacts created (cleanup)

```
resources/{flask,ripgrep,express,UniGetUI,redis,mem0}/.graphgraph/
resources/flask/.code-review-graph/
```

Remove with `graphgraph remove` per repo, or delete the directories. They are
otherwise harmless caches and may be worth keeping as differential control fixtures
for the next cycle — the numbers in this report are reproducible against them.
