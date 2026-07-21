# GraphGraph Evaluation — Cycle 3 (Gray-Box)

**Date:** 2026-07-21
**Method:** `graybox` skill (`~/.claude/skills/graybox/`). Strict black box on
GraphGraph source **and** git history. Target repos read freely for ground truth.
**Repos:** flask (control fixture), redis (**new — first C-language coverage**),
mem0, express, sympy, graphiti, langgraph.

---

## 0. Headline

**Three of five cycle-2 findings are fixed, including the severity-1 data loss and
the broken instrument.** With a trustworthy instrument for the first time, real
accuracy numbers are now measurable:

**Mean recall 0.810** over 7 hand-verified tasks — genuinely respectable.
**NDCG@5 = 0.000 on 4 of those 7** — the right nodes are retrieved and then
buried.

The new headline defect: **retrieval is lexical, not semantic.** `JSONProvider` is
in the graph; querying its name returns 8 hits; querying *"how is JSON serialized
and configured"* returns **0**.

**Score: 6.5 → 7.5.**

---

## 1. Phase 0 — Instrument validation (passed)

Per skill protocol, the instrument was validated before anything was measured.

### Red test — PASS

| Task | Expected | recall |
|---|---|---|
| teardown query, real symbol | `do_teardown_request` | **1.00** |
| teardown query, **nonexistent** symbols | `zzz_nonexistent_alpha/beta` | **0.00** |

The metric moves. `expected` is honored. Cycle 2's unconditional `1.0` is gone.

### Internal consistency — PASS

`returned_nodes: 48` now matches the actual `query` packet (was 12 in cycle 2 —
eval was scoring a different retrieval path than the one shipped). MRR is live and
consistent with NDCG: task 1 reports `mrr=0.083` (= 1/12, first hit at rank 12)
alongside `ndcg_at_5=0.0`, which is exactly right for an item outside the top 5.
No contradictory metric pairs found.

### Cross-surface consistency — PASS

`scan`-reported and `status`-reported member-call counters, same graph,
immediately consecutive: `resolved=1366 ambiguous=30 unknown_receiver=1981
external_or_unmatched=9310` — identical on both surfaces.

**The instrument is trustworthy. Everything below is measured, not inferred.**

---

## 2. Cycle-2 regression checks

| # | Cycle-2 finding | Status |
|---|---|---|
| 1 | **SEV-1: `scan` w/o `--docs` destroys 72% of graph** | ✅ **FIXED** — verified on flask *and* redis; docs preserved |
| 2 | **Eval harness reports recall 1.0 unconditionally** | ✅ **FIXED** — red test passes |
| 3 | **TypeScript call resolution exactly 0%** | ✅ **FIXED** — 0 → 108 TS methods with callers |
| 4 | Incremental equivalence +1 edge divergence | ✅ **FIXED** — rebuild == no-op update, both repos |
| 5 | JavaScript extraction gap | ❌ **unchanged**, 3rd cycle |
| 6 | `cpg` frontend unreachable | ❌ **unchanged**, 3rd cycle |
| 7 | Scaling contract violated | ❌ **unchanged** |
| 8 | No abstention | ❌ **unchanged / worse characterized** |

### Detail: SEV-1 data loss — fixed

```
before:                          nodes=5869 doc_nodes=4331
$ scan --depth symbols --no-incremental      # no --docs
after:                           nodes=5869 doc_nodes=4331
```
Confirmed independently on redis (`nodes=7764 doc_nodes=907` → unchanged). The
documented "reuses the existing graph setting when omitted" contract now holds.

### Detail: TypeScript — categorically fixed

| Metric | Cycle 2 | Cycle 3 |
|---|---|---|
| TS methods with ≥1 caller | **0** | **108** |
| TS methods total | 313 | 453 |
| `mem0-ts` orphan rate | **100.0%** | **68.1%** |
| mem0 member-call resolution | 30.6% | **40.8%** |

TS is now at roughly Python parity (flask methods: 32.2% with callers; mem0-ts:
31.9%). The code path that emitted nothing now emits edges. Extraction also
improved (313 → 453 methods).

**This validates cycle 2's stratification claim** that TS and JS were two distinct
defects rather than one gradient — one was fixed, the other is byte-identical.

---

## 3. NEW — First real accuracy measurement

Seven tasks, ground truth verified by grep against flask source, plus a red
control. This suite should be committed as the seed of a regression gate.

| Query | recall | MRR | NDCG@5 | tokens |
|---|---|---|---|---|
| request context teardown | 1.00 | 0.083 | **0.000** | 1155 |
| session cookies signed and loaded | 1.00 | 0.250 | 0.264 | 1295 |
| what calls `full_dispatch_request` | 1.00 | 0.333 | 0.500 | 109 |
| request handling chain | 1.00 | 0.500 | 0.345 | 941 |
| how is a URL built for an endpoint | 1.00 | 0.083 | **0.000** | 1042 |
| how is JSON serialized and configured | **0.00** | 0.000 | **0.000** | 983 |
| the flask CLI group | 0.67 | 0.167 | **0.000** | 936 |
| RED CONTROL (nonexistent) | 0.00 | — | — | 191 |

**Mean recall (excl. red control): 0.810**

### Read

- **Recall is good.** 0.81 with 5 of 7 tasks perfect. The graph contains the right
  material and retrieval usually reaches it.
- **Ranking is poor.** NDCG@5 = 0.000 on 4 of 7 — *no relevant item in the top 5*.
  Mean MRR ≈ 0.20, i.e. the first relevant hit lands around rank 5–12 in packets
  of 30–48 nodes.
- **Token economy remains excellent.** ~1,000 tokens per answer; the reverse-lookup
  task answered in **109 tokens**.

Ranking matters even when the consumer reads the whole packet: it determines what
survives truncation, it drives attention weighting, and a weak ranking signal will
degrade into a precision problem as graphs grow.

---

## 4. NEW — Retrieval is lexical, not semantic (the core defect)

Sharpest finding of the cycle, and it explains items 3, 8, and the ranking numbers
above.

**Symptom.** Task 6 scored recall 0.00.

**Evidence — extraction is NOT the problem:**

```
$ graphgraph select "label contains JSONProvider"
  JSONProvider        @src/flask/json/provider.py:19   kind=class
  DefaultJSONProvider @src/flask/json/provider.py:124  kind=class

$ graphgraph query "JSONProvider"                        → 8 hits
$ graphgraph query "how is JSON serialized and configured" → 0 hits
```

Same target, same graph. **Naming the symbol: perfect. Describing the concept:
total miss.**

**Inferred (marked as inference):** anchor selection is dominated by literal token
overlap between query and node label/path. Concept-level queries only succeed when
the concept name happens to appear in an identifier.

**Corroboration** — this predicts exactly the two other unexplained behaviors:
- Low MRR/NDCG: lexically-adjacent nodes outrank semantically-correct ones.
- No abstention: gibberish still finds weak partial lexical matches, so *something*
  is always returned.

**Floor.** For a tool whose value proposition is *"ask a question, get context,"*
concept→symbol mapping is the product. A user who already knows the symbol name
does not need a context graph — `grep` suffices.

**What if there were an embedding index over symbol labels + docstrings + doc
sections?** Recall on descriptive queries goes to parity with named queries;
ranking gets a real relevance signal; and — because embedding similarity is a
score rather than a match — abstention becomes possible for free via a threshold.
**One capability fixes three findings.**

---

## 5. NEW — Language stratification (first C coverage)

`redis` adds the first C data point across three cycles.

| Repo | Primary lang | resolved | unknown_recv | **resolution** | **calls_per_symbol** |
|---|---|---|---|---|---|
| **redis** | **C** | 96 | 26 | **78.7%** | **2.249** |
| graphiti | Python | 1,245 | 593 | 67.7% | 1.242 |
| mem0 | Py + TS | 1,366 | 1,981 | 40.8% | 0.823 |
| langgraph | Python | 3,563 | 6,208 | 36.5% | 1.331 |
| flask | Python | 247 | 931 | 21.0% | 0.337 |
| express | JavaScript | 0 | 0 | n/a | **0.070** |

**C is by far the best-supported language** — 6.7× flask's `calls_per_symbol` and
32× express's. Verified against ground truth: `addReply` correctly shows **124
callers**; a "what does processCommand call" query returned genuine callees
(`ACLCheckAllPerm`, `performEvictions`, `queueMultiCommand`, `flagTransaction`).

### Honest caveat on a previous claim

Cycles 1–2 attributed the Python deficit primarily to **receiver resolution**. A
within-repo split refines that:

| Repo | kind | with callers |
|---|---|---|
| flask `src/` | function | 38.1% |
| flask `src/` | method | 32.2% |
| redis | function (C) | 60.2% |

The function/method gap inside flask is only **6 points** — much smaller than the
receiver hypothesis predicts. Python plain *functions* (38.1%) still trail C
functions (60.2%) by 22 points, which receivers cannot explain.

**However, orphan rates are confounded** by library-vs-application structure: a
framework's public API legitimately has no internal callers, while an application
like redis calls itself constantly. I therefore treat orphan rate as a weak proxy
and rely on the tool's **direct** counter instead: `unknown_receiver=931` on flask
is a first-party measurement that 931 call sites produce no edge — no structural
assumption required. That number is unchanged this cycle.

---

## 6. Metamorphic relation suite

Run on redis (new repo) and flask (original failure site).

| MR | redis | flask | Note |
|---|---|---|---|
| Idempotence (identical query ×2) | ✅ PASS | ✅ PASS | byte-identical |
| Budget monotonicity (`--max-nodes` 15→45) | ✅ PASS | ✅ PASS | 0 members dropped |
| Docs preservation (cycle-2 sev-1) | ✅ PASS | ✅ PASS | **regression fixed** |
| Incremental equivalence (rebuild vs no-op update) | ✅ PASS | ✅ PASS | **+1 divergence fixed** |
| Cross-surface consistency (scan vs status) | ✅ PASS | — | counters identical |
| **Negation / abstention** | — | ❌ **FAIL** | see below |

### MR: Negation — FAIL

```
$ graphgraph query "zzqx blorf wug frobnicate"     # pure gibberish
→ 17 nodes, 1023 bytes
   "Extensions @docs/extensions.rst:1"
   "Welcome to Flask @docs/index.rst:3"
   "The Base Layout @docs/tutorial/templates.rst:38"
   ...
```

Nonsense input yields a well-formed 17-node packet with no confidence signal.
A query for an absent feature ("database connection pooling retry backoff" on a
microframework with none) returns 48 nodes — unchanged from cycle 2.

This is the failure mode most likely to reach an end user undetected, because the
output is perfectly well-formed. §4's embedding index would fix it via a score
threshold.

---

## 7. Performance — unchanged

Fixed startup: **0.304s** (paid every invocation).

| Repo | Graph | `status` | `query` | 1-file `update` |
|---|---|---|---|---|
| flask | 2.2 MB | 0.54s | 1.29s | **0.85s** |
| redis | 3.0 MB | 0.54s | 1.42s | **1.63s** |
| sympy | 18.6 MB | 1.56s | 7.12s | **5.82s** |

**The documented contract remains violated.** `update --help`: *"cost scales with
`--files`, not repo size."* Identical 1-file work costs 0.85s / 1.63s / 5.82s —
roughly linear in graph size, ~7× across the range.

**Floor:** reparse one file (~5 ms), splice O(Δ), persist O(Δ) → **~30 ms,
invariant to corpus size. ~190× off, unchanged from cycle 1.**

---

## 8. What is at the floor — do not touch

Restating, because three cycles have not moved it and it is the part that cannot
be brute-forced:

- **Packet encoding.** ~1,000 tokens per answer; the reverse-lookup task answered
  correctly in **109 tokens**.
- **Reverse lookup.** "what calls `full_dispatch_request`" → recall 1.00, MRR
  0.333, 109 tokens. This is optimal.
- **Epistemic honesty.** `select` still refuses to claim dead code without
  receiver evidence, and now `status` additionally flags staleness and scope.
- **Determinism.** Idempotence and monotonicity pass on every repo tested.

---

## 9. Gates for cycle 4

```
GATE 0  eval red control                  recall == 0.0          ✅ holding
GATE 1  mean recall on flask suite        ≥ 0.85    (now 0.810)
GATE 2  NDCG@5 on flask suite             ≥ 0.40    (now 0.158 mean)  ← new priority
GATE 3  descriptive-query parity          JSON task recall > 0   (now 0.00)
GATE 4  abstention                        gibberish → 0 nodes    (now 17)
GATE 5  express calls_per_symbol          > 1.0     (now 0.070)
GATE 6  flask unknown_receiver            < 500     (now 931)
GATE 7  1-file update invariance          sympy ≈ flask          (now 6.8×)
```

GATE 2 and GATE 3 are new and should be the focus — they are the same underlying
fix (§4), and that fix also delivers GATE 4.

---

## 10. Score: 7.5 / 10 (was 6.5). Ceiling: 9.5.

**Up a full point**, earned by: severity-1 data loss fixed, the instrument fixed
(which unblocks everything else), TypeScript fixed from a hard 0%, and — now
measurable — recall of 0.81, which is better than I would have guessed in cycle 2.

**Held back from 8+** by: retrieval that succeeds on names and fails on concepts
(§4), ranking that buries correct answers below rank 5 in over half of tasks, no
abstention, an untouched JavaScript path in its third cycle, and an incremental
loop still ~190× off floor.

| Layer | C1 | C2 | C3 |
|---|---|---|---|
| Packet encoding | 9.5 | 9.5 | **9.5** |
| Epistemic honesty | 10 | 10 | **10** |
| Instrument | — | **1** | **9** |
| Retrieval recall | ? | ? | **8** |
| Retrieval ranking | ? | ? | **3** |
| Extraction — C | — | — | **8** |
| Extraction — Python | 4 | 4 | **4** |
| Extraction — TypeScript | — | **0** | **5** |
| Extraction — JavaScript | 2 | 2 | **2** |
| Runtime / IO | 3 | 3 | **3** |

The trajectory is good and the fixes landed where they were pointed. The single
highest-leverage remaining item is no longer extraction — it is **semantic anchor
selection** (§4), which alone would move GATE 2, GATE 3, and GATE 4.

---

## 11. Coverage and caveats

**Exercised:** `scan`, `update`, `query`, `status`, `select`, `profile`, `doctor`,
`eval` (with authored fixtures), `frontends`, `cache`, `--json`, `--max-nodes`,
`--query-class`, `--no-incremental`, `--docs`.

**Not exercised:** `platform`, `memory`, `federation`, `repair`, `compare`,
`ingest`, `export`, `plan`, `render`, `final`, `snippets`, `traversal` policies
beyond listing, non-default packet formats, `--scope`/`--scope-mode`, MCP surface.

**Not scanned:** z3, lean4, crewAI, PufferLib, KGCompass, SerpentAI, MoBA,
requests, and remaining `resources/` entries.

**Fixtures to promote into the repo:** `flask_suite.json` (7 hand-verified tasks +
red control, ground truth grep-verified against flask source) — this is the seed
of GATE 1–3.

**Artifacts:** `.graphgraph/` directories in `resources/{flask, express, ripgrep,
graphiti, langgraph, sympy, mem0, redis}`. No target source modified. Flask's
graph was left restored (5,869 nodes) after deliberate degradation testing.

**Standing confounder:** all measurements used `tree_sitter`; `cpg` remains
unreachable from `scan` for a third cycle. If it carries real type evidence, §5's
resolution table must be re-measured.

**Method note:** cycles 1–2 over-attributed the Python call-graph deficit to
receiver resolution. §5 corrects this with a within-repo function/method split and
states the library-vs-application confound explicitly.
