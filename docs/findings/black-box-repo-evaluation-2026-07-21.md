# GraphGraph Black-Box Evaluation — Test Repo Selection & Distance-to-Floor

**Date:** 2026-07-21
**Method:** CLI only. No GraphGraph source was read. No code edited. Ground truth
established by reading the *target* repos (flask, express) with grep/Read.
**Corpus:** `C:\Users\dcarn\aiprojects\resources\`

---

## 0. Correction issued during this run

An earlier interim conclusion in this session — "the packet drops the call-chain
backbone edges" — **was wrong and is retracted.** It came from truncating the
`[e]` section with `head -40`. The full packet contains `9 6`, `9 8`, `9 15`,
`10 8`, i.e. `full_dispatch_request → dispatch_request / finalize_request /
preprocess_request` and `handle_exception → finalize_request`: all four
ground-truth backbone edges, complete. Packet edge selection is sound.
Recorded here because the retracted claim was the more dramatic one and should
not survive in anyone's memory of this evaluation.

---

## 1. Recommended test repos

| Tier | Repo | Why | Cold scan |
|---|---|---|---|
| **Daily driver** | `resources/flask` | 83 py files, fully type-annotated, docs + code + tests, canonical ground truth (`wsgi_app → full_dispatch_request → …`). Full loop in <4s. | 3.7s |
| **Ideal-conditions** | `resources/graphiti` | Best member-call resolution observed (67.7%). Modern typed async Python; same domain as GraphGraph itself. | 4.3s |
| **Scaling adversary** | `resources/sympy` | 40,570 nodes / 181,604 edges / 18.6 MB. Exposes every O(graph) operation. Use as a regression gate. | 84.3s |
| **Correctness adversary (JS)** | `resources/express` | Currently a *failing* case — see §3.2. Fix target, not a passing test. | 0.9s |
| **Non-Python control** | `resources/ripgrep` | 101 Rust files, 3,235 source nodes. Guards against Python overfit. | 5.7s |
| Next frontier (untested) | `z3`, `lean4` | 2,062 / 2,881 C++ files, polyglot. | — |

Set the regression gate on **flask + sympy**: flask proves the loop is snappy,
sympy proves it *stays* snappy. Everything currently interesting lives in the
delta between those two.

---

## 2. Measured baseline

### Build / topology

| Repo | Lang | Src files | Nodes | Edges | Cold scan | Graph size |
|---|---|---|---|---|---|---|
| express | JS | 141 | 365 | 386 | 0.9s | — |
| flask | Py | 83 | 5,868 | 15,321 | 3.7s | 2.2 MB |
| graphiti | Py | 255 | 2,932 | 11,934 | 4.3s | — |
| ripgrep | Rust | 101 | 4,214 | 12,515 | 5.7s | — |
| langgraph | Py | 447 | 8,469 | 29,794 | 14.9s | 3.8 MB |
| sympy | Py | 1,574 | 40,570 | 181,604 | 84.3s | 18.6 MB |

### Loop latency

| Op | flask (5.8k nodes) | sympy (40.5k nodes) | Ratio |
|---|---|---|---|
| `status` (load-dominated) | 0.58s | 1.56s | 2.7× |
| `update --files` (**1 file**) | 0.92s | 5.98s | **6.5×** |
| `query` | 1.34s | 6.64s | 5.0× |
| `query` (identical repeat) | — | 6.64s | **1.0× — no cache benefit** |
| CLI floor (`--help`) | 0.32s | 0.32s | — |

### What is genuinely excellent

- **Packet economy.** A flask trace query returns 27 nodes + 41 edges in
  **3,002 bytes (~750 tokens)** — 2,661 B of nodes, 213 B of edges. Edges are
  **7%** of packet cost while carrying the structural payload. The `#gg`
  interning format is at or near the information-theoretic floor for this content.
- **Anchor precision.** "request context teardown" → `do_teardown_appcontext`,
  `do_teardown_request`, `ctx.py`, `reqcontext.rst`. 4.5 KB, no hunting.
- **Reverse lookup.** "what calls full_dispatch_request" → a **4-node** packet
  containing exactly the answer. This is the floor. It cannot be improved.
- **Epistemic honesty.** `select` refuses to claim dead code:
  *"18 call sites lack receiver evidence and produce no calls edge, so zero-caller
  counts are an upper bound on dead code, not a proof."* Most tools in this
  category would have silently reported dead code. This is a genuine moat —
  do not regress it.

---

## 3. Distance to floor

Graded against the theoretical optimum, not against "works."

### 3.1 Member-call resolution — **the ceiling on everything**

`resolved / (resolved + unknown_receiver)`:

| Repo | Resolved | Unknown receiver | Rate |
|---|---|---|---|
| flask | 178 | 931 | **16.1%** |
| sympy | 8,497 | 24,515 | **25.7%** |
| ripgrep | 1,210 | 2,311 | 34.4% |
| langgraph | 3,563 | 6,208 | 36.5% |
| graphiti | 1,245 | 593 | 67.7% |

Downstream consequence, non-test symbols only:

- **flask `src/`: 196 of 267 methods (73.4%) have zero known callers.**
- **graphiti: 920 of 1,060 methods (86.8%) have zero known callers.**

True dead-method rate in these libraries is approximately zero. So the `calls`
relation — the highest-value edge in a code context graph — is roughly **15–27%
complete for Python method calls.**

Receiver-shape census in flask `src/`: **149** `self.X(` call sites vs **750**
other-receiver sites. `self.` resolves reliably (verified: `wsgi_app →
full_dispatch_request` is present and correct). It is only **17%** of the
member-call surface. The unresolved bucket is dominated by `named_local=709` —
`obj = Foo(); obj.method()`.

Why this is the ceiling: blast radius, impact analysis, and dead-code detection
are all reachability queries over `calls`. At 20% edge completeness, a 1-hop
answer is advisory and a 3-hop answer is noise. The tool is currently honest
enough to say so, which converts a correctness bug into a *shipped-feature*
blocker.

> **What if the graph read the type annotations it is already parsing?**
> Flask is fully annotated: `def full_dispatch_request(self, ctx: AppContext) ->
> Response`. When the extractor sees `ctx.request`, the type of `ctx` is *in the
> same signature, in the same file, in the same CST that tree-sitter already
> built.* It is being discarded. For annotated Python this is not inference —
> it is a lookup. Resolution plausibly goes 25% → 85%+ with no new machinery and
> no new dependency.

### 3.2 The `cpg` frontend is built, advertised, and unreachable

```
$ graphgraph frontends
regex        avail=True conf=0.75 langs=0
tree_sitter  avail=True conf=0.95 langs=15
cpg          avail=True conf=0.95 langs=15
    "Multi-language control, data, field, and type evidence
     normalized into GraphGraph IR."

$ graphgraph scan -d . --frontend cpg
error: argument --frontend: invalid choice: 'cpg'
       (choose from auto, regex, tree_sitter)
```

**The frontend carrying "type evidence" — the exact missing input for §3.1 —
reports itself available with 15 ready languages and cannot be selected from the
primary build path.** Every scan in this evaluation ran `tree_sitter`.

This is the single highest-leverage item in the project. The capability appears
to exist; the CLI does not expose it. If wiring `cpg` into `scan` moves flask's
resolution rate off 16.1%, that one change lifts the ceiling on impact analysis,
dead-code detection, and multi-hop traversal simultaneously.

**Verify this before anything else.** It may be a one-line argparse change
standing between the current state and a categorically better tool.

### 3.3 JavaScript extraction — 10–20× density deficit

Source nodes per source file:

| Repo | Lang | Density |
|---|---|---|
| ripgrep | Rust | 32.0 |
| sympy | Py | 25.3 |
| langgraph | Py | 18.3 |
| flask | Py | 17.3 |
| graphiti | Py | 10.9 |
| **express** | **JS** | **1.6** |

Ground truth: `express/lib/application.js` contains **16** `app.X = function`
declarations and **2** bare `function` declarations. The graph captured the 2
bare ones. **89% of express's core public API is invisible.** Express reports
`resolved=0 ambiguous=0 unknown_receiver=0` — it detected *no member calls at
all*.

Consequence: a query for "routing and middleware dispatch" returned mostly
`examples/` noise, because `lib/` — the actual library — is nearly empty in the
graph.

This is **not** a missing-language problem. `javascript`, `typescript`, and `tsx`
are all listed ready. It is an extraction-rule gap: only top-level `function foo()`
is captured. Object-property assignment (`app.use = function use(fn)`),
`const f = () => {}`, and class methods appear to be missed.

> **What if JS/TS reached Python parity?** The npm ecosystem — the largest body
> of code a context tool could address — goes from unusable to first-class.
> `express` is the smallest possible reproduction: 6 files in `lib/`, known
> ground truth, 0.9s scan. It is a perfect fixture.

### 3.4 Incremental update violates its own contract

`graphgraph update --help` states:

> *"cost scales with `--files`, not repo size."*

Measured, **1 file in both cases**:

- flask (2.2 MB graph): **0.92s**
- sympy (18.6 MB graph): **5.98s** — 6.5× slower for identical work

Cost scales with **repo size**, not change size. Isolating the components:
`status` (load-dominated) on sympy is 1.56s, so ~1.0s is the 18.6 MB read. The
remaining ~4.5s is work proportional to graph size — the most likely candidates
being the full-graph structural validation that runs on every update
(`Structural validation: PASS graph.gg nodes=40570 edges=181617` — all 40,570
nodes revalidated after a 1-file change) and the full 18.6 MB rewrite. There is
no `--no-validate` escape hatch.

**Floor:** reparse one file (~5 ms tree-sitter), diff its symbol set, splice
O(Δ) edges, persist O(Δ) bytes. **~10–50 ms, invariant to repo size.**
**Current: 5.98s. Roughly 120–600× above floor, and diverging.**

> **What if the store were append-only and validation were scoped to the splice?**
> A 1-file update becomes ~30 ms on a 40k-node graph — the same as on a 5k-node
> graph. Repo size stops being a variable in the edit loop. This is the difference
> between "fast on small repos" and "fast, period," and it is the single change
> that makes the tool feel unbounded.

### 3.5 The cache is inert

```
$ graphgraph cache
Cache: 2/256 entries  hits=0  misses=0  hit_rate=0%
```

`misses=0` alongside `hits=0` means the query path **never consults the cache**.
An identical repeated query on sympy cost 6.635s vs 6.645s — no benefit.

The deeper point: with a 6.6s query on a 40k-node graph, ~1.5s is graph load and
0.32s is Python interpreter startup, paid **on every single invocation**.

> **What if there were a resident daemon?** Hold the graph in memory across
> queries. Interpreter start and graph load — currently ~1.8s of every sympy
> query — collapse to zero. Query cost approaches pure ranking + serialize:
> **~10–20 ms.** At that point the cache is nearly redundant, and the tool stops
> being a CLI you invoke and becomes something you converse with. This is the
> largest perceived-speed win available, and unlike §3.1 it requires no new
> correctness work.

---

## 4. The zero-bottleneck composite

If all four "what ifs" land, the loop on **sympy** — the worst case in this
corpus — becomes:

| Op | Now | Floor | Gap |
|---|---|---|---|
| Cold scan (once, ever) | 84.3s | ~40s (parallel extract) | 2× |
| 1-file update | 5.98s | ~30 ms | **~200×** |
| Query (warm daemon) | 6.64s | ~15 ms | **~440×** |
| Call-edge completeness | ~26% | ~90% (typed) | **3.5×** |
| JS node density | 1.6/file | ~17/file | **~10×** |

The cold scan is the only cost that is *irreducibly* large, and it is paid once.
Everything else in the loop is currently 200–440× above its floor for reasons
that look structural rather than algorithmic: whole-graph load, whole-graph
validation, whole-graph rewrite, cold interpreter, unconsulted cache.

**Nothing in this list requires a research breakthrough.** The type evidence
already exists in the source and possibly in an already-built frontend. The
incremental path already has the right CLI shape and simply does not honor it.
The daemon is engineering. That is an unusually good position: the gap to
"god-tier" here is wiring and I/O discipline, not invention.

The thing already at the floor — packet format and anchor selection — is the
hard part, and it is done.

---

## 5. Suggested regression gates

```
flask     1-file update   < 300 ms
sympy     1-file update   < 300 ms      # the invariance gate — same as flask
sympy     warm query      < 100 ms      # requires daemon
flask     src/ methods with 0 production callers   < 20%   # currently 73.4%
express   source nodes per JS file      > 10        # currently 1.6
```

The sympy-equals-flask update gate is the one that matters. It converts "scales
acceptably" into "does not scale at all," which is the correct target.

---

## 6. Coverage and caveats

**Tested:** `scan`, `update`, `query`, `status`, `select`, `snippets` (help),
`frontends`, `traversal`, `cache`, `eval` (help). Repos: flask, express,
ripgrep, graphiti, langgraph, sympy.

**Not tested:** `platform`, `memory`, `federation`, `repair`, `compare`,
`profile`, `ingest`, `export`, `doctor`, MCP surface, the `eval` harness with a
real task file (no task fixtures were located), packet formats other than the
default, `--scope` / `--scope-mode`, doc-only and history modes.

**Not scanned:** z3, lean4, PufferLib, crewAI, mem0, redis, KGCompass,
SerpentAI, MoBA, and the remaining `resources/` entries. `neo4j` contains no
source files of the counted types.

**Artifacts created:** `.graphgraph/` directories in `resources/{flask, express,
ripgrep, graphiti, langgraph, sympy}`. No target-repo source was modified. Remove
with `graphgraph remove-graph-files` or by deleting those directories.

**Single largest confounder:** every measurement here used the `tree_sitter`
frontend, because `cpg` is unreachable from `scan` (§3.2). If `cpg` is wired in
and carries real type evidence, §3.1's resolution rates and §3.3's density
figures must both be re-measured before being trusted.
