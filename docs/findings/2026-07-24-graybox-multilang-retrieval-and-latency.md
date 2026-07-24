# Gray-Box Evaluation: GraphGraph 0.1.0 — Multi-Language Retrieval, Latency, and Instrument Trust

**Date:** 2026-07-24
**Method:** Gray-box. CLI execution only; GraphGraph source and git history never read.
Ground truth derived by reading the *target* repositories (permitted and required).
**Targets:** `requests` (Python, 127f), `express` (JavaScript, 214f), `ripgrep` (Rust, 223f),
`sympy` (Python, 2068f), `flask` (Python, doc-heavy, 231f)
**Fixtures:** clean copies in scratchpad (`.git`/`.graphgraph` excluded) so all cold numbers are
uncontaminated. Several repos under `resources/` had pre-existing graphs from earlier sessions —
the first flask scan I ran reported `dirty=0 restored=231`, i.e. a warm cache. All timings below
are from the clean fixtures unless stated.

---

## Executive summary

**Today: 6/10. Credible ceiling: 9.5/10.** The hard parts are done and several are provably at
the floor. What holds it back is not architecture — it is ranking quality, one broken flag, and a
set of quality signals that are constant and therefore useless.

The single most important structural fact:

> **Extraction bounds retrieval.** JavaScript member-call resolution is **2.2%**. No ranking
> improvement can recover edges that were never extracted. Fix extraction first.

| Layer | Score | Note |
|---|---|---|
| Incremental update / splice | **10/10** | Provably invariant to repo size. Do not touch. |
| Packet encoding (`gg`) | **9/10** | Dense, well-designed, carries qualified names. |
| Extraction — Python | 7/10 | 33–47% member-call resolution |
| Extraction — Rust | 6/10 | 34% resolution, good type modeling (struct/enum/field) |
| Extraction — JavaScript | **2/10** | 2.2% resolution — categorical failure |
| Ranking / MRR | **3/10** | Rust MRR 0.007; correct node often ranked ~30th–77th |
| Quality signals (answerability, gates) | **2/10** | Constant or inverted; not decision-usable |
| Query latency | 4/10 | 77% is process startup; cold semantic build >300s |
| Self-honesty / caveats | **10/10** | Best-in-class. See "What is already excellent". |

---

## Phase 0 — Instrument validation (the red test)

Before trusting any reported number I tried to make it produce a bad value.

**`eval` PASSES.** It is a real instrument, not decorative:

| Expectation given | `node_recall` | `mrr` |
|---|---|---|
| `["quantum_flux_capacitor", "ZZZ_nonexistent_9f3a"]` | **0.0** | 0.0 |
| `["send"]` (real, bare label) | **1.0** | 0.2 |
| `["src/requests/sessions.py"]` (real path) | **1.0** | 1.0 |
| `["Session"]` | **1.0** | 0.125 |
| nonsense query `"blorptastic zibbleflorp manifold"` | 0.0, **0 nodes returned**, `unanswerable`, conf 0.0 |

Recall moves 0.0 → 1.0, MRR varies meaningfully. With no expectations it reports
`node_recall: null` + `"scored": false` + an explanatory `note` rather than faking a 1.0.
**This is exactly right and worth protecting.**

**Two instruments FAIL validation** — see Findings 3 and 4.

---

## Findings

### 1. `--max-nodes` is a no-op as a value, and *lowers* the budget below the default — CONFIRMED

**Symptom.** Passing `--max-nodes` at any value collapses the node budget *below* what the
adaptive default chooses, and the value itself is entirely ignored.

```
requests  default (adaptive)   -> node_budget=48   packet=5281 chars / 1359 tok
requests  --max-nodes 20       -> node_budget=16   packet=1720 chars
requests  --max-nodes 120      -> node_budget=16   packet=1720 chars
requests  --max-nodes 640      -> node_budget=16   packet=1720 chars
```

Reproduced on all four graphs, four different queries:

| repo | default budget | `--max-nodes 30` | `--max-nodes 200` | `--max-nodes 1000` |
|---|---|---|---|---|
| requests | 48 (5281 ch) | 16 (1720) | 16 (1720) | 16 (1720) |
| ripgrep | 48 (4186 ch) | 24 (2708) | 24 (2708) | 24 (2708) |
| express | 48 (4339 ch) | 24 (2529) | 24 (2529) | 24 (2529) |
| sympy | 48 (3605 ch) | 16 (1571) | 16 (1571) | 16 (1571) |

**Evidence.** Violates **monotonicity**: raising a budget 33× must never *remove* results. It
removes 40–67% of the packet. The collapsed value (16 vs 24) tracks graph shape, not the flag —
so the flag is being dropped and some unrelated floor applied.

**Control that proves it is specific.** `--anchor-limit` on the same graph behaves perfectly —
monotone and saturating at the 6 anchors that exist:

```
--anchor-limit 2 -> 2 anchors, 2266 ch
--anchor-limit 8 -> 6 anchors, 5281 ch
--anchor-limit 32 -> 6 anchors, 5281 ch   (correctly saturated)
```

**Impact.** An agent that widens context to recover from a thin packet gets **less** context.
This is the single highest-value bug in the report: it silently inverts the main recovery move.

**Floor.** `--max-nodes N` yields `min(N, reachable)`. **Gap: currently unbounded/inverted.**

---

### 2. Retrieval quality is stratified by language, and ranking is the weaker half

Six ground-truth queries per repo, expectations derived by reading target source
(e.g. `sessions.py:186 def resolve_redirects`, `response.js:234 res.json = function json(obj)`).

| Language | recall@packet | mean MRR | member-call resolution (self-reported) | `calls_per_symbol` |
|---|---|---|---|---|
| Python (`requests`) | **6/6** | 0.604 | 46.8% (238/509) | 0.90 |
| Python (`sympy`) | — | — | 33.1% (12110/36624) | **1.75** |
| JavaScript (`express`) | 4/6 | 0.472 | **2.2% (143/6389)** | **0.10** |
| Rust (`ripgrep`) | **2/6** | **0.007** | 34.2% (1210/3542) | 0.74 |

**Ranking is the sharper problem than recall.** On ripgrep, both "successful" queries had
`ndcg@5 = 0.0` and `ndcg@10 = 0.0`:

```
"how are gitignore files parsed"  recall=1.0  mrr=0.0132  -> correct node ranked ~76th
"how is the regex matcher built"  recall=1.0  mrr=0.0312  -> correct node ranked ~32nd
```
A 107-node / 3308-token packet whose answer sits at position 76 costs an agent nearly as much as
a miss. Even a *targeted* query (`"how does redirect handling strip authorization headers"`,
expecting `rebuild_auth`) returned `mrr=0.031`.

**Verified not an artifact.** `"how are search results printed"` scored recall 0 against
`crates/printer`. I re-derived independently: `select "path contains crates/printer" --mode count`
returns **417** nodes, and backslash form returns 0 — so forward-slash matching works and 417
relevant nodes genuinely failed to reach a 46-node packet. Real miss.

**JavaScript root cause (inference, marked as such).** Ground truth from the target: express uses
prototype-assignment style —
```js
res.json = function json(obj) {
res.sendFile = function sendFile(path, options, callback) {
```
The graph classifies these as `function` (2861) not `method` (85), and a call `res.json(...)` has
receiver `res` (a parameter), so it lands in `unknown_receiver` — 6246 of 6389. This is
*inferred* from the extraction counts plus the source style, not observed directly.

**Consequence.** `select "callers = 0"` — advertised as "symbols with no production caller",
i.e. dead-code detection — returns **2907 of 3087** express source nodes (94%). It is unusable on
JavaScript. **The tool says so itself** (see "What is already excellent").

**Floor.** Python/Rust ~85–95% resolution is achievable with scope+import binding; JS requires
prototype/object-literal assignment recognition. **Gap: JS is ~40× below the Python rate.**

---

### 3. Answerability confidence is miscalibrated — the tool's own calibration receipt proves it

`answerability_status` was `"answerable"` for **18 of 18** in-domain queries, including all 6 that
scored recall 0. It only fires on pure gibberish. Worse, the *confidence* is inverted:

- mean confidence when recall = 1 (n=12): **0.267**
- mean confidence when recall = 0 (n=6): **0.307**

The two highest-confidence queries in the whole set both failed:
`"how are static files served"` conf **0.4678** recall 0; `"how are files searched for matches"`
conf **0.4444** recall 0.

`graphgraph eval --calibration` confirms it using GraphGraph's own instrument:

```json
"resolution": 0.022222,   "uncertainty": 0.222222,
"ece": 0.212983,          "mce": 0.4444,
"bins": [ {"lower":0.2,"upper":0.4,"count":5,"mean_confidence":0.2333,"accuracy":0.4},
          {"lower":0.4,"upper":0.6,"count":1,"mean_confidence":0.4444,"accuracy":0.0} ]
```
`resolution 0.022` against `uncertainty 0.222` = **~10% discriminative power**. The higher
confidence bin has **accuracy 0.0**.

Credit where due: **the calibration instrument itself is correct and honest** — it accurately
reports that the thing it measures is broken. Keep it; wire it into CI.

---

### 4. The control receipt is constant — `state=incomplete` on 18/18, including every success

```
gates=fresh:-,route:-,anchor:+,evidence:-,semantic:+,packet:+   (17 of 18 identical)
state=incomplete  next=refresh                                   (18 of 18)
```
Only one query differed (`route:+`). So neither the confidence score **nor** the structured gate
receipt lets an agent distinguish a good packet from a bad one. `next=refresh` on every call would
drive an agent into a rebuild every single time — 82s on sympy — and still be told `incomplete`.

`evidence:-` is always negative and `semantic:+` always positive, including on a graph with **no
semantic index at all** (Finding 6). A gate that is always the same value is not a gate.

---

### 5. Universal false-positive staleness warning

Every query on every graph emits:

```
GraphGraph WARNING: extractor cache is incompatible; graph is stale for
0 changed and 0 deleted path(s); use `scan --no-incremental`.
```

**Internally contradictory**: "stale for 0 changed and 0 deleted paths" is a description of a
*fresh* graph. Verified it fires on `express` and `ripgrep`, which were scanned once and never
updated, as well as on `requests`/`sympy` which I did update. It recommends the most expensive
operation available (`scan --no-incremental` = 82s on sympy) unconditionally.

---

### 6. Silent semantic degradation at scale, plus a 300s+ cold-start cliff

`semantic.json` is consistently **~10–13× the size of the graph itself**:

| repo | graph.gg | semantic.json | ratio |
|---|---|---|---|
| requests | 361 KB | 3.5 MB | 9.8× |
| express | 957 KB | 12.5 MB | 13.1× |
| ripgrep | 1.6 MB | 16.4 MB | 10.4× |
| flask | 2.2 MB | 22.8 MB | 10.3× |
| **sympy (40571 nodes)** | 18.8 MB | **absent (0 B)** | — |

Two problems:

**(a) Cold-start cliff.** The *first* query on flask (5868 nodes, 74% doc nodes) **exceeded 300
seconds** and had to be backgrounded; it was building the 22.8 MB semantic index. Warm queries on
the same graph: **5332ms, 598ms, 601ms**. A first-run query also triggered a **HuggingFace model
download** mid-query (`fastembed_cache`, 64 MB, `bge-small-en-v1.5-onnx`) with a rate-limit
warning — a network dependency and offline failure mode on the query path.

**(b) The largest repo silently has no semantic index at all** — yet still reports
`gates=...,semantic:+`. Whatever cap skipped sympy is not surfaced to the caller, so retrieval
quietly degrades to lexical/structural at exactly the scale where semantics matter most.

Also of note: sympy's `graph.gg.manifest.json` (24.7 MB) is **larger than the graph** (18.8 MB).

---

### 7. Advertised-but-dead packet formats

`--packet` accepts 10 choices. Two are rejected by the renderer:

```
--packet hybrid -> Error: generated graph packet failed validation: unknown packet format
--packet svo    -> Error: generated graph packet failed validation: unknown packet format
```

Working formats on one identical query (`requests`, "how are cookies handled"):

| format | chars | proxy_tokens | chars/token |
|---|---|---|---|
| `sql` | 4703 | 1678 | 2.8 |
| **`gg`** | **5281** | **1359** | 3.9 |
| `gg_hybrid` | 5933 | 1524 | 3.9 |
| `gg_lex` | 7030 | 1359 | 5.2 |
| `lowlevel` | 12746 | **1072** | 11.9 |
| `semantic_arrow` | 14142 | 1276 | 11.1 |

**`proxy_tokens` is not comparable across formats.** `lowlevel` has 2.4× the characters of `gg`
but reports *fewer* tokens. Whatever the estimator does, it inverts the ranking an agent would use
to pick the cheapest format. `gg` is the right default and is genuinely well-designed.

---

### 8. Qualified names exist in packets but are not queryable

The `gg` packet renders them:
```
5 rebuild_auth @src/requests/sessions.py:309 def rebuild_auth( [SessionRedirectMixin::rebuild_auth]
```
But they are not in the `label` field that `select` and `eval` match on:

| predicate | matches |
|---|---|
| `label contains SessionRedirectMixin::rebuild_auth` | **0** |
| `label contains rebuild_auth` | 1 |

`requests` has four distinct `send` methods (`adapters.py:128`, `adapters.py:634`,
`sessions.py:132`, `sessions.py:752`) all labelled bare `send`. An agent cannot express
"who calls `Session.send`" — the natural form of the question. `eval` expectations written the
natural way (`"Session.send"`) score 0.0 and look like retrieval failures when they are
label-format mismatches. The data is already there; only the index/predicate surface is missing.

---

### 9. Documentation contradiction on `--depth` default

- `scan --depth`: *"Reuses the existing graph setting when omitted; new graphs default to **files**."*
- `context --depth`: *"'files': one node per file. '**symbols**' (default)…"*

Two subcommands state opposite defaults for the same concept.

---

## Latency decomposition — the "whip through calls fast" question

Mean of 3 runs each, Windows 11, warm OS cache:

| Operation | Time | Marginal (minus 388ms startup) |
|---|---|---|
| `python -c pass` (interpreter floor) | 86 ms | — |
| `graphgraph --version` (does nothing) | **388 ms** | — |
| `graphgraph ontology` (no graph load) | 347 ms | ~0 |
| `query` requests (908 nodes) | 472 ms | ~85 ms |
| `query` sympy (40571 nodes, warm) | ~975 ms | ~590 ms |
| `query` flask **first ever** (5868 nodes) | **>300 s** | semantic index build |
| `query` flask warm | ~600 ms | ~210 ms |

**~302 ms of every invocation is import overhead above the bare Python floor** — 77% of a typical
query's wall time is spent before any graph work begins.

Cold scans: requests 1.48s/127f · express 3.05s/214f · ripgrep 6.75s/223f · sympy 82.5s/2068f.

### The invariance gate — `update` passes it outright

The `update` help makes a falsifiable scaling claim: *"cost scales with `--files`, not repo size."*

```
update 1 file | requests   (908 nodes)  ->  342 ms   (367, 331, 328)
update 1 file | sympy    (40571 nodes)  ->  327 ms   (332, 307, 343)
```

**A 45× larger graph, and the update is if anything marginally faster.** Both numbers sit *below*
the 388ms `--version` startup measurement, i.e. the splice work is not measurable above process
launch. **This is at the floor. Do not touch it.** It is the strongest engineering result in the
evaluation, and it means the expensive-looking half of the system is already solved.

Contrast: `query` marginal cost went 85ms → 590ms (~7×) for a 45× larger graph — roughly linear in
graph size. Query reloads and rescans the whole graph every invocation.

---

## What is already excellent — do not regress these

1. **`update` size-invariance.** At the floor (above). The hard problem is done.
2. **Self-reported caveats — best-in-class.** Every `select` result auto-appends:
   > `CAVEAT: member-call resolution 2.2% (143/6389); 6246 call sites lack receiver evidence and
   > produce no calls edge, so zero-caller counts are an upper bound on dead code, not a proof
   > [scope=full_scan_snapshot; last_update=full_scan]`

   A tool that volunteers the precise denominator of its own incompleteness, unprompted, in the
   output where it matters, is rarer than it should be. This single line is what let me localize
   the JavaScript failure in one command. **Keep this pattern and extend it everywhere.**
3. **Honest capability declaration.** `frontends` reports `cpg` as
   `"PLANNED (not implemented)"`, `available: false`, `selectable: false`. No phantom features.
4. **`eval` refuses to fake a score** — `null` recall + `scored: false` + a `note` telling you the
   exact field to add.
5. **The calibration receipt correctly diagnoses its own miscalibration.**
6. **Idempotence holds** — identical byte-for-byte output across runs (5544 chars, `-eq` True).
7. **`--anchor-limit` is correctly monotone and saturating.**
8. **`gg` packet design** — relation legend + numbered nodes + `path:line` + signature +
   qualified name, at 3.9 chars/token. Dense and genuinely good.
9. **Honest documented overhead** — `--pretty` documented as "~26% more tokens"; measured **22.6%**.
10. **`profile` exposes real shape metrics** including the best available quality scalar.

---

## The road to 10/10 — ranked by value per unit of work

### Nominated CI scalar: `calls_per_symbol` (from `graphgraph profile`)

One number, already computed, costs nothing, comparable across repos and languages, requires no
contested assumptions, and moves the instant member-call resolution improves:

```
sympy (py) 1.75   requests (py) 0.90   ripgrep (rs) 0.74   express (js) 0.10   flask (py) 0.40
```

**Gate: `calls_per_symbol >= 0.5` for every supported language fixture.** JavaScript fails at
0.10 today. This one number would have caught Finding 2 automatically.

### Proposed gates (thresholds that can fail, not adjectives)

| Gate | Threshold | Today |
|---|---|---|
| Budget monotonicity | `--max-nodes N` ⇒ nodes non-decreasing in N; never below adaptive default | **FAILS** |
| Extraction quality | `calls_per_symbol >= 0.5` per language fixture | FAILS (js 0.10) |
| Ranking | mean `mrr >= 0.3` and `ndcg@10 > 0` on a 6-query fixture per language | FAILS (rust 0.007) |
| Update invariance | 1-file update on 40k-node graph within 1.5× of 900-node graph | **PASSES (0.96×)** |
| Cold first query | < 5 s on any fixture | FAILS (flask >300 s) |
| Freshness signal | no staleness warning when 0 changed and 0 deleted | **FAILS** |
| Signal variance | `state`/gates must not be constant across a mixed pass/fail fixture | **FAILS** |
| Format liveness | every `--packet` choice renders | FAILS (hybrid, svo) |

### The four changes that collapse the gaps

**1. Fix `--max-nodes` (hours).** Highest value per effort in the report. It inverts the agent's
primary recovery move. `--anchor-limit` already shows the correct pattern.

**2. Persistent process / daemon (`graphgraph serve`).** *What if* the graph stayed resident?
- Floor: query on a 361 KB graph = load-once + anchor + bounded BFS ≈ **5–15 ms**.
- Today: 472 ms, of which ~302 ms is import overhead and ~85 ms is reload-per-call.
- **Gap: ~30–90× above floor.** A resident process collapses *every* call to its marginal cost.
  Combined with the already-invariant `update`, this yields the "whip through calls" property
  directly: **`update` is already O(Δ); only the process boundary is stopping the whole loop from
  being O(Δ).** That is a remarkably good position to be in — the expensive half is done.
- Cheaper interim win: lazy-import the heavy deps (embedding stack) so `--version`-class and
  structural commands do not pay 302 ms. Floor for startup ≈ 30 ms → **~10× on every invocation**.

**3. Make one quality signal actually vary.** The infrastructure exists (`gates`, `state`,
`answerability`, `--calibration`); it just does not discriminate. Target: `resolution > 0.10`
and `ece < 0.10` on a mixed fixture. Concretely, anchor-score margin and
`matched_anchor_paths / expected_scope` are already computed and would vary. Without this an
agent cannot tell a 3308-token packet with the answer at rank 76 from a good one — which is
precisely when it should widen or fall back to grep.

**4. Index qualified names (`Class::method`) as first-class labels.** The data is already in the
packet renderer. Exposing it to `select`/`eval` predicates fixes disambiguation of the four
`send` methods, makes eval expectations writable the natural way, and would likely lift MRR
directly, since `rebuild_auth` currently ranks ~32nd on a query that names it.

### Secondary
- Precompute `semantic.json` during `scan` (with a progress line) instead of on first query;
  vendor or pre-fetch the embedding model so the query path has no network dependency.
- Surface the cap that skipped sympy's semantic index instead of reporting `semantic:+`.
- Down-weight `paragraph` nodes for code-class queries: flask is 74% doc nodes and 36% weak edges.
  (Retrieval held up — a routing query returned 40 `.py` lines vs 7 `.rst`/`.md` — so this is a
  *cost* problem, not a correctness one: 10× index size and the 300s build for little code gain.)
- Remove or implement `hybrid` / `svo`; reconcile the `--depth` default documentation.

---

## Coverage — what was NOT tested

Explicitly not exercised, and silence here must not be read as a pass:
`plan`, `render`, `final`, `snippets`, `ingest`, `export`, `compare`, `validate-graph`, `remove`,
`cache`, `artifacts`, `install`, `platform`, `graph_at_time`/time-travel, memory scoping
(`--memory-scope`), federation/cross-repo, MCP server surface (CLI only), `--history` extraction,
`--scope`/`--scope-mode`, and the `spreading_activation` query class. `doctor` was attempted but
rejects `-d`; not retried from a repo cwd.

Single-machine, Windows 11, Python 3.12, n=3 per timing. Cold-cache effects were observed
(first sympy query 7135 ms vs ~975 ms warm) and warm figures are used throughout except where
cold is the point.

## Artifacts created

- **`C:\Users\dcarn\aiprojects\resources\flask\.graphgraph\`** — graph pre-existed from an earlier
  session, but this evaluation added **`semantic.json` (22.8 MB)** and refreshed `kv_cache.json`.
  Remove those two files to restore prior state.
- Scratchpad fixtures (`fx/requests`, `fx/express`, `fx/ripgrep`, `fx/sympy`, ~200 MB) and eval
  task JSON — session-scoped, safe to delete wholesale.
- `C:\Users\dcarn\AppData\Local\Temp\fastembed_cache` (64 MB) — downloaded embedding model,
  shared/global, safe to keep.
- No `resources/` source files were modified.
