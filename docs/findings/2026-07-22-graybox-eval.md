# Gray-Box Evaluation — graphgraph 0.1.0

**Date:** 2026-07-22 · **Method:** `/graybox` (CLI-only; source and git history never read)
**Fixtures:** `tuya-ble-scanner` (10 py files, small stratum) · `sd-scripts` (193 py + 46 docs, large stratum)
**Environment:** Windows 11, Python 3.12.10, tree-sitter frontend, hash (lexical) semantic backend, no venv

---

## Retractions (read first)

1. **"Small repo resolved 0 calls" — retracted.** Ground truth (grep) shows
   `tuya-ble-scanner` genuinely has no cross-file internal calls. The tool was right.
2. **"LoRAModule ambiguity hidden" — retracted.** The full packet contains all 6
   `class LoRAModule` definitions; my first look truncated at the top-5 evidence
   points. (Classic Phase-4 rule-1 near-miss: never conclude absence from a prefix.)

---

## Scorecard

| Layer | Today | Credible ceiling | Why |
|---|---|---|---|
| Extraction (symbols/docs) | 7/10 | 9 | Tree-sitter solid, 15 langs; doc phase has a data-file pathology (F6) |
| Extraction (call graph) | **3/10** | 9 | Module-qualified calls unresolved (F3) — **this layer caps everything above it** |
| Retrieval (literal queries) | 7/10 | 9 | Correct anchors, compact packets, monotone budgets |
| Retrieval (paraphrase/semantic) | 2/10 | 8 | Zero paraphrase recall on default backend (F7) — honestly self-reported |
| Latency (agent edit loop) | 5/10 | 9 | ~2s cold query, ~0.5s cached; 1-file update not O(Δ) (F4) |
| Instrument honesty | 8/10 | 10 | Abstains on null queries, names missing facets, volunteers caveats |
| Trust calibration | **4/10** | 9 | Answerability gate errs in *both* directions (F2) |

**Overall today: ~6/10 as an agent context tool. Ceiling: 9+.** The hard part —
packet IR, budget planner, gate/receipt architecture, telemetry design — is done
and close to the floor. What's missing is plumbing: call resolution, delta
persistence, real embeddings, gate calibration.

---

## Findings (ranked)

### F2 · Answerability gate is uncalibrated in both directions — INSTRUMENT, HIGHEST RISK
- **Symptom:** `query "who calls load_metadata_from_safetensors"` → `status: answerable`
  while returning **0 of 4** ground-truth call sites. `query "definition of LoRAModule class"`
  → `status: incomplete, abstained: true, confidence 0.23` while the packet fully answered
  the question (all 6 definitions).
- **Evidence:** direct oracle (grep of sd-scripts) both times.
- **Why ranked first:** per the graybox prime directive, a confident green light over a
  wrong answer poisons every downstream consumer. Agents will *trust this field*.
- **Inferred cause** *(inference)*: facet extraction is lexical ("definition class" treated
  as an unmatched facet) and the gate keys off facet-string matching, not evidence quality.
- **Gate:** calibration suite in CI — a fixture with known-answerable and known-unanswerable
  queries; require `answerable ⇒ recall ≥ 0.8` and `fully-answered ⇒ not abstained`.

### F3 · Module-qualified call resolution is effectively absent — CORRECTNESS, BIGGEST GAP
- **Symptom (observed):** sd-scripts scan telemetry: `member_calls = 586 resolved /
  104 ambiguous / 1832 unknown-receiver / 12085 external-or-unmatched`. Reverse lookup
  for a function with 4 real call sites (`networks/*_merge_lora.py` →
  `model_io.load_metadata_from_safetensors(...)`) returned definitions + one import edge,
  **zero `calls` edges**.
- **Evidence:** direct oracle — grep found all 4 call sites; none appear in the packet.
- **Inferred** *(inference)*: `module.func()` receivers are not resolved against the
  `imports`/`imports_from` edges the graph *already has*. The information needed for
  resolution is in the graph; the join is missing.
- **Floor:** with import edges present, resolving `model_io.X` → `library/model_io.py::X`
  is a dictionary lookup at extraction time, ~O(calls). Cost ≈ negligible.
- **Gap:** caller recall on this query: 0%. This caps blast-radius, affected-tests, and
  reverse-lookup quality no matter how good retrieval is — extraction bounds retrieval.
- **What if:** import-aware receiver resolution → reverse lookup and blast radius become
  trustworthy in one change. **Gate:** caller recall ≥ 90% on a ground-truth fixture.

### F4 · `update` violates its own documented scaling contract — PERFORMANCE
- **Symptom (observed):** help text claims *"cost scales with --files, not repo size."*
  Measured 1-file update: **396ms** (10-file repo) vs **1065ms** (265-file repo).
  Marginal cost (minus ~300ms process start): ~100ms vs ~765ms → **~7.7× on a 26× corpus**.
- **Evidence:** differential measurement, same machine, same command shape.
- **Inferred** *(inference)*: O(corpus) graph load + whole-graph structural validation +
  full 4.3MB rewrite dominate. (`update` emits no phase telemetry — see F9 — so this
  cannot be decomposed from the tool's own instruments.)
- **Floor:** reparse 1 file (~5ms) + splice O(Δ) edges + persist O(Δ) bytes ≈ ~30ms
  work + process start, **invariant to corpus size**.
- **Gate (nominated CI scalar):** `1-file update wall time, large fixture == small
  fixture ± 20ms`. An invariance gate — converts "scales acceptably" into "does not
  scale at all," which is the correct target.

### F5 · Second scan after a cold build re-extracts everything — IDEMPOTENCE
- **Symptom (observed):** cold scan 13.5s → immediate unchanged rescan **13.7s with full
  doc re-extraction** → third and later rescans 1.25s (`dirty=0 restored=265`).
  Convergence requires three runs.
- **Inferred** *(inference)*: first scan's hash manifest is not fully persisted (or is
  written in a form that doesn't match the rehash), so scan #2 sees all files dirty.
- Steady-state no-op rescan is still O(corpus): concepts phase re-runs every time
  (~250ms) and the full graph is rewritten.
- **Gate:** `scan #2 on unchanged repo reports dirty=0 and completes < 2s`.

### F6 · Data files ingested as documentation — EXTRACTION PATHOLOGY
- **Symptom (observed):** `configs/qwen3_06b/merges.txt` (BPE tokenizer merges data)
  parsed as a document: **3.66s = 65% of the 5.6s doc phase**, producing 568 junk
  "paragraph" nodes that then compete in retrieval ranking.
- **Evidence:** tool's own slowest-docs telemetry (credit: this telemetry existing is
  what made the finding cheap).
- **What if:** entropy / token-shape sniff before doc parsing → doc phase drops to ~1.9s
  and the graph loses ~570 noise nodes. **Gate:** no single non-markdown file > 20% of
  doc-phase time.

### F7 · Zero paraphrase recall on default backend — CONFIRMED SELF-REPORT
- **Symptom (observed):** literal `"definition of LoRAModule class"` → correct class
  nodes. Paraphrase `"where is the class that implements LoRA modules declared"` →
  5 unrelated doc paragraphs, **zero overlap** (semantic-equivalence metamorphic
  relation: total violation).
- **Credit:** `doctor` volunteers exactly this: *"hash (offline lexical fallback — no
  paraphrase recall)."* The caveat is truthful and precisely maps the gap.
- **What if:** bundle a small local embedding model as the default (not opt-in via
  `$GRAPHGRAPH_EMBED_URL`). **Gate:** paraphrase/literal anchor overlap ≥ 60% on a
  10-pair fixture.

### F8 · `eval` silently accepts garbage — DECORATIVE-INSTRUMENT RISK
- **Symptom (observed):** `eval --tasks <file containing {"bad":"schema"}>` → prints
  `[]`, **exit 0**. No schema error, no warning.
- A benchmark harness that exits green on malformed input will one day report a
  perfect score on an empty task list. **Gate:** malformed tasks file ⇒ nonzero exit.

### F9 · Telemetry asymmetry — `scan` is exemplary, `update`/`query` are opaque
- `scan` emits per-phase receipts, slowest-docs, member-call accounting, truncation
  lists — best-in-class. `update` prints 2 lines; F4 could not be decomposed without
  external timing. **What if:** the same phase-receipt framework on every subcommand.

### F10 · Fixed-cost profile
- **Observed:** process start ≈ 300ms (0.4s wall vs 0.1s internal on small repo);
  query on 9800-node graph ≈ 2.0s cold, ≈ 0.52s cache-hit. Cache works (~4× saving)
  but ~500ms/invocation floor remains for an agent edit loop.
- The fixed:marginal ratio (≈ 500ms : ~200ms) is exactly the regime where a warm
  daemon pays off. An MCP server already exists (`graphgraph-mcp`, registered) —
  **not measured here**; measuring its per-call latency is the obvious next cycle.

### F1 · Null-query behavior — PASS, with a token tax
- Red test (`FrobnicateQuantumFlux77`): abstained, confidence 0.22, named the missing
  facet, refused implementation authorization. **The abstention machinery is real** —
  rare in this tool category. Minor: still spent 516 tokens on 20 irrelevant
  "structural context" nodes; a null query's ideal packet is near-empty.

---

## What is already at the floor — do not touch

- **`#gg` packet format:** 516–968 proxy tokens for genuinely useful answers; compact
  relation/node/edge encoding. This is the product's core asset.
- **Budget monotonicity:** `--max-nodes 20` result set ⊆ `--max-nodes 80` set
  (0 violations). The planner's regularized budget (`n*=42, λ=0.092`) behaves.
- **Honest self-diagnosis:** `doctor` and scan telemetry volunteer their own
  weaknesses (semantic fallback caveat, truncation lists, member-call accounting).
  The caveats pointed at 3 of the 10 findings — keep writing them.
- **Data-loss guard:** `scan --force` refusal semantics for >50% graph shrink.

## Pinnacle requirements (ranked by leverage)

1. **Import-aware call resolution** (F3) — one join collapses the biggest correctness gap.
2. **Calibrated answerability gate** (F2) — makes every other number trustworthy.
3. **O(Δ) update path** (F4/F5): delta persistence + spliced-region-only validation.
   Target: 1-file update invariant to corpus size.
4. **Warm daemon / measure MCP path** (F10): sub-100ms in-loop queries.
5. **Default local embeddings** (F7): paraphrase recall without configuration.
6. **Data-file sniffing in doc phase** (F6).
7. **Loud `eval` schema failures** (F8) + uniform phase telemetry (F9).

## Proposed CI gates

| Gate | Threshold | Current |
|---|---|---|
| 1-file update, large fixture | == small fixture ± 20ms | 1065ms vs 396ms ✗ |
| Unchanged rescan #2 after cold build | dirty=0, < 2s | 13.7s full re-extract ✗ |
| Caller recall (ground-truth fixture) | ≥ 90% | 0% on tested query ✗ |
| Answerable ⇒ recall | ≥ 0.8 | violated ✗ |
| Paraphrase anchor overlap | ≥ 60% | 0% ✗ |
| Malformed eval tasks | exit ≠ 0 | exit 0 ✗ |
| Budget monotonicity | 0 violations | 0 ✓ |
| Null-query abstention | abstains + names facet | ✓ |

**Nominated single scalar:** wall-time of a 1-file `update` on the large fixture.
One number, cheap, assumption-free, and it moves the moment the O(Δ) work lands.

## Coverage — tested vs not tested

**Tested:** scan (cold/incremental/idempotence), update (1-file, both strata), query
(direct/reverse/blast-radius/null, cache, budgets), eval (schema handling only),
doctor, frontends, traversal.
**Not tested (silence ≠ pass):** `plan`/`render`/`final` packet workflow, `snippets`,
`select`, `context` one-step, `export`/`ingest`/`compare`, `profile`, `platform`
(evidence/memory/time/federation/repair), `--history` extraction, non-Python
languages, the MCP server path, `eval` with a *valid* tasks file.

## Test artifacts left in fixtures

- `tuya-ble-scanner/.graphgraph/` and `sd-scripts/.graphgraph/` (graph + cache stores)
- mtime bumps on `sd-scripts/library/utils.py`, `tuya-ble-scanner/analyze.py` (touch only, no content change)
- Cleanup: `graphgraph remove-graph-files` or delete the `.graphgraph/` dirs.
