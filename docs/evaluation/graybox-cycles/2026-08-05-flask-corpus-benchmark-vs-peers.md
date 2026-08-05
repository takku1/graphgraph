# Graybox Evaluation: GraphGraph on Flask (vs. peer tools)

**Date:** 2026-08-05
**Target:** GraphGraph MCP tools (`mcp__graphgraph__*`)
**Fixture:** `flask` (pallets/flask), local checkout at `C:\Users\dcarn\aiprojects\resources\flask`, commit `954f568`, ~9,500 LOC across 24 `src/flask` files, plus `tests/` (961 files) and `examples/`.
**Method:** Gray-box (skill: `graybox`). GraphGraph's own source and its version-control history were not read. The Flask *target* source was read freely as the oracle. Prior reports in this `graybox-cycles/` directory were deliberately not read before forming conclusions, per instruction, to avoid anchoring — this report may duplicate or contradict earlier cycles; that overlap is itself informative and should be diffed by whoever reconciles the series.
**Also evaluated head-to-head:** `code-review-graph` MCP (a competing local context-graph tool, built on the same Flask checkout, same commit) — included because it was available in-environment and let several claims be checked against an independent implementation rather than against grep alone. **Additionally installed mid-session** (with explicit permission) as a third, independent oracle: `pyright` 1.1.411 (via npm; the harness's built-in `LSP` tool did not auto-detect it, so it could not be driven through that interface) and `jedi` 0.20.0 (via pip; a mature, type-inference-based Python reference/definition engine with a clean Python API, used directly). Jedi's project-wide `get_references()` gave a genuine third data point — a real type-inference engine, architecturally unlike both GraphGraph's and code-review-graph's tree-sitter-based extraction — for the two hardest oracle checks below.

---

## Executive summary

GraphGraph's structural core is sound: on every ground-truth-checked caller/callee query it either matched grep exactly or correctly refused to guess. Its self-diagnosis is unusually good — confidence, completeness, and abstention are reported per-query and were never caught asserting something false (the instrument passed its own red test). The two real defects found are narrow and fixable: (1) `describe_formats`'s documented token-cost multiplier for the `sql` packet format is backwards — it claims `sql` costs *more* than `gg`, but it measured *less*, twice, at two different result sizes; (2) informal entity-name queries (e.g. "the Flask class") pull in lexically-similar-but-structurally-unrelated symbols as co-equal anchors, padding packets with dead weight. A genuine extraction gap (return-type-flow-derived receiver types) was also found, confirmed against a third independent oracle (the `jedi` type-inference engine, installed mid-session), and is already disclosed by GraphGraph's own telemetry — so it is a confirmed, known-unknown, not a silent lie. The same jedi run also positively validated GraphGraph: its production-caller resolution for `App.add_url_rule` matched jedi's exactly, 3 for 3, zero false positives.

The one benchmark I set out to run — incremental-update marginal cost vs. corpus size — could not be completed. External stopwatching in this harness is invalid: a *no-op* `project_status` call round-tripped in 26.9s, dwarfing any plausible sub-second compute difference. This is a property of my measurement environment, not of GraphGraph, and I am flagging it loudly rather than reporting a number I don't trust (see Retraction below).

**Score:** 6.5/10 today, credible ceiling 9/10. The gap is concentrated in one layer (member-call resolution, capped at 67% by the tree-sitter-only frontend) that the tool already has the ontology and telemetry hooks to close without a redesign.

---

## Retraction / methodology note (read first)

I attempted to benchmark `update_graph_files` (1-file incremental update) against `build_graph` (full 231-file rebuild) using external wall-clock timestamps bracketing each MCP call. The calibration control — timing a `project_status` call that does no writing and should be near-instant — returned **26,921 ms** round-trip. The incremental update itself measured **9,688 ms**, i.e. *faster* than the no-op calibration call. This proves the external timing is dominated by conversational-turn/tool-dispatch overhead in this harness, not by GraphGraph compute, and is unusable at the sub-second resolution needed to judge incrementality. I did not publish a marginal-cost number. This is a **methodology failure on my part**, not a finding about GraphGraph — flagging per the skill's evidence-discipline rule to retract loudly rather than let an unreliable number stand.

What I could still establish: `build_graph` self-reports a detailed `phase_profile` (wall_ms per phase, attributed-ratio 0.9998 — internally consistent) on full builds, but `update_graph_files` and `remove_graph_files` report **no timing at all** in their response payload. That asymmetry is itself Finding 3 below.

---

## Phase 0 — Instrument validation (red test)

Queried `mcp__graphgraph__query` for `"who calls quantum_teleport_config_nonexistent_xyz"` (direction=callers, a symbol that provably does not exist in Flask).

- `search_nodes` did not hallucinate an exact match; it returned only genuine fuzzy matches on the substring `config`.
- `query` correctly returned `status: unanswerable`, `abstained: true`, `confidence: 0.0`, and an explicit `missing_evidence` list naming the fake symbol.

The metric moved on a known-failure input. Also checked for internal contradiction across three independent completeness signals returned together on real queries — `graph_complete`, `answer_complete`, and `caller_evidence_complete`/`call_topology_status` — and found them consistent with each other in every test below (e.g. `graph_complete: false` at `limit=1` when 3 results existed, `true` once `limit` covered all 3; `answer_complete: false` throughout, correctly, because global call-topology resolution is only partial). **The instrument passed validation** — I did not catch it reporting a confident-green number for a case I could prove was bad.

---

## Findings

### Finding 1 — `describe_formats`'s `sql` token-cost multiplier is backwards (confirmed twice)

**Symptom:** `describe_formats` advertises `sql` as `relative_tokens: "1.38x+"` versus `gg`'s documented `1.00x` floor. Measured on two independent real queries against the built Flask graph (via `query`'s own self-reported `metrics.packet.proxy_tokens`, not my byte-counting):

| Query | gg tokens | sql tokens | measured sql/gg ratio | documented ratio |
|---|---|---|---|---|
| `direct_lookup` on `SessionInterface` (14 nodes, 13 edges) | 2803 chars (proxy) | 1008 chars (proxy) | **0.36x** | 1.38x+ |
| `blast_radius` on `Flask` class (36 nodes, 42 edges) | 945 tokens | 734 tokens | **0.78x** | 1.38x+ |

`hybrid` and `semantic_arrow` were checked in the same pass and roughly track their documented ratios (hybrid measured 2.24x vs. documented ~2.3x on the larger query; semantic_arrow measured 1.38x vs. documented ~1.49x). Only `sql` is wrong, and it's wrong in the same direction both times — not noise, a systematic mislabel.

**Evidence:** Direct oracle — GraphGraph's own self-reported `proxy_tokens` field, re-derived on two differently-sized queries, both times `sql < gg` when the schema declares `sql > gg`.

**Inferred:** `sql`'s pipe-delimited table rows have genuinely lower per-node/per-edge character overhead than `gg`'s tagged adjacency-list syntax for Flask-shaped data (mostly narrow method/class names, short paths) — the `relative_tokens` figure in `describe_formats` looks like it was computed from `schema_tokens` (per-row *schema* overhead: `sql` declares `schema_tokens: 10` vs. `gg`'s `20`) inverted, or from a different corpus shape where SQL's `TABLE nodes:` / `TABLE edges:` headers dominate small payloads. *Marked as inference — I did not read the code that computes this number.*

**Floor:** A `describe_formats` call whose numbers an agent can trust without re-deriving them per-query. Right now an agent doing token-budget-aware format selection would actively avoid `sql` believing it's the *most* expensive non-hybrid format, when empirically it was the *cheapest* format tested on both queries.

**Gap:** Not a distance-to-floor problem — it's a correctness problem in the self-description itself. Any agent trusting the documented ratio to pick a format under a tight token budget picks wrong.

**What if:** Recompute `relative_tokens` empirically (mean ratio over a representative query sample, refreshed periodically) instead of declaring it statically, and have `describe_formats` self-report the corpus/sample it was measured against — turns a static claim into a checkable one.

---

### Finding 2 — Lexical anchor pollution on informal entity-name queries

**Symptom:** Querying `blast_radius` for "the Flask class" (and separately "what breaks if I change the Flask class") returns `Flask`, `FlaskProxy`, `FlaskGroup`, `FlaskClient`, `FlaskCliRunner`, and (in one run) `FlaskTask` as co-equal ranked anchors, all contributing to the same packet.

**Evidence (direct oracle, grep against Flask source):**
```
src\flask\app.py:109:      class Flask(App):
src\flask\cli.py:531:      class FlaskGroup(AppGroup):        # inherits click's AppGroup, NOT Flask
src\flask\testing.py:109:  class FlaskClient(Client):         # inherits werkzeug's Client, NOT Flask
src\flask\testing.py:265:  class FlaskCliRunner(CliRunner):   # inherits click's CliRunner, NOT Flask
src\flask\globals.py:22:   class FlaskProxy(ProxyMixin[Flask], Flask): ...  # genuinely inherits Flask
```
Of the six lexically-matched "Flask*" anchors, only `FlaskProxy` has a real structural (inheritance) relationship to the `Flask` class. `FlaskGroup`, `FlaskClient`, and `FlaskCliRunner` share a name prefix only. In the `examples/celery` run, `FlaskTask` was included as an anchor and its own `anchor_contribution` count was **0 edges** — it was carried into the result set and contributed nothing, pure packet padding.

**Inferred:** anchor selection for underspecified natural-language entity references (`the Flask class`) ranks by lexical/label similarity (`label_exact:flask`, `path:flask`, `summary:flask` — visible in the `reasons` field of each anchor) without a structural tiebreak (e.g., preferring the node with an actual `implements`/inheritance edge to the literal string when one exists and the query says "class").

**Floor:** For a query naming one real class, the ideal anchor set is that class plus nodes actually reachable from it in ≤2 hops — not every symbol sharing a name prefix.

**Gap:** In the 36-node blast-radius packet, roughly 20 of 36 nodes trace back to the three unrelated Flask*-prefixed classes' own internals (methods, their callers, their imports) rather than to `Flask` itself — over half the token budget spent on symbols the query didn't actually mean.

**What if:** When an anchor candidate set contains an exact-label match plus several prefix/substring matches, weight the exact match higher and require ≥1 real graph edge (not just lexical score) to co-admit a same-scoring sibling; drop anchors that end up contributing zero edges to the final packet (this is cheap — `anchor_contribution` is already computed and returned).

---

### Finding 3 — Telemetry asymmetry between full build and incremental update

**Symptom:** `build_graph` returns a rich `phase_profile` (`wall_ms`, `attributed_ms`, per-phase breakdown, `attributed_ratio`). `update_graph_files` and `remove_graph_files` return only `{action, paths, nodes, edges, validation}` — no timing of any kind.

**Evidence:** Direct comparison of the two response schemas on the same graph (see raw calls in this session).

**Inferred:** the incremental path likely doesn't instrument phases the same way the full-scan path does (not verified — I did not read the implementation).

**Floor:** Every mutating call self-reports at least a total `wall_ms`, the same way `query`/`query_relations` already self-report `receipt.milliseconds` on every read.

**Gap:** Because of this, GraphGraph's central pitch — cheap incremental updates that keep a graph fresh without a full rescan — is currently **unverifiable by the caller**. I could not confirm or refute it in this session (see Retraction above); an agent relying on GraphGraph in a tight edit-loop has no way to know from the tool's own output whether an update was O(files-changed) or secretly re-scanned everything.

**What if:** add a `phase_profile`-shaped (or even single-scalar `wall_ms`) field to `update_graph_files`/`remove_graph_files` responses. This is the single cheapest fix in this report and turns an unfalsifiable claim into a CI-gateable one (see gates below).

---

### Finding 4 (disclosed, not hidden) — Return-type-flow is a real blind spot in member-call resolution

**Symptom:** `query_relations(target="BlueprintSetupState.add_url_rule", direction=callers)` returns 0 callers.

**Evidence (direct oracle, confirmed by a third, independent, type-inference-based tool):** `src/flask/sansio/blueprints.py:321` — `state = self.make_setup_state(app, options, first_bp_registration)`, then `blueprints.py:324` — `state.add_url_rule(...)`. This is one real, unambiguous call site whose receiver type (`state`) requires propagating `make_setup_state`'s return-type annotation to a local variable — a level of dataflow GraphGraph's tree-sitter frontend does not currently perform.

I did not just eyeball this from grep — I installed `jedi` (0.20.0, `pip install jedi`) mid-session and ran `Script.get_references()` directly against the `add_url_rule` definitions as a genuinely independent, type-inference-based oracle (jedi resolves receiver types via real static type inference, not tree-sitter pattern matching — an architecturally different lineage from both GraphGraph and code-review-graph). Result for `BlueprintSetupState.add_url_rule`:

```
[DEF] blueprints.py:87:8   def add_url_rule
[ref] blueprints.py:324:18 add_url_rule
```

Exactly one reference, exactly the call site GraphGraph missed. This upgrades the finding from "inferred from reading the source" to **confirmed by an independent type-checker**: GraphGraph's `0` is a false negative, not a defensible reading of ambiguous code.

Usefully, jedi *also* failed to attribute the second, harder case — `blueprints.py:434`, `self.record(lambda s: s.add_url_rule(...))` — to `BlueprintSetupState.add_url_rule`; jedi's reference list for that target has no entry at line 434. This matters for prioritization: the `state.add_url_rule(...)` miss (line 324) is a **tractable** gap that a real type-inference engine closes routinely (return-type propagation through one local variable). The lambda-callback miss (line 434) is **hard even for jedi** (requires inferring a callback parameter's type from how `self.record()` later invokes it) and should not be prioritized the same way — it's a genuinely hard dataflow problem, not a shallow gap.

**Cross-check, and a positive result:** the same jedi run against `App.add_url_rule` found exactly 3 non-test call sites: `examples/tutorial/flaskr/__init__.py:46`, `src/flask/app.py:358`, `src/flask/sansio/blueprints.py:110` — **the identical 3 production callers GraphGraph itself returned** for that target (`create_app`, `Flask.__init__`, `BlueprintSetupState.add_url_rule`). Zero false positives, zero missed production sites. On this target, GraphGraph's production-scope resolution is complete against an independent type-checker.

One open discrepancy, reported rather than resolved: jedi found 18 references to `App.add_url_rule` inside `tests/`; GraphGraph's receipt reported `filtered.tests: 29` for the same target; a raw `grep -rn "\.add_url_rule(" tests/` finds 42 textual occurrences across 8 files. Three tools, three different counts (18 / 29 / 42). I did not reconcile this by hand-auditing all 42 sites — plausible, unverified explanations include multi-line call wrapping inflating the grep count, and test fixtures subclassing `Flask`/`App` in ways that route some calls to a different (test-local) override that jedi resolves away but GraphGraph's simpler name-based test-tagging still counts. **Marked as an open question, not a finding** — flagging it is more honest than picking whichever number flatters or damns GraphGraph.

**By contrast**, direct-attribute receiver typing worked correctly: `BlueprintSetupState.add_url_rule` (line 110, `self.app.add_url_rule(...)`) *was* correctly attributed to `App.add_url_rule` with `evidence: "receiver self.app:App"`, and `Flask.__init__`'s `self.add_url_rule(...)` was correctly resolved via inheritance (`self` typed as `Flask`, which extends `App`).

**This is not a silent failure.** Every query touching this target returned `call_topology_status: "partial"`, a concrete ratio (`67.0% (883/1318)`), and explicit language that "zero-caller counts are an upper bound on dead code, not a proof." That caveat is exactly correct for this case. I'm reporting the underlying gap because it's a good, concrete example of what the disclosed 33% actually looks like — not because the disclosure failed.

**Floor:** 100% receiver resolution requires full type inference (a real type checker), which is out of scope for a tree-sitter frontend by design.

**Gap:** ~33% of member-call sites (435 unknown-receiver + fraction of 97 unmatched, out of 1318 receiver sites) are currently *dropped silently from the edge set* rather than *downgraded*. The ontology already defines a `calls_candidate` relation (`strength: 0.25`, `traversable: false`, "may invoke target; receiver/type evidence did not identify one unique method") for exactly this situation, but it doesn't appear to be populated for the `state.add_url_rule(...)` case — the call site simply produces no edge at all rather than a weak `calls_candidate` edge.

**What if:** for member calls where the receiver type is unknown but the callee name uniquely matches exactly one same-named method on any class the variable could plausibly hold (or is unresolvable at all), emit a `calls_candidate` edge instead of nothing. This wouldn't fix precision, but it would fix recall-of-uncertainty: a `callers` query would show *something* instead of `0`, with the existing "upper bound, not proof" framing carrying the caveat.

---

## Metamorphic / invariant checks

| Relation | Test | Result |
|---|---|---|
| **Negation** | `negative_query`: "does flask have a graphql resolver system" | Correctly abstained, `confidence: 0.665` on absence, no fabricated evidence. **Pass.** |
| **Monotonicity** | `query_relations(add_url_rule callers, limit=1)` vs. `limit=50` | `limit=1` returned 1/3 eligible (`graph_complete: false`); `limit=50` returned all 3, a strict superset of the `limit=1` result. **Pass.** |
| **Disambiguation honesty** | `add_url_rule` has 4 definitions (App, Blueprint, BlueprintSetupState, Scaffold) | Both GraphGraph and code-review-graph independently refused to pick one and returned all 4 candidates rather than silently guessing. **Pass, and matches an independent peer implementation.** |
| **Idempotence** | Not independently re-run after the initial pass; not marked failed, marked **not tested** (see coverage). | — |

---

## Head-to-head: GraphGraph vs. `code-review-graph` (same Flask checkout, same commit)

`code-review-graph` was built fresh on the identical checkout for a fair comparison (`full_rebuild=true`; 86 files, 1708 nodes/8333 edges pre-postprocess, 1446 nodes/8319 edges reported by its stats tool — it scopes to source-ish files only, no `docs/`).

| | GraphGraph | code-review-graph |
|---|---|---|
| `get_root_path` callers | 1/1 correct (Scaffold.__init__) | 1/1 correct (Scaffold.__init__) — **identical** |
| `add_url_rule` (ambiguous name) | Returns 4 candidates, refuses to guess | Returns 4 candidates, refuses to guess — **identical behavior, independently arrived at** |
| Per-query confidence/completeness | Yes — `answer_complete`, `graph_complete`, `call_topology_status`, `receiver_resolution_ratio`, abstain reasons, all on every response | **No.** `query_graph_tool` returns bare result lists; a `0`-result answer is indistinguishable from "definitely doesn't exist" vs. "extraction gap" |
| Explicit test-linkage edges | Via `tests` relation in ontology (not exercised heavily in this run) | First-class `TESTED_BY` edge kind, 1970 edges out of the box |
| Inheritance as first-class edge | Via `implements` relation | First-class `INHERITS` edge kind, 116 edges |
| Token-budgeted packet formats | 10 formats (`gg`, `sql`, `hybrid`, `semantic_arrow`, `svo`, `gg_lex`, ...) with self-reported token cost per query | None observed — results are structured JSON, not pre-shaped for LLM context windows |
| Natural-language query routing | Yes (`query`/`query_context` compile NL into typed operators with a routing confidence/margin) | No — pattern name + target string, caller supplies the query "class" |
| Community/architecture overview | `project_status(view=atlas)` — subsystems, couplings, representatives | `get_architecture_overview_tool` — comparable, community-detection-based |

**Read:** on raw structural accuracy for the two things I could cheaply verify against grep, the two tools tied. GraphGraph's decisive edge over this real peer is epistemic — it tells an agent *how much to trust* each answer; code-review-graph does not expose that at the query level at all. That is GraphGraph's strongest, most defensible differentiator in this evaluation, and it should be protected/extended rather than traded away for feature parity elsewhere.

---

## Where GraphGraph sits against the wider field

The LSP/type-inference row below is now backed by the jedi data above, not just description; the rest were not executed against Flask this session (no local install pursued, or out of scope for a single-session pass) and are included because the user asked what "best in category" would require. Based on established, publicly documented capabilities of each class of tool where not otherwise noted — treat everything except the LSP/jedi row as desk research, not oracle-verified benchmark.

- **`ripgrep`/`grep`** — the floor. Zero setup, zero false structural claims (it makes none), but zero understanding: no callers, no blast radius, no disambiguation. Used *as the oracle* throughout this report. Any context-graph tool that can't beat grep's precision on a query grep can also answer isn't earning its keep.
- **`ctags`/`universal-ctags`** — adds a symbol-definition index (jump-to-def) but no call graph, no cross-file resolution, no confidence signal. Not installed/run this session.
- **LSP / type-inference engines (jedi — empirically run this session; pyright/pylance, gopls, rust-analyzer, tsserver — same class, not run)** — the real-type-checker gold standard for single-language find-references/go-to-def precision. Empirically, jedi resolved the `state.add_url_rule(...)` receiver-type-flow case that GraphGraph's tree-sitter frontend missed (Finding 4), confirming the ~67% receiver-resolution ceiling measured on GraphGraph is a real, closable gap relative to this class of tool — not an artifact of my reading. What full LSP/type-checkers still lack for *this* use case even where they win on precision: no natural-language query layer, no LLM-token-budgeted packet output, no cross-language federation, no self-explained abstention/confidence, no portable offline export, one server per language with no unified cross-language graph. (I attempted to drive this through the harness's built-in `LSP` tool after installing `pyright` globally via npm; the tool reported `No LSP server available for file type: .py` both before and after the install, i.e. it does not auto-discover newly installed servers on PATH — a note for whoever configures that tool, not a GraphGraph finding.)
- **CodeQL** — excellent for security/dataflow queries via a real query language over a compiled database; batch/offline, steep authoring curve, not built for interactive per-turn agent context assembly under a token budget.
- **Sourcegraph / Glean (Meta) / Kythe (Google)-class code-intelligence platforms** — the ceiling for cross-repo precision at scale, built on SCIP/LSIF indexes emitted by each language's own compiler, so receiver resolution approaches 100%. Costs: heavyweight per-language indexer pipelines, server/team infrastructure rather than a single MCP call, and — same as LSP — no first-class "packet formats sized for an LLM context window" concept or self-reported confidence designed for autonomous-agent consumption.
- **Embedding/RAG-only code search** — best recall for "what talks about X" via semantic similarity, but no grounded structural truth and prone to confidently-wrong relationships. GraphGraph's `concept_linking` (typed-fact/exact-alias, measured 23.1% coverage here) is a narrower, more honest version of this — it's explicitly flagged `status: partial` rather than presented as ground truth, which is the right posture; it's just thin right now (351 links / 1516 eligible nodes on Flask).

---

## "If I had XYZ, this would be the best context-graph tool for anything" — synthesized wishlist

In priority order, cheapest/highest-leverage first:

1. **Fix `describe_formats`'s `sql` ratio** (Finding 1). Free — it's a documentation/measurement bug, not an engineering project. Recompute empirically instead of declaring statically.
2. **Add timing to `update_graph_files`/`remove_graph_files`** (Finding 3). Makes the tool's core incrementality claim self-verifiable instead of requiring an external stopwatch that (per my retraction above) doesn't even work in agent-harness environments.
3. **Populate `calls_candidate` for unresolved-receiver call sites** instead of dropping them (Finding 4). The ontology already has the relation type at the right strength/traversability; it's a wiring gap, not a design gap.
4. **Structural tiebreak in anchor selection** for informal entity-name queries (Finding 2): prefer an exact-label match with a real edge to a name-prefix sibling with none; drop zero-edge-contribution anchors from the final packet automatically.
5. **Optional LSP/compiler-grade backend under `tree_sitter`**, for repos willing to pay the setup cost — `describe_frontends` already lists `cpg` as "PLANNED (not implemented)"; that's the natural slot. This is the one item that would move the *ceiling* (currently capped near 67% receiver resolution by construction) rather than the current score within today's ceiling.
6. **SCIP/LSIF import as an alternate extraction source.** This would let GraphGraph sit on top of Sourcegraph/Glean-grade precision where a team already has it, while keeping GraphGraph's actually-differentiated layer (NL query routing, token-budgeted packets, self-reported confidence/abstention) as the retrieval interface — competing on the layer it's already winning rather than re-fighting the extraction-precision war against compiler-based indexers.
7. **A public single-scalar CI gate per claim**, not adjectives:
   - `sql_tokens / gg_tokens` stays within its documented band (±15%) — turns Finding 1 into a regression test.
   - `update_graph_files` on a 1-file change emits `wall_ms` and it stays flat as corpus size grows 10x (invariance gate — the strongest form, converts "incremental updates are cheap" from a claim into something that fails loudly if it stops being true).
   - `receiver_resolution_ratio` (currently 0.67 on Flask) must not regress between releases on a fixed fixture.

---

## Scoring — today vs. credible ceiling, by layer

Per the skill's guidance: score two ways, decompose by layer, weight by the layer that caps the others (extraction bounds retrieval regardless of how good retrieval logic is).

| Layer | Today | Ceiling | Notes |
|---|---|---|---|
| **Extraction (structural accuracy)** | 6.5/10 | 9/10 | Everything I could grep-verify was either exactly right or honestly refused. The gap is receiver-type resolution (67%), which is architecturally expected for a tree-sitter-only frontend, not a bug — and the tool already tells you it's 67%, which is the correct behavior for this layer today. |
| **Retrieval / query routing** | 7/10 | 8.5/10 | NL→operator routing, query-class-specific traversal policy, and abstention are all genuinely good. Docked for Finding 2 (lexical anchor pollution). |
| **Packet efficiency / token budgeting** | 6/10 | 9/10 | The concept (10 formats, self-reported per-query token cost, format-selection-by-budget) is the single most distinctive feature versus every peer compared above, including code-review-graph. Docked hard for Finding 1 — a token-budgeting feature whose own cost table is wrong for one format undermines the feature's entire premise until fixed. |
| **Self-diagnosis / telemetry** | 8.5/10 | 9.5/10 | This is where GraphGraph clearly beats the one real peer tested (code-review-graph has none of this at the query level) and where it earned its Phase-0 pass. Docked only for the build-vs-incremental timing asymmetry (Finding 3). |
| **Ergonomics for an agent caller** | 7/10 | 8.5/10 | Rich, well-structured JSON with next-step suggestions (`a:` action hints in the compact format) is a real strength. Slightly capped by verbosity of the default (non-compact) response shape when only a small answer is needed. |
| **Overall** | **6.5/10** | **9/10** | Weighted toward extraction and packet-efficiency since those cap what the rest of the system can honestly claim. The gap to ceiling is concentrated in a small number of fixable items (5 of 6 wishlist items above are wiring/measurement fixes, not redesigns), which is a good position to be in. |

**What's already at the floor and shouldn't be touched:** the abstention/confidence machinery (Phase 0 pass, negative_query pass, monotonicity pass) and the disambiguation behavior on ambiguous names (matched an independent peer exactly). Don't spend engineering effort re-litigating these — they work.

---

## Coverage — explicitly not tested this cycle

Absence of a result below should not be read as a pass or a fail — it means I did not test it in this session:

- `multi_hop_path`, `recent_changes`, `spreading_activation` query classes
- `graph_change` (before/after diff, breaking-change detection)
- `memory_context` (add/query/list scoped memory)
- `repair_context` (issue/trace → bounded repair context)
- `select_symbols` predicate DSL beyond the implicit use inside other calls
- Any non-Python frontend (`rust`, `js/ts`, `go`, `java`, `c/cpp`, `csharp`, `ruby`, `php`, `kotlin`, `scala`, `swift`) — Flask is Python-only, so tree-sitter multi-language support is untested here
- `history`/`docs` extraction flags (`build_graph` supports `docs: true`, `history: true`; not exercised)
- True marginal-cost scaling of incremental updates (blocked by harness timing overhead — see Retraction)
- Idempotence (ran once per query; did not systematically re-run and diff)
- Federation / `cross_repo` relation family
- `export_graph` (.gg native export) and downstream re-import fidelity

---

## Artifacts created during this evaluation

- `C:\Users\dcarn\aiprojects\resources\flask\.graphgraph\graph.gg` — the build artifact from this session (untracked; `git status` shows only `?? .graphgraph/`). Left in place in case it's useful for a follow-up cycle; safe to delete (`rm -rf .graphgraph`) if not wanted — it is not tracked by git and Flask's own source tree was left byte-identical to `git status` clean before and after (a transient probe function added to `helpers.py` mid-session was restored from a backup and confirmed clean).
- Scratch comparison files (`pkt_gg.txt`, `pkt_sql.txt`, `pkt_hybrid.txt`, `pkt_svo.txt`, `helpers_backup.py`, `jedi_probe.py`) in this session's Claude scratchpad directory — outside the repo, no action needed.
- `code-review-graph`'s own graph database for the Flask checkout (location managed by that tool, not GraphGraph) — left in place for reproducibility of the head-to-head comparison.
- **Global tool installs** (with explicit user permission, not confined to the Flask checkout): `pyright@1.1.411` via `npm install -g pyright`, `jedi@0.20.0` via `pip install jedi` (into the active Python env at `hermes-agent/venv`). Both are standard, widely-used, reversible installs (`npm uninstall -g pyright` / `pip uninstall jedi`); neither modifies Flask or GraphGraph.
