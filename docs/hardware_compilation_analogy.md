# Systems Analogy: From Assembly/Hardware to LLM Attention Mechanics

> **Status: conceptual framing, not an implementation claim.** Per
> [`rigorous-framing.md`](rigorous-framing.md)'s rule ("write hypotheses
> separately and label them as hypotheses"), this document is a teaching
> analogy for *why* compact packet formats help, plus two forward-looking
> ideas (§3, §4) that are **not implemented** in this codebase today. Section
> markers below call out exactly what's real vs. aspirational — don't cite
> §3 or §4 as describing current GraphGraph behavior.

This document maps traditional low-level systems compilation (Assembly
$\rightarrow$ Machine Code $\rightarrow$ Register/ALU execution) onto
LLM-native context retrieval, to explain the reasoning behind compact packet
formats. Everything the model actually receives is still plain text passed
through the normal token stream — nothing here bypasses that.

---

## ⚡ 1. The Assembly vs. Binary Representation — **implemented**

Verbose JSON/Markdown context requires the model to do lexical parsing and
pointer-chasing across the attention window for every request. GraphGraph's
`gg_max`/`semantic_arrow`/`lowlevel` formats instead assign short integer
indices to nodes and encode edges as compact adjacency tuples — a real,
tested, benchmarked reduction in tokens-per-fact (see
`docs/empirical-findings.md`). This part of the analogy describes actual
code (`src/graphgraph/packets/renderers.py`).

---

## 🧠 2. Packet Caching — **implemented, but not literally the model's KV cache**

`TopologicalKVCache` (`src/graphgraph/runtime/cache.py`) is an
application-side LRU cache of *rendered packet text*, keyed by graph state
and query, with dependency-path hashing so a rescan only evicts entries
whose actual source files changed. That's real and reduces redundant
re-rendering work. What it is **not**: direct manipulation of a
transformer's internal KV cache or VRAM. The practical connection is
indirect — a stable, repeated text prefix makes it *possible* for an LLM
provider's own prompt-caching feature to help, but GraphGraph does not pin
anything into a model's attention mechanism itself.

---

## 🎛️ 3. Direct Attention Masking — **hypothesis, not implemented**

The idea: instead of serializing a geodesic-distance ("spatial bias") matrix
as text for the model to read, inject it directly into the attention
computation ($\text{Softmax}(QK^T/\sqrt{d_k} + S)V$) so the graph shape
steers attention without ever being read as tokens.

What actually exists today is `render_tensor_array` /
`tensor_spatial_bias` (`src/graphgraph/packets/renderers.py`): a real
all-pairs BFS shortest-path matrix, computed correctly — but **serialized as
plain-text numbers in a packet**, tokenized and read by the model through
the ordinary attention mechanism like every other format. There is no code
path in this repo that touches attention weights, KV-cache internals, or GPU
execution directly; doing so would also require inference-server-level
access this project doesn't have. Treat this section as a research
direction, not a description of what `render_tensor_array` does.

---

## ⚙️ 4. Demand Paging — **partially real, partially hypothesis**

**Real:** Personalized PageRank (`Graph.personalized_pagerank`) genuinely
prioritizes which nodes make it into a budget-constrained packet, and
session/git-recency weighting genuinely biases that scoring toward recently
touched code (see `retrieval/git_utils.py`,
`test_personalization_git_session_weight_formula`).

**Hypothesis:** framing this as OS-style "LRU page replacement" with
formal "context page faults" is a naming choice, not a literal paging
system — there's no virtual memory table, no page-fault trap, and no
`keystroke-decayed half-life weighting` formula ($W(t) = W_0 \cdot
2^{-\Delta t/\lambda}$) currently implemented in the codebase. If that
decay formula gets built, update this section to link the real function;
until then, don't cite it as existing behavior.
