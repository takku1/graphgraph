# The Last 30%: What GraphGraph Would Need to Run at 100% Agent Efficiency

**Date:** 2026-07-24 (cycle 3)
**Frame:** Not "does it work" — *"can an AI agent drive this at 100% efficiency?"* This report is
half measurement, half theory: the measured floor is the launch pad, and the rest is a deliberate
fantasy of what the ideal graph-native agent loop would feel like, and what is still missing to get
there. Gray-box throughout; source and git history never read.

---

## Cycle 3 differential (what moved since last time)

Version still `0.1.0`; frozen fixtures intact. Both fixes from cycle 2 hold:
`--max-nodes` honors its value (budget=200 when asked for 200); the false staleness warning stays
gone. **New this cycle:** I stopped testing the packet and started testing the *loop* — the JSON
envelope's `actionable`, `workflow`, `routing`, and `answerability` blocks, i.e. the surface an
agent actually steers by. That is where the remaining 30% lives, and it is the subject of this
report.

---

## Defining "100% efficiency" for an agent

An agent using a graph tool is efficient to the exact degree that **every token it receives is
load-bearing and every call advances the task.** Perfect efficiency has four properties:

1. **Zero verification round-trips.** The agent acts on the output without re-checking it against
   grep/read. This requires a *trustworthy* signal, not just a correct answer.
2. **Zero wasted tokens.** Every node in a packet is used. No paying for 75 wrong nodes to reach
   the one that mattered.
3. **Zero re-orientation.** The agent threads one call into the next by handle, never re-deriving
   context it already had.
4. **Zero fallback.** The whole loop — orient → locate → blast-radius → act → verify — completes
   inside the graph; the agent never drops to raw file reading.

Measured against those four, GraphGraph today is roughly: **fallback ~70% eliminated, chaining
~80% there, token-waste ~50%, verification round-trips ~10%.** The binding constraint is #1 —
trust — because a signal the agent can't trust forces round-trips that poison the other three.
Below, each property as a concept, pinned to a number.

---

## Property 1 — Trust: the efficiency ceiling nobody sees

**The measurement.** Across 18 ground-truth queries spanning three languages, *every* top-level
trust signal is constant:

| signal | value across 18 queries | discriminates recall? |
|---|---|---|
| `answerability.abstained` | `True` × 18 | no |
| `answerability.status` / `actionable.status` | `incomplete` × 18 | no |
| `routing.confidence` | `0.147` × 17 (one 0.718) | no |
| control-receipt `state` | `incomplete` × 18 | no |
| `eval --calibration` resolution | **0.022** (vs uncertainty 0.222) | ~10% of needed |

The confidence is not merely flat — it's *inverted*: mean 0.307 on failures vs 0.267 on successes;
the two most confident queries in the set both had recall 0.

**Why this is the ceiling.** An agent that cannot distinguish a good packet from a bad one must
treat *all* packets as suspect, which means it re-verifies every one against the filesystem. That
single fact converts a graph tool from an *oracle* into a *hint generator*. The difference in
agent efficiency between those two modes is enormous: an oracle is called once and trusted; a hint
generator is called and then checked, doubling the work on every step.

**The fantasy.** Imagine one scalar — call it `trust` ∈ [0,1] — that is *calibrated*: when it says
0.9, the answer is right 90% of the time. The agent adopts a single policy:

```
trust ≥ τ  → act on the packet, no verification
trust < τ  → widen once; if still low, fall back to grep and SAY SO
```

That policy is the whole game. It turns "verify everything" (100% round-trip tax) into "verify the
tail" (maybe 15%). The infrastructure to compute it already exists and already varies internally —
anchor-score *margin* (top seed vs second), `matched_anchor_paths / expected_scope`, BFS frontier
saturation, `sources.lexical_strength` (I measured it swinging 12.3 on a strong query). None of
these are exposed as the confidence. The tool even ships the *grader* for this — `eval
--calibration` — so the loop to calibrate a candidate signal against ground truth is already
closeable inside the repo. **This is the highest-leverage missing piece and it is not a research
problem; it is a wiring problem.**

**Distance to floor:** resolution 0.022 → 0.10+ needed; ece 0.213 → <0.10. ~5–10× off, one signal.

---

## Property 2 — Token economy: every node must be load-bearing

**The measurement.** Packet efficiency swings wildly and the agent can't tell which regime it's in:

| query | packet | where the answer sat | *useful fraction* |
|---|---|---|---|
| requests "cookies extracted" | ~48 nodes | rank 1 (MRR 1.0) | ~high |
| ripgrep "gitignore parsed" | 107 nodes / 3308 tok | **rank ~76** (MRR 0.013) | **~1/107** |
| ripgrep "regex matcher built" | 48 nodes | rank ~32 (MRR 0.031) | ~1/32 |

When the answer is at rank 76 of a 3308-token packet, the agent paid ~3300 tokens to use ~40.
That is a **~98% token-waste event**, and — because of Property 1 — the agent has no way to know it
happened, so it can't even compensate by reading more carefully.

Confirmed this cycle: the now-working `--max-nodes` cannot fix this. Widening ripgrep to 800 nodes
recovered 0 of 4 misses — the useful nodes aren't reachable from the anchors at any budget. **Token
waste here is a ranking failure, not a budget failure.**

**The fantasy — the agent declares the budget, the graph packs it optimally.** Today the tool
guesses an adaptive budget (48). At 100% efficiency the agent, which *knows* its own context
economics, would instead say: *"I have 1500 tokens for this. Give me the 1500 highest-marginal-value
tokens, and tell me the marginal value of the last node you included."* That is a knapsack over
`(node, relevance, token_cost)`, and it would let the agent trade breadth for depth deliberately.
Coupled with a per-node relevance score in the packet, the agent could *stop reading* once marginal
value crossed zero — the packet would become self-truncating. GraphGraph already emits
`metrics.packet.proxy_tokens`; it just doesn't yet emit per-node value or accept a token budget
(only a node count). And `proxy_tokens` is currently non-comparable across formats (`lowlevel`
reports fewer tokens than `gg` despite 2.4× the characters), so even the cost side of the knapsack
is unreliable today.

**Distance to floor:** ranking MRR 0.007 (rust) → 0.5; the correct node in the top 5, so useful
fraction ≥ ~1/5 worst case instead of 1/107.

---

## Property 3 — Chaining: thread calls by handle, never re-orient

**The good news — this substrate already works.** This is the property GraphGraph is *closest* to
nailing, and it deserves to be said plainly. Node IDs are stable, structured handles that carry the
qualified name inside them:

```
src_requests_sessions_py__SessionRedirectMixin__should_strip_auth
```

And they chain across commands with zero re-search. Measured this cycle:

```
query "…strip authorization headers" --json
  → actionable.change_points[1].id = src_requests_sessions_py__…__should_strip_auth
snippets --starts <that id> --max-lines 12
  → ## should_strip_auth  src/requests/sessions.py:154
     154 | def should_strip_auth(self, old_url, new_url) -> bool:
     155 |   """Decide whether Authorization header should be removed when redirecting"""
```

The agent went query → exact source, by ID, no path guessing, no second search. **That is the raw
material of a zero-waste loop**, and it already exists.

**The two gaps that stop it short of 100%.**

*(a) The qualified name is in the ID but not queryable.* `label contains
SessionRedirectMixin::should_strip_auth` returns 0; the four distinct `send` methods in requests
all carry the bare label `send`. So an agent can chain *forward* from an ID it already holds, but it
cannot *start* from "who calls `Session.send`" — the natural question. The disambiguation data is
present in the ID string; it just isn't indexed as a first-class query key.

*(b) Re-orientation is forced by the process boundary, not the API.* Each command reloads the graph
from disk: ~302 ms of the ~400 ms query time is pure import + load, i.e. **~77% of every call is the
agent paying to re-establish context the previous call already had.** The API supports chaining;
the runtime throws the context away between every link.

**The fantasy — a resident session that holds the graph and the agent's working set.** Imagine
`graphgraph serve` where the agent opens a session, and IDs it has seen stay warm: the graph never
reloads, and the agent can say "expand *these five* IDs I'm holding" and get a 5–15 ms answer
(measured floor) instead of 400 ms. Because `update` is *already* O(Δ) and size-invariant (measured
0.96× across a 45× graph), a resident session makes the *entire* edit loop O(Δ): edit a file →
splice → the agent's held IDs are still valid → re-query in milliseconds. **The expensive half of
that vision is already built. Only the process boundary is missing.**

---

## Property 4 — Loop closure: the packet should be the whole work order

**The measurement — the loop is designed but stubbed.** The `actionable` block is genuinely
sophisticated and points straight at 100% efficiency. For the redirect query it returned:

- `change_points`: ranked node list with `path:line` — *where to edit* ✅ (and it surfaced
  `should_strip_auth` correctly, arguably better than the raw packet ranking)
- `implementation.authorized: false`, `"a documented absence is evidence, not a work order"` — a
  real governance model that stops an agent from acting on thin evidence ✅
- `tests`: `{direct:[], transitive:[], commands:[]}` — **empty.** The slot for *"here are the exact
  tests to run after this change"* exists and is unpopulated.

**Why the empty slot matters.** The single most valuable thing a graph can hand an agent making a
change is: *"you touched `should_strip_auth`; run `pytest tests/test_requests.py -k redirect`."*
That closes the loop — the agent edits, the graph names the verification, the agent runs it, done,
no thinking in between. The `tests` edge type exists in the ontology (`tests: family=validation
strength=0.85`), the `affected_tests` query class exists, and the `commands_by_role` schema is
already there in the JSON. The wiring from "affected test node" → "runnable command string" is the
missing link.

**The fantasy — the transactional change packet.** One call returns everything an agent needs to
execute a change with zero composition on its side:

```
{ change_points: [where to edit, ranked],
  blast_radius:  [what else this reaches],
  tests:         [exact commands to run, ordered],
  trust:         0.91,          # Property 1
  budget_used:   1200/1500 tok, # Property 2
  session_ids:   [warm handles] # Property 3
}
```

Every field above is something GraphGraph *already computes a piece of*. Assembling them into one
authoritative work order — and making `trust` real — is the difference between an agent that
*consults* the graph and an agent that is *driven* by it.

---

## The one number that captures agent efficiency

If a single CI-able scalar had to stand for "how efficiently can an agent use this," it is
**useful-token fraction**: of the tokens delivered for a query, what fraction lands within the
top-k the agent will actually read. It collapses ranking (Property 2) and is trivially derived from
the eval harness that already exists:

```
useful_token_fraction ≈ 1 / (rank_of_first_relevant)   # from MRR the tool already reports
```

Today: requests ~0.6, express ~0.47, **ripgrep 0.007**. Gate it at ≥ 0.3 per language. It is the
same underlying failure as every other open item — anchoring/ranking — which is why fixing that one
subsystem lifts three of the four efficiency properties at once.

---

## What is already at the floor (protect at all costs)

The reason the remaining work is "the last 30%" and not "the first 70%" is that the hard,
irreversible-if-lost engineering is done:

1. **`update` is O(Δ) and size-invariant** — 0.96× across a 45× graph. This is what makes the
   resident-session fantasy (Property 3) *cheap* rather than a rewrite.
2. **ID-based chaining works** — query → snippets by handle, measured this cycle.
3. **The `actionable` governance model** — "a documented absence is evidence, not a work order" is
   exactly the discipline you want gating an autonomous agent.
4. **Radical self-honesty** — the `select` caveat volunteers its own resolution denominator
   (`2.2% (143/6389)`), and `eval --calibration` correctly grades its own confidence as broken. A
   tool that ships the instrument that proves its own weakness is one you can *improve* against.
5. The `gg` packet (3.9 chars/token), idempotence, honest `frontends` declaration — all intact.

---

## The shape of the remaining 30%, in one paragraph

Everything left is the same organism seen from four sides. **Anchoring/ranking** is picking the
wrong seeds (ripgrep MRR 0.007; JS extraction 2.2% starves it of edges to rank), which wastes tokens
(Property 2) and, because no signal exposes that it happened, forces verification (Property 1); the
process boundary throws away context between calls (Property 3); and the work-order slots that would
let the agent execute without thinking are stubbed (Property 4). Fix anchoring + JS extraction, make
one trust signal real, keep the graph resident, and populate `tests.commands` — and the four
properties close together, because they were never really separate. The floor is already built. The
last 30% is wiring the loop the tool has *already designed* into something an agent can trust its
whole weight to.

---

## Coverage / artifacts
Cycle-3 additions exercised: `actionable`, `workflow`, `routing`, `answerability`, `snippets
--starts` ID-chaining. Still untested: `plan/render/final`, memory scoping, federation, MCP surface,
`graph_at_time`, `platform`. Single machine, Windows 11, n=3 timings, warm except where noted.
Artifacts unchanged from prior cycles: `resources/flask/.graphgraph/semantic.json` (22.8 MB, mine —
safe to delete); scratchpad fixtures (~200 MB); `fastembed_cache` (64 MB, global). No source
modified.
