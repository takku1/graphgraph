# GraphGraph Evaluation — Cycle 2 (Gray-Box)

**Date:** 2026-07-21
**Method:** Gray-box. CLI execution only — no GraphGraph source or git history read.
Diagnosis driven by the tool's own telemetry (`doctor`, `profile`, `status`,
`select` caveats, `eval`) rather than by inference from internals. Ground truth
established by reading the *target* repos.
**Repos:** `flask` (controlled delta), `express` (controlled delta),
`mem0` (new — first repo with large Python **and** TypeScript volume).

---

## 0. Headline

**The most important finding this cycle is not a performance or extraction gap.
It is that `graphgraph eval` — the project's own accuracy instrument — reports
perfect recall unconditionally.** Proof in §3. Until that is fixed, no claim in
any of these reports (including my own) can be regression-tested, and every
tuning decision is unguided.

Second finding: **TypeScript call resolution is exactly 0%.** Not low — zero.

---

## 1. Answer to "do we need to refresh the skill?"

Yes. `graphgraph doctor` says so directly:

```
[Installed Skill Artifacts]
  Codex skill contract: STALE  [C:\Users\dcarn\.codex\skills\graphgraph\SKILL.md]
  Codex live validator: Current (OK)
  Repair: graphgraph install --platform codex
```

Claude Code (user), Claude Desktop, and Gemini/Antigravity MCP registrations all
report **Configured (OK)**. Project-level `.mcp.json` for this repo is not
configured, which is why the `code-review-graph` server — not GraphGraph — is the
one bound in `aiprojects/`.

`doctor` is excellent and underused. It answered this question in one command.

---

## 2. Controlled delta since cycle 1

Same repos, same commands, same machine.

### flask — real, modest improvement

| Metric | Cycle 1 | Cycle 2 | Δ |
|---|---|---|---|
| Member calls resolved | 178 | **247** | **+39%** |
| unknown_receiver | 931 | **931** | **unchanged** |
| external_or_unmatched | 1,303 | 1,234 | −69 |
| Total edges | 15,321 | 15,430 | +109 |
| `src/` methods, 0 production callers | 196/267 (73.4%) | **181/267 (67.8%)** | −5.6 pts |
| 1-file `update` | 0.92s | 0.87s | flat |
| `query` | 1.34s | 1.50s | flat |
| `status` | 0.58s | 0.53s | flat |

**Read:** the +69 resolved calls came entirely out of `external_or_unmatched`
(−69), not out of `unknown_receiver` (unchanged at 931). So the resolver got
better at matching calls to *known internal targets*, but the
**local-variable-receiver bucket was not touched at all.** That bucket
(`named_local=709` in cycle 1) is still the whole ballgame.

Orphan rate 73.4% → 67.8% is real progress and still ~68 points from where it
needs to be.

### express — byte-identical, no change

```
Cycle 1: 365 nodes, 386 edges, 227 source, 86 functions, resolved=0
Cycle 2: 366 nodes, 386 edges, 227 source, 86 functions, resolved=0
calls_per_symbol: 0.0698
```

The JavaScript extraction gap is untouched. `lib/application.js` still yields 2
of its 18 declarations.

### `--frontend cpg` — still unreachable

```
$ graphgraph frontends
cpg  avail=True conf=0.95 langs=15   "control, data, field, and type evidence"

$ graphgraph scan --help
--frontend {auto,regex,tree_sitter}
```

Unchanged from cycle 1. Still the highest-leverage unexploited capability
visible from the outside.

---

## 3. **The eval harness is non-functional** (new, critical)

`graphgraph eval --graph G --tasks T` accepts `[{"query": ..., "expected": [...]}]`.
I ran a four-task falsification suite:

| # | Task | Should be |
|---|---|---|
| 1 | teardown query, expect `do_teardown_request`, `do_teardown_appcontext` | high recall |
| 2 | teardown query, expect `zzz_nonexistent_symbol_alpha/beta` — **symbols that do not exist** | recall 0.0 |
| 3 | `"database connection pooling retry backoff"` (flask has no pooling), expect `do_teardown_request` | recall 0.0 |
| 4 | session cookie signing, expect `SecureCookieSessionInterface`, `open_session`, `save_session` | partial |

Result — **all four identical on every accuracy metric:**

```json
{ "node_recall": 1.0, "edge_recall": 1.0,
  "mrr": 0.0, "ndcg_at_5": 0.0, "ndcg_at_10": 0.0,
  "query_class": "blast_radius" }
```

**Direct proof of falsity.** For task 3, I dumped the actual packet:

```
$ graphgraph query "database connection pooling retry backoff" | grep -c do_teardown_request
0
```

The expected symbol appears **zero times** in the returned packet, and eval
reported `node_recall: 1.0`.

Three independent defects, all observable without source access:

1. **`expected` is ignored.** Recall is degenerate to 1.0; MRR/NDCG degenerate to
   0.0. `recall = 1.0` with `mrr = 0.0` is internally contradictory — if the
   expected items were truly all retrieved, MRR cannot be 0.
2. **eval measures a different system than `query` ships.** eval reported
   `returned_nodes: 12` for task 3; the actual `query` packet contains **48**
   nodes. Even with working metrics, it would be scoring a retrieval path users
   never touch.
3. **`query_class` is constant.** All four queries classified `blast_radius`,
   including "how does session cookie signing work." Either the classifier is
   bypassed in eval or it is not discriminating.

### Why this outranks every other finding

Everything else in these reports is a gap with a known direction. This one is a
**broken instrument**, and a broken instrument is worse than no instrument
because it produces confident green numbers. A `node_recall: 1.0` in CI would
pass while retrieval silently regressed to returning nothing but tutorial docs.

**You cannot converge on a floor you cannot measure.** This is the gate on
everything below.

---

## 4. **TypeScript: 0% call resolution** (new, critical)

`mem0` is the first repo tested with large volume in both languages: 382 Python
files, 360 TypeScript files, 7,957 nodes.

| Scope | Methods | Zero production callers | Rate |
|---|---|---|---|
| `mem0-ts/` (TypeScript) | 313 | **313** | **100.0%** |
| `mem0/` (Python) | 799 | 576 | 72.1% |

Verified repo-wide, not a path artifact:

```
methods in *.ts  with callers > 0  →  0
methods in *.py  with callers > 0  →  370
```

**Not a single TypeScript method in the repository has a known caller.**

Critically, this is a *different* defect from the JavaScript one, and the
distinction matters:

- **TypeScript — extraction is good, topology is empty.** 360 TS files yield 313
  methods, 248 functions, and **304 interfaces**. Symbols are found. The call
  graph among them is completely absent.
- **JavaScript — extraction itself fails.** 141 JS files yield 86 functions
  (`calls_per_symbol: 0.0698`); object-property assignment (`app.use = function`)
  is missed entirely.

For the whole JS/TS ecosystem, GraphGraph is currently a **symbol list, not a
graph.** Given that TS is arguably the largest body of code an agent tool would
be pointed at, this is a market-scope issue, not just a quality issue.

The TS case is also the *more encouraging* of the two: the hard part (parsing TS,
recovering interfaces and members) is evidently working. Something in the call
edge emission or resolution stage is dropping everything on the floor.

---

## 5. `profile` is the best health metric in the tool

`graphgraph profile` exposes `calls_per_symbol`, which collapses the entire
resolution problem into one number:

| Repo | Lang | symbol_nodes | calls_edges | **calls_per_symbol** |
|---|---|---|---|---|
| flask | Py | 1,354 | 456 | **0.337** |
| express | JS | 86 | 6 | **0.070** |
| *healthy target* | any | — | — | **~3–8** |

This should be the primary CI gate. It is cheap, single-number, language-agnostic,
and moves the instant resolution improves. It is more honest than orphan-rate
because it needs no assumption about true dead-code levels.

---

## 6. No abstention on out-of-domain queries (new)

Flask is a microframework with no connection pooling. Asked
`"database connection pooling retry backoff"`, GraphGraph returned **48 nodes** —
tutorial prose, `examples/tutorial/flaskr/db.py`, `sqlite3.rst` paragraphs — with
no confidence signal, no empty result, and no "this repo does not do that."

An agent consuming this packet will confidently answer a question about
functionality that does not exist, from documentation about a tutorial app.

> **What if retrieval could say "I don't have this"?** A confidence score on the
> packet, and an empty or explicitly-low-confidence result below threshold. This
> is the difference between a retrieval tool and a *trustworthy* one, and it is
> the failure mode most likely to burn an end user, because the output looks
> perfectly well-formed.

---

## 7. What a 10/10 requires

Ordered by leverage. Each is gated on the one above it.

### Gate 0 — A working instrument
Make `eval` capable of *failing*. Concretely: honor `expected`, compute real
recall/MRR/NDCG, run the same retrieval path `query` runs, and ship a committed
task suite over flask + mem0 with hand-verified ground truth. Add a red test
(nonexistent symbols → recall 0.0) so the harness proves it can fail.

**Nothing below this line is verifiable until this exists.** This is the whole
ballgame for reaching 10/10, because 10/10 is a *measured* claim.

### Gate 1 — Type-aware receiver resolution
`unknown_receiver` did not move at all this cycle (931 → 931). Flask is fully
annotated — `ctx: AppContext` is in the signature, in the same CST already
parsed. For annotated Python this is a lookup, not inference.
**Target: `calls_per_symbol` 0.337 → >3.0; orphan rate 67.8% → <20%.**

### Gate 2 — JS/TS parity
Two separate fixes: emit call edges for TS (extraction already works), and
capture non-`function`-keyword definitions for JS. **Target: mem0-ts orphan rate
100% → <25%; express `calls_per_symbol` 0.070 → >3.0.**
Fixture repos already identified and scanned: `express` (6-file reproduction),
`mem0-ts` (volume).

### Gate 3 — Wire `cpg`, or stop advertising it
It reports `available=True`, 15 languages, "type evidence" — the exact input Gate 1
needs — and `scan --frontend` rejects it. Either it is the answer to Gate 1 and
should be exposed, or it is aspirational and `frontends` should not claim it is
available. Right now it is the single most conspicuous loose thread visible from
the CLI.

### Gate 4 — Size-invariant edit loop
1-file `update`: flask 0.87s, sympy 5.98s (cycle 1) — still scaling with repo size
against the documented contract. Floor is ~30ms, invariant.

### Gate 5 — Resident daemon
0.32s interpreter start + graph load paid on every invocation; cache still shows
`hits=0 misses=0` (never consulted). A warm query should be ~15ms.

### Gate 6 — Abstention
Confidence-gated results. §6.

---

## 8. The "zero bottleneck" fantasy, restated

Everything I would want, in one sentence each:

- **I want to change one file in a 40,000-node graph and have the graph correct
  again before my finger leaves the key.** (Gate 4 — 200× away.)
- **I want to ask a question and get an answer in the time it takes to render the
  prompt.** (Gate 5 — 400× away, needs no correctness work.)
- **I want `calls` to mean *calls*, not *calls, if the receiver happened to be
  `self`*.** (Gates 1–3 — this is the one that makes blast-radius, dead-code, and
  multi-hop traversal *exist* as features rather than as caveats.)
- **I want to point it at a TypeScript monorepo and have it work as well as it
  works on flask.** (Gate 2 — currently 0%.)
- **I want it to tell me when it doesn't know.** (Gate 6.)
- **And I want a number I can trust that tells me which of the above I just
  improved.** (Gate 0 — and this is the only one that is currently *lying* rather
  than merely *missing*.)

The genuinely good news is unchanged from cycle 1 and worth restating, because
it is the part that cannot be brute-forced: **the packet format, anchor selection,
and epistemic honesty are at or near optimal.** A 4-node answer to "what calls
full_dispatch_request." 3KB for 27 nodes and 41 edges. `select` refusing to claim
dead code without receiver evidence. Those are taste-and-judgment problems with
no test suite, and they are solved. What remains is wiring, type lookups, I/O
discipline, and — first — an honest ruler.

---

## 9. Score

**Cycle 1: 6.5/10. Cycle 2: 6.5/10.**

Flask resolution genuinely improved (+39% resolved, −5.6 pts orphan rate), which
on its own is worth about +0.3. It is offset by two findings that were present in
cycle 1 and that I simply had not yet uncovered: TypeScript at 0% resolution
(scope of the extraction gap is roughly double what I reported), and a
non-functional eval harness (the project has been flying without instruments).

The ceiling is unchanged and still credible: **9.5**. The hard part remains done.

---

## 10. Coverage and caveats

**Exercised this cycle:** `doctor`, `profile`, `eval` (with authored task
fixtures), `select`, `scan --no-incremental`, `update`, `query`, `status`,
`frontends`, `cache`.

**Notes:** `query --details` is rejected (the flag lives on `context`).
`--show-stats` and `--show-anchors` produced no observable output difference on
`query` — unverified whether that is a no-op or a silent path.

**Not exercised:** `platform`, `memory`, `federation`, `repair`, `compare`,
`ingest`, `export`, `plan`, `render`, `final`, `traversal` policies beyond
listing, non-default packet formats, `--scope`/`--scope-mode`, MCP surface.

**Task fixtures written** (not committed to the repo): scratchpad
`tasks.json`, `falsify.json`. Worth promoting into the repo as the seed of the
Gate 0 suite.

**Artifacts:** `.graphgraph/` directories now exist in `resources/{flask, express,
ripgrep, graphiti, langgraph, sympy, mem0}`. No target-repo source was modified.

**Standing confounder:** all measurements used `tree_sitter`, because `cpg`
remains unreachable from `scan`.
