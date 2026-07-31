# Caching and compression prototypes: three candidates, two falsified

**Date:** 2026-07-31
**Method:** measurement before implementation. Each candidate was reduced to a
number that could kill it, and the number was taken before any code was written.
**Companion:** `2026-07-31-critical-graybox-scope-resolution.md` (which raised
the latency and scale questions this round answers).

---

## Summary

Three optimizations were ranked by expected value, then tested in order. One
survived, and it turned out to be already implemented. The other two were
falsified — one by measurement, one by reading the code that already did it.

| Candidate | Premise | Outcome |
|---|---|---|
| Resident service for exact lookups | 252 ms -> ~1 ms | **Real, and already present** on the MCP path |
| Prefix-stable packet ordering for KV cache reuse | packets share ~2% prefix | **Narrow**: no benefit for append-only conversations |
| Anchor-set cache keys to collapse paraphrases | queries keyed on text | **Already implemented**; residual is anchor instability |

The useful output of this round is therefore a corrected latency model rather
than new code. That model is recorded in `../architecture.md`.

---

## 1. Resident service

**Premise.** An exact one-hop lookup costs ~252 ms end to end while the work
itself is microseconds, so a process holding the graph in memory should collapse
it.

**Measured.** On Flask (460 nodes / 1,311 edges):

| Stage | Cost |
|---|---:|
| Bare Python interpreter | ~126 ms |
| GraphGraph import and dispatch | ~3 ms |
| First `load_any` | ~6 ms |
| Later `load_any` (process cache) | ~0.2 ms |
| `query_relations`, resident graph | ~0.017 ms |
| Reverse-index build, whole graph | ~0.19 ms |

**Result.** The premise is right about the size of the gap and wrong about its
cause. Roughly **126 ms of a 252 ms invocation is spent before any GraphGraph
code runs**, and GraphGraph's own contribution to a cold call is single-digit
milliseconds. A daemon fronted by a CLI client recovers none of it: the client
is another Python process paying the same interpreter cost.

The only callers that can benefit are ones already long-lived — and the MCP
server is exactly that, with `load_any` memoized per process against a store
fingerprint. Resident retrieval measures **~0.26 ms per query** versus ~252 ms
through a fresh CLI process, a factor of about 1000.

**Consequence for evaluation.** Timing repeated CLI invocations measures process
spawn. The previous report's "60-300x above floor, essentially all process
startup" identified the right component but drew the wrong conclusion from it:
the fix is to use the resident path that exists, not to build one.

---

## 2. Prefix-stable packet ordering

**Premise.** Prompt caching reuses the KV state of a shared prompt prefix, and
cache-aware evidence ordering is an active technique for RAG systems whose chunk
order varies per request. GraphGraph controls its own serialization order and
already has a `--stable-skeleton` notion, so ordering packets by volatility —
invariant header, then subsystem, then query-specific evidence — should raise
prefix reuse.

**Measured.** Four unrelated queries against Flask, `subsystem_summary`:

| Pair | Shared prefix | % of smaller packet |
|---|---:|---:|
| q1/q2, q1/q3, q1/q4 | 67 chars | 2.0% |
| q2/q3, q3/q4 | 80 chars | 1.9% |
| q2/q4 | 94 chars | 2.2% |

Packets share only the format legend (`#gg`, relation table) and diverge
immediately after. So the headroom the premise assumes is genuinely there.

**Why it was still dropped.** Prefix caching applies to the whole prompt prefix,
and an agent conversation is append-only: turn *N+1*'s prompt is turn *N*'s
prompt plus new content, so everything through the previous turn is already
cached regardless of how any individual packet is ordered internally. Reordering
content *within* a packet moves nothing across the cache boundary.

The benefit is real only where the same packet is re-sent at the same position
in a *different* prompt — a fresh session, a compacted context, or a stateless
prompt template. That is a narrower case than the premise assumed, and it was
not worth the serialization churn without a workload that exhibits it.

---

## 3. Anchor-set cache keys

**Premise.** Paraphrased queries should hit the same packet cache entry, and
would not if the cache were keyed on query text.

**Result.** Already implemented. `compute_cache_key` keys on
`(sorted anchors, query_class, hops, packet_format)` — no query text.

**But the observed behaviour still shows two entries** for two paraphrases of
the same question, because *anchor discovery* is lexically sensitive: the two
phrasings resolved to different anchor sets, and the second additionally
degraded to `state=incomplete, evidence:-`.

So the miss is upstream of the cache and no cache change can fix it. It belongs
to the semantic-retrieval axis already tracked by the optional embedding
backend, not to caching.

---

## Compression: why it was not pursued

Compressed adjacency structures (k2-trees, ~3.3-5.3 bits per link, 2-15 us per
neighbour) are strong results, but they optimise the wrong term here. On Flask
the graph is 166 KB and load-plus-query is ~43 ms of a 252 ms call, against
~126 ms of interpreter start. Compression would target a minority slice of a
cost dominated by process creation.

A separate point is worth stating because it is easy to conflate: **byte
compression is not token compression.** The packet is consumed by a model as
tokens, and no byte-level encoding reduces token count. The lever for token cost
is selectivity — the previous report measured 52 nodes returned where roughly 8
answer the question.

Succinct structures become relevant when graphs are large enough that load or
resident memory binds — plausibly under federation, where many repositories are
held at once. The variant that would pay earliest is not the compression ratio
but a **memory-mappable layout queryable in place**, which removes
deserialisation rather than shrinking bytes. Even that is bounded by the ~6 ms
first load measured here.

---

## What this round changes

- `../architecture.md` gains an execution-model section recording the two
  transports and their measured cost.
- Latency claims should specify transport. A number without one is unfalsifiable
  and, for the CLI, is mostly a measurement of Python.
- Two of three candidates were removed from the roadmap on evidence rather than
  carried as plausible future work.
