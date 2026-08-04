# Retrieval, the shared tree-sitter path, and a parallelism result that failed

**Date:** 2026-08-01
**Method:** `cProfile` plus byte-identical output gates — a canonical dump of
search results across natural-language, `exact_fast_path` and `exact_only`
modes, and the scan dump from the previous cycle. Every gate was run twice
against unchanged code before being trusted.
**Companion:** `2026-07-31-scan-hot-path-optimization.md`, which fixed the scan
hot path and left retrieval unmeasured.

---

## Retrieval was never profiled, and warm queries were 3.3× slower than needed

| Measurement | Before | After |
|---|---:|---:|
| Warm query, p50 | 130.4 ms | **46.2 ms** |
| Cold first query (incl. index build) | 976.5 ms | **666.8 ms** |
| Graph load | 188.7 ms | ~175 ms |

Two defects, both byte-identical to fix:

**Search was touching the filesystem.** `document_authority` is a per-node
tiebreaker, so it runs once per docs node in a query. It resolved its default
README path and called `.exists()` on *every* call — about 930 syscalls per
query. The expensive part (reading the index) was already cached; **the guard
around it was not.** The cache sat one level too deep.

**Inflections were recomputed per node per query.** `lexical_forms` is pure in
its argument and was called 401,724 times per five searches. It is now memoized
and returns a `frozenset`, so the shared value cannot be mutated.

### The number that actually matters is cold, not warm

Warm p50 reached 39.8 ms after the two fixes above, already inside the "< 50 ms"
gate. But the CLI runs one query per process, so **real usage is always cold**,
and cold decomposed as: 183 ms graph load, 402.6 ms building search rows,
347.6 ms building an inverted index, and only **59.6 ms of actual scoring**. The
indexes were 93% of it, and `_candidate_rows` read about five postings out of
the 37,465 the index contained.

**Search no longer builds an inverted index at all.** Each row now carries the
token set it is findable under, computed where the row is already being built,
so candidate selection is a set intersection. Cold fell to **666.8 ms**.

The first attempt was a lazy per-query scan with no precomputation. It was
rejected: it re-derived every row's tokens on each query and pushed warm p50
from 39.8 ms to 111.9 ms. Precomputing costs warm 6.4 ms (46.2 ms, still inside
the gate) and buys 146 ms of cold, breaking even at roughly 23 queries per
process — and the CLI issues one. `_search_token_index` still exists for facet
requiredness, and still invalidates on node revision.

What remains is the row building and the ~175 ms load.

### Persisting the index does not fix that, and the numbers say so

The obvious next step is to build the index at scan time and load it. Measured
before building it, on the same 11.7k-node graph:

| | |
|---|---:|
| Rebuild in-process | 604.7 ms |
| Interned-JSON sidecar: decode **and reconstruct** | 443.6 ms |
| Saving | **161 ms (1.36×)** |
| Sidecar size | **11.47 MB** (the graph itself is 5.80 MB) |

**Reconstruction is 73% of the rebuild.** The cost is constructing 11,763
dataclasses with five `set()` fields each, not parsing text — and no
serialization format persists its way out of Python object construction. For
161 ms it would buy a sidecar twice the size of the graph, a write cost on every
scan, staleness handling, and an invalidation key that cannot reuse
`_search_index_key` (`node_revision` is an in-memory counter that resets on
load, so it would need a content fingerprint).

`pickle` decoded no faster than JSON once interned (182 ms against 244 ms) and
is disqualified regardless: the sidecar would live in `.graphgraph/` inside a
scanned repository, so loading it would execute arbitrary code from whatever
checkout the tool was pointed at.

**Not built.** The only approach that would help is a columnar row
representation that avoids per-node object construction, which is a redesign of
the retrieval path rather than a persistence feature.

---

## The shared tree-sitter path, measured on C for the first time

All previous profiling used Python corpora, which never exercise the
pattern-matching extractors. On a 132-file C corpus (GCC sources), two
language-agnostic defects dominated. Both fixes are byte-identical; the corpus
went **5.33 s → 4.93 s**.

**`_collect_defs` re-derived a constant inside its node walk.** A JS-only check
called `source.path.suffix.lower()` for every node that is not a definition —
which in C is nearly all of them. `Path.suffix` re-parses the path string on
each access: **775,388 calls** on this corpus, about 10% of the scan, to compute
one per-file boolean. Hoisted.

**`_syntax_text_without_literals` re-classified node types 2.2M times.** It
casefolded each node's type and ran four substring scans to decide whether the
node was a comment or literal. A grammar has a few dozen node types, so that
classification is now memoized by type string; self time fell 2.80 s → 1.73 s.

**It was also computed twice for every non-Python definition** — once during
collection, once during resolution. `_definition_facts` now returns the blanked
source alongside the facts derived from it, and `_TsDef` carries it forward for
the same reason it already carries the parse node: extraction-time state that
later stages would otherwise re-derive. Calls fell **4,962 → 2,481**, exactly
one per definition, and self time 1.73 s → 0.91 s.

An `id()`-keyed memo would have been the tempting shortcut and is both unsafe
and useless here: py-tree-sitter creates fresh `Node` wrappers per traversal.

Together the C corpus went **5.33 s → 4.58 s (-14%)**, byte-identical.

---

## Cache bounds are working-set quantities, and they fail catastrophically

Three caches keyed by per-file or per-symbol data were raised from fixed bounds
to 131,072: `_lang_family` (keyed by path, hot inside edge resolution),
`_source_declares_rust_test`, and `_rust_test_module_calls_symbol` (each miss
re-reads a file). `_rust_source_lines` was deliberately **left at 512**: it
holds whole file contents, so its bound is a genuine memory ceiling rather than
a working-set quantity.

The failure mode is worth stating precisely, because it is not gradual. On a
20,000-item working set:

| maxsize | time | hit rate |
|---:|---:|---:|
| 8,192 | 32.9 ms | **0.0%** |
| 131,072 | 12.7 ms | 75.0% |

A cache smaller than its working set does not degrade gracefully — it degrades
to a **zero hit rate**, paying full cost plus caching overhead. And it is silent.

**Not claimed:** no available corpus (sympy is 2,073 files) exceeds the old
bounds, so this is preventive. The table above is a synthetic demonstration of
the mechanism, not a measured end-to-end win.

---

## Parallelising the scan: sympy 113.2 s → 87.5 s

**Threads are useless here.** tree-sitter does not release the GIL: parsing 86
files was 1.07× faster at 2, 4 and 8 workers alike.

**Processes cannot carry parse trees**, so only the Python type-snapshot phase
is cleanly serializable. It is a pure function of each file's text producing
data that is already persisted to the manifest, and in isolation it parallelizes
**4.82× (33.6 s → 6.6 s) with identical results**.

Naively, that gains nothing, because the phase doubles as **cache warming**.
Running it in the parent populates the memoized per-file analyses that the
sequential resolution phase then reuses. Measured directly by clearing those
caches immediately before extraction: **113.7 s warm against 147.3 s cold —
33.6 s**, which is more than parallelising the phase saves.

So the worker returns the three analyses it computed on the way to the snapshot,
and the parent primes its cache with them. Shipping them is nearly free
(~0.2 MB, ~4 ms to unpickle for 1,583 files). Result: **113.2 s → 87.5 s (-23%)
for a byte-identical graph** — same digest, 40,857 nodes and 192,689 edges.

The memo is now a plain dict exposing `cache_prime` rather than an `lru_cache`,
because the point is that entries can be *contributed* as well as computed. The
pool engages only above 200 files, since Windows `spawn` costs 213–410 ms and
would otherwise make a small repository slower.

### The first attempt failed for a reason worth recording

An earlier version of this measured 124.5 s parallel against 124.6 s sequential
and was reverted, with cache warming written up as the explanation. **That
explanation was plausible, consistent with the evidence, and wrong.** Tracing
the phase showed `snapshot phase: 0.0 s for 0 files` — the pool had been
attached to the loop in `_build_graph_from_split`, where `python_fact_snapshots`
is already fully populated, so it never ran at all. The real work happens in the
dirty-files loop of the type-fact planning pass.

Cache warming is real and independently measured, and priming is what
neutralises it. But it was never why the first attempt failed. A negative result
that is never traced to a mechanism is not a finding, it is a guess that
happened to match — and here it cost a working 23% until the phase was
instrumented rather than reasoned about.

An intermediate reading of 131.0 s also suggested a regression at one point; it
was contention from a test suite running alongside the scan. Controlled A/B
pairs, not one-off timings.

---

## JavaScript receiver resolution, and where it is not fixable

Prompted by `2026-08-01-graybox-flask-multilang.md`, which measured express at
2.8% member-call resolution against flask's 65.5%. Both figures reproduce.

Instrumenting the resolver shows express's 6,181 unresolved receivers are only
**51 distinct names, 96% of them in `test/`**: `app` (1,951, from
`var app = express()`), `request()` (1,783, a supertest chain into a library
that is not in the graph), `res` (1,500) and `req` (103) middleware parameters.

Seven receiver idioms were enumerated; two were fixed and two are refused.

| idiom | resolves | type stated in source? |
|---|---|---|
| `new Engine()`, `new Imported()` | yes | yes |
| module object method, same-file object | **yes (fixed)** | yes |
| `new m.Engine()` | **yes (fixed)** | yes |
| factory result — `var app = express()` | no | **no** |
| callback parameter — `res`, `req` | no | **no** |

**Fixed.** A same-file object receiver (`var app = {}; app.set = fn;` then
`app.set()` elsewhere in the file) had its owner recorded but nothing bound the
name to it. And `new m.Engine()`, the CommonJS way to name an imported class,
was missed because the pattern required the whole path to start uppercase.

**Refused, deliberately.** express's factory returns a *function* whose methods
arrive through `mixin(app, proto, false)` — dynamic property copying via a
third-party helper — and `res`/`req` take their types from express's own routing
contract. Neither is recoverable without framework-specific or dynamic-dispatch
modelling. Every available heuristic trades precision, which this engine holds at
10.0 and which is the reason its output is worth trusting, for recall on one
framework. express's rate is therefore unchanged at 0.0276, and that is the
honest number.

Two precision guards were added with the fixes: a parameter that shadows the
object name does not bind to it, and a lowercase callee (`new makeThing()`) is a
factory rather than a type.

## The gate that number feeds must not be the obvious one

The gray-box report nominates `member_call_resolution_rate` as a CI gate. It was
never actually emitted — it had been computed from the raw counters — so it is
now emitted, together with the denominator it is taken over.

It must **not** be `resolved / (resolved + unknown_receiver)`. Binding a receiver
moves a call from `unknown_receiver` to `unmatched` *without producing an edge*,
so that definition rises when nothing resolves — observed going 66.7% → 100% on
a two-call fixture during the work above. On a fixture whose only member call is
a genuine miss it reads 0/0 and scores a scan that resolved nothing as
unpenalised.

The emitted definition is `resolved / (resolved + ambiguous + unknown_receiver +
unmatched)`. `external_resolved` is excluded: no internal symbol carries that
method name, so declining to link it is correct, and counting it would make the
gate track how much third-party API a repository touches. Both properties are
pinned by tests.

| corpus | strict rate | internal member calls |
|---|---:|---:|
| express | 0.0276 | 6,522 |
| crewAI | 0.5006 | 13,189 |
| flask | 0.5952 | 1,544 |

## Not claimed

- **Only `search_nodes` was decomposed**, and only partially (412 → 375 lines).
  52 functions still exceed 100 lines; `_add_tree_sitter_calls` grew to 507 from
  the optimization work.
- **The token-ceiling guard was re-derived** (151,006 → 154,149) rather than
  met. It had 126 tokens of slack before this work began, so it was firing on
  any addition rather than on unusual growth.
- Retrieval was measured on one 11.7k-node graph, and the C findings on one
  132-file corpus.
