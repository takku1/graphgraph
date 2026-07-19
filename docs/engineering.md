# Context Engineering for GraphGraph — grounded notes

> This replaces the earlier `egnineering.md`, which was a raw chat transcript.
> That transcript proposed a "JIT Context Injector / Active Working Set" and
> explained it via a KV-cache analogy. The core intuition is right and is,
> in fact, roughly what GraphGraph already is. But several of the mechanism
> claims are half-true or wrong, and the framing misses where the real
> research and the real gaps are. This note keeps the good parts, corrects
> the rest against the 2024–2026 literature, and maps each idea to what
> GraphGraph has today vs. what it's missing.

---

## 1. What the transcript actually proposed

Stripped of the vocabulary, it's three claims:

1. **Don't dump the whole repo into context.** Maintain a graph as the source
   of truth, and load only the "hot" nodes relevant to the current task into a
   working buffer (`MEMORY_WINDOW.md`) via a controller script (`//LOAD`).
2. **This is manual KV-cache management.** Swapping chunks in/out of the buffer
   is "pruning stale KV entries and replacing them with new projections."
3. **It beats naive context** because attention is quadratic and models are
   "lost in the middle," so keeping the window small and reloading hot chunks
   at the edges maximizes recall.

Claim (1) is correct and is the whole thesis of the field now called **context
engineering**. Claims (2) and (3) contain a real phenomenon wrapped in a wrong
mechanism. Below, each is checked against the literature.

---

## 2. Grounding the claims

### 2a. The KV-cache "RAM" analogy — right picture, wrong lever

**True:** During *prefill*, the model computes Key/Value projections for every
input token and stores them in GPU HBM; that structure is what lets later tokens
attend without recomputing. "KV cache is the model's RAM" is a fair analogy, and
its cost/size is the real constraint (MemGPT frames the whole context window as
exactly this — a memory-hierarchy problem).

**Wrong:** *Editing a `.md` file does not prune or evict KV-cache entries.* The
KV cache is per-inference-request state, not a file you own. When you rewrite the
buffer, the next request simply re-prefills a *different token sequence* from
scratch (or reuses a cached **prefix**, see below). You cannot selectively evict
"the middle" by editing text — eviction is an inference-server policy (H2O,
StreamingLLM's *attention sinks*, InfiniGen, FreeKV), not something a prompt file
controls.

**The lever you actually have** is **prefix caching**: servers like
vLLM/SGLang cache the KV of a shared prompt *prefix* (RadixAttention) so a stable
leading segment is prefilled once and reused across calls. This is real, it is
large (often the dominant latency/cost win), and it has a hard design
implication: **put the stable stuff first and never let it churn.** Any byte that
changes near the top invalidates the whole downstream prefix cache.

→ *GraphGraph already respects this*: `graphgraph final --stable-skeleton`
exists precisely to emit a byte-stable leading skeleton. The transcript
reinvented a weaker version of this and mislabeled it.

### 2b. "Lost in the middle" — real, but more nuanced than "edges good"

**True:** Liu et al. showed a U-shaped position curve — accuracy is best
when the needed fact is near the start or end, worst in the middle. Follow-ups
(including multi-hop and multimodal settings) confirm that position can
materially change retrieval use, while also showing that the exact curve varies
by model, task, and modality.

**Nuance the transcript missed:** primacy vs. recency is not fixed; some later
settings even show a strong primacy effect instead of the original U-shape. So
"always reload hot chunks at the edges" is a heuristic, not a law. Ordering by
relevance and keeping the set small is the safer design target.

### 2c. Quadratic attention — true, but not the binding constraint anymore

Attention is O(n²), yes. But FlashAttention, prefix caching, and paged KV make
the *marginal* cost of a stable-prefix + small-delta prompt far below "re-read
everything." In practice the binding constraint is **quality degradation with
length (context rot)** and **token budget/cost**, not raw FLOPs. Optimizing for
"fewer tokens because attention is quadratic" is directionally fine but aims at
the wrong bottleneck; optimize for *precision of the loaded set*.

### 2d. "Force the model to forget" via a memory flush — legitimate, and named

This is the best idea in the transcript and it has a name: **virtual context
management** (MemGPT / Letta, 2023→). Treat the window as paged memory with an
explicit controller that moves facts between an in-context tier and external
tiers, and decides what to evict per task. The transcript's "clear
`MEMORY_WINDOW.md` on task switch" is a crude form of MemGPT's tiered eviction.
The principle — *statelessness is the default; state is something you engineer* —
is exactly right.

---

## 3. The better approach (what the field actually does)

The transcript describes a single hand-rolled loader. A modern implementation is a
**layered context pipeline**, and GraphGraph is positioned to be the retrieval
core of one:

| Layer | Job | Representative work |
|---|---|---|
| **Structure** | Repo as a typed graph (imports, calls, defs, tests) — not flat chunks | CodexGraph, GraphCodeAgent, RANGER, LARGER (2024–2026) |
| **Retrieval** | Query → anchors → bounded relevant subgraph (structural + semantic hybrid) | Graph-RAG for code; dense+structural beats dense-only for multi-hop |
| **Compression** | Serialize the subgraph in few tokens; drop cold nodes | agent context compression (ACON, SkillRAE) |
| **Ordering** | Stable prefix first (prefix-cache), relevant nodes at the edges | prefix caching + position-bias calibration |
| **Memory** | Persist/evict facts across turns; page in/out | MemGPT / Letta virtual context |
| **Serving** | Prefix/KV reuse, paged KV | RadixAttention, vLLM, StreamingLLM sinks |

Recent repository-level work supports structural and structural-semantic graphs
as useful retrieval substrates, especially for multi-hop code relationships.
The stronger operational choices—local-first storage, MCP transport, embedded
databases, and zero code egress—are GraphGraph design decisions; the cited
papers do not by themselves prove that this exact deployment bundle dominates
every alternative.

---

## 4. What GraphGraph already has (the transcript mostly reinvented it)

- **Graph as source of truth** — `scanner/`, `graph/core.py` (typed nodes/edges).
- **The `//LOAD` controller** — this is `query_context` / `final_packet` /
  `plan_context`. Natural-language query → auto-discovered anchors → bounded
  packet. No hand-rolled Python loader needed.
- **Token-efficient serialization** — `packets/renderers.py`, the whole reason
  the project exists (40–60% fewer tokens than verbose graph dumps).
- **Query-class-aware retrieval depth** — `planning/` routes `blast_radius`,
  `subsystem_summary`, `direct_lookup`, etc. to different expansion depths. This
  is the "pull the right dependencies" idea, already calibrated.
- **Token budgeting** — `retrieval/budgeting.py`, `planning/token_cost.py`,
  `planning/budgets.py`. Answers the transcript's closing question ("does your
  loader account for token length?") — yes, there's an explicit budget/knapsack
  layer (`retrieval/tree_knapsack.py`).
- **Prefix-cache-friendly output** — `final --stable-skeleton` (the correct,
  server-aware version of "manual KV management").
- **Hot/cold + temporal awareness** — `platform/temporal.py`,
  `platform/change.py`, `graph_at_time`, `graph_change`, `update_graph_files`.
  The "dirty state" concept the transcript wanted already exists.
- **Semantic + structural hybrid** — `platform/semantic.py`,
  `retrieval/search.py`, `retrieval/relevance.py`.
- **Repair / validation / evidence** — `platform/repair.py`, `validate.py`,
  `platform/evidence_store.py` (guards against hallucinated packets).

**Bottom line:** the transcript's "novel" architecture is, to a first
approximation, a re-derivation of GraphGraph minus the parts that make it work
(server-aware prefix stability, budgeting, query-class routing).

## 5. What GraphGraph does *not* have yet (the real roadmap)

These are the gaps the transcript didn't reach — and where "improving the AI"
actually lives:

1. **True cross-turn agent memory tier (MemGPT-style).** Temporal/change data
   exists, but nothing *pages facts in and out of context across an agent
   session with an eviction policy*. `platform/memory.py` is the natural home;
   today it's not a first-class MemGPT-style controller.
2. **Provider prefix-cache exploitation beyond the skeleton.** The stable
   skeleton is byte-stable, but there's no measurement/telemetry proving cache
   hits, and packet ordering isn't yet optimized end-to-end for
   RadixAttention-style reuse (stable-prefix + small-delta per turn).
3. **Data-calibrated relevance.** Ranking weights are still heuristics, not
   learned from an eval set (this matches the existing "ranking-model-design"
   note — smooth signals are in, but the weights aren't calibrated). Position
   ordering ("lost in the middle") is not yet informed by any calibration.
4. **Cross-model downstream task-quality evaluation.** GraphGraph now has
   `graphgraph platform acceptance`: sealed black-box cases for structural
   correctness, completeness, token ceilings, transport parity, incremental
   equivalence, secret boundaries, and executable test selection. The remaining
   gap is to connect those packet-level guarantees to model answer/edit quality
   on a benchmark such as CORE-Bench or a repository-editing suite.
5. **Context-rot-aware sizing.** Budgeting caps tokens, but nothing yet *shrinks
   the set because more context measurably hurts* — the packet is sized to a
   budget, not to a quality-vs-length curve.

---

## 6. One-paragraph answer to "what's the better approach"

Stop thinking of it as "a loader that dumps hot chunks and manually manages the
KV cache" — you can't manage the KV cache from a file, and raw token count isn't
the bottleneck. Think of it as a **retrieval-and-ordering problem over a typed
graph, tuned for two things the hardware/model actually reward: a byte-stable
prefix (so the server's prefix cache hits) and a small, high-precision,
relevance-ordered delta (so you dodge context rot and position bias).**
GraphGraph already implements a substantial part of this architecture. The
differentiated work left is (a) a MemGPT-style memory tier, and (b) extending
the new acceptance foundation into a cross-model evaluation loop that proves
token savings do not cost answer or edit quality.

---

## Sources

- [Lost in the Middle: How Language Models Use Long Contexts (Liu et al.)](https://arxiv.org/abs/2307.03172), the multi-hop follow-up [Lost in the Middle, and In-Between](https://arxiv.org/abs/2412.10079), and later work on [position-bias correction](https://arxiv.org/abs/2606.27793) and [primacy bias in multimodal RAG](https://arxiv.org/abs/2606.16494)
- [MemGPT: Towards LLMs as Operating Systems (Packer et al., 2023)](https://arxiv.org/abs/2310.08560) — virtual context management / memory tiers
- [The Missing Memory Hierarchy: Demand Paging for LLM Context Windows](https://arxiv.org/pdf/2603.09023)
- [Survey on System-Aware KV Cache Optimization](https://arxiv.org/pdf/2607.08057); [FreeKV](https://arxiv.org/pdf/2505.13109) — KV reuse, eviction, prefix caching (RadixAttention)
- [LLM Agent Memory: A Survey](https://www.preprints.org/manuscript/202603.0359/v1)
- Graph-RAG for code: [CodexGraph](https://arxiv.org/pdf/2408.03910), [GraphCodeAgent](https://arxiv.org/abs/2504.10046), [RANGER](https://openreview.net/forum?id=EPTVoeaz7Y), [LARGER](https://arxiv.org/pdf/2605.16352)
- [Retrieval-Augmented Code Generation: A Survey (repo-level)](https://arxiv.org/html/2510.04905v1); [CORE-Bench](https://arxiv.org/pdf/2606.11864)
