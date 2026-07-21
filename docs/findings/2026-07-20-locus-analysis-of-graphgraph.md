# Locus analysis of GraphGraph — findings

**Date:** 2026-07-20
**Tool:** `locus` 0.1.0, release build compiled from `locus` main at time of run
(includes koopman/semiring_closure/game_theory/learning_theory work through 2026-07-20).
**Target:** `C:\Users\dcarn\aiprojects\graphgraph\src` — 132 Python files.
**Command:** `locus analyze <src>` (plus `--lane quality`, `--lane discovery`).
**Runtime:** 20.8 s. Exit 0.

**Every finding below was checked against the actual GraphGraph source.** Locus's
output is reported as *claims*, then marked CONFIRMED or FALSE POSITIVE with the
evidence. Nothing here is taken on the tool's word.

---

## Headline

```
592 objects analyzed → 1,427 findings
  1,402 observation lane (inventory + structure)   ← noise
     17 discovery lane
      8 quality lane                               ← the actionable set
```

**98.2 % of output is observation-lane inventory/structure notes.** The signal is
the 8 quality-lane findings. Of those, after verification:

| Verdict | Count | Findings |
| --- | ---: | --- |
| Confirmed, actionable | 1 | `__main__.py` duplication (partial) |
| Confirmed but trivial | 1 | `directory / name` shared expression |
| **False positive** | 6 | 2 conditioning hazards, 2 "optimized equivalents", log1p, difference-of-squares |

Plus one **false negative**: the single genuine `log(1+x)` site in the codebase
was not flagged, while an already-correct `log1p` site was.

---

## Confirmed findings

### 1. `cli/__main__.py` and `mcp/__main__.py` are byte-identical — CONFIRMED

```python
from . import main

if __name__ == "__main__":
    main()
```

Both files, identical. Locus is right that these share a canonical form.

**Caveat on the advice.** The attached obligation is *"consolidate into a shared
utility or constant"*, which is not achievable here — Python requires a literal
`__main__.py` per package for `python -m graphgraph.cli` to work. The duplication
is idiomatic and load-bearing. Correct detection, inapplicable remedy.

**Also note the companion finding is wrong:** Locus separately reported *"3 objects
share identical canonical form"* including the root `__main__.py`. That file is
**not** identical — it reads `from .cli import main`, a different import target:

| File | import |
| --- | --- |
| `cli/__main__.py` | `from . import main` |
| `mcp/__main__.py` | `from . import main` |
| `__main__.py` | `from .cli import main` ← differs |

The canonical form is discarding the import target, which is the semantically
significant part. The 2-object finding is sound; the 3-object one is not.

### 2. `directory / name` shared between two files — CONFIRMED but trivial

Reported as *"Exact logic duplication"* between `platform/persistence.py:41:15`
and `platform/source_planner.py:421:15`. Both do contain `path = directory / name`
inside a filename-candidate loop — but the surrounding logic differs (`continue`
vs `return path`), and the shared fragment is a single path join.

Technically true, not worth acting on. Flagging a two-token expression as
duplication that should be "consolidated into a shared utility" is noise.

---

## False positives (verified)

### 3. `log1p` recommended for code that already uses `log1p` — FALSE POSITIVE

Locus flagged `retrieval/git_utils.py` with *"prefer `log1p(x)` over `log(1 + x)`"*.
`git_utils.py` contains **no `log(1 + x)` at all**. What it contains is already the
stable form:

```python
253:  structural = math.log1p(degree.get(node_id, 0)) / math.log1p(max(1, max_degree))
261:  change_mass = math.log1p(max(0, change_count)) / math.log1p(max(1, max_changes))
```

**Minimal reproduction.** A two-function probe — one already-stable, one genuinely
naive:

```python
import math

def already_stable(x, y):
    return math.log1p(x) / math.log1p(y)     # already correct

def genuinely_naive(a, b):
    return math.log(1.0 + a / b)             # real opportunity
```

`locus analyze probe.py --lane quality` emits **two** log1p findings, not one. It
fires on `math.log1p` itself.

**Mechanism — CONFIRMED in the Locus source, not merely inferred.**
`lower_call` (`locus-frontends/src/formula.rs:681`) deliberately expands stable
intrinsics so the e-graph can reason about them:

```rust
"log1p" | "ln_1p" => Ok(Expr::log(Expr::add(vec![Expr::int(1), a.remove(0)]))),
```

The advisor then pattern-matches that expansion and re-derives the intrinsic. It
cannot distinguish "the source wrote `log(1+x)`" from "the source wrote `log1p(x)`
and we expanded it."

**It is a systemic class, not one bug.** A probe using only stable forms —
`math.hypot(a,b) + math.log1p(x) + math.expm1(x)` — produces **three findings, one
per intrinsic**, each recommending the function already in use. `hypot` → `sqrt(a²+b²)`
and `expm1` → `exp(x) + -1` round-trip identically.

Filed against Locus with root cause and recommended fixes:
`locus/docs/bugs/2026-07-20-stable-intrinsic-round-trip-false-positives.md`.

**Impact:** on any numerically careful codebase, this advisor recommends changes
that are already made — the worst false-positive class, because the codebases most
likely to trigger it are the ones that already got it right.

### 4. The genuine `log(1+x)` site was MISSED — FALSE NEGATIVE

`retrieval/relevance.py:80`, the BM25 IDF term:

```python
term: math.log(1.0 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
```

This is a real `log(1 + x)` and a legitimate `log1p` candidate. Searching the full
1,427-finding run: **exactly one log1p finding exists, and it points at
`git_utils.py`.** `relevance.py` never received one.

So the advisor inverted: it fired on the file that was already correct and stayed
silent on the file that wasn't.

### 5. Difference-of-squares at `relevance.py` — FALSE POSITIVE (since FIXED in Locus)

Locus recommended *"prefer `(a - b) * (a + b)` over `a² - b²`"* at
`retrieval/relevance.py`. That file contains **no squaring of any kind** — no `**`,
no `pow(`, no `math.pow`. It also does not contain the factored form, so unlike
the log1p case this is not a round-trip artifact. The only nearby structure is the
BM25 numerator/denominator pair `(total - doc_freq + 0.5) / (doc_freq + 0.5)`,
which has a difference and a sum of related terms but is not a difference of
squares. Appears to be an over-eager structural match.

The finding does carry `obligation: structural pattern match only`, which is
honest — but it is presented at `moderate` severity in the quality lane.

**Root cause found and fixed (2026-07-20).** `check_difference_of_squares` never
verified its terms were squares: `IrOp::Mul` counted with no square requirement and
`IrOp::Pow` counted at any exponent, so the effective predicate was *any difference
of two products*. `a*b - c*d` and `x**3 - y**5` both fired. This was the run's most
serious defect — the suggested form is **not equal** to the original, yet was
labelled `numerically-equivalent`. Fixed by gating on the exact `Add[square,
−square]` shape, with three regression tests (the check previously had none);
`cargo test -p locus-advisors --test suite` passes 154/154. Re-running against
GraphGraph, the quality lane is now 7 findings and this false positive is gone.

### 6. Conditioning hazard in `platform/evaluation.py` — FALSE POSITIVE

Claim: denominator `(index + 1)` has enclosure `[0, 2]` including zero, so the
quotient may have a pole.

Source (`evaluation.py:46-49`):

```python
for index, node_id in enumerate(found):
    ...
    reciprocal_rank = 1.0 / (index + 1)
```

`index` is an `enumerate` counter, so `index ≥ 0` and `index + 1 ≥ 1`. No pole is
reachable. The `[0, 2]` enclosure comes from Locus assuming a **unit input box**
`[-1, 1]` for an integer loop counter. The report states this assumption
explicitly ("over the unit input box"), so the tool is not being dishonest — but
the finding is wrong, and reaches `moderate` severity.

### 7. Conditioning hazard in `planning/shape.py` — FALSE POSITIVE

Claim: denominator `(1/10000 * tau)` has enclosure `[-1/10000, 1/10000]` including
zero.

Source (`shape.py:183-188`):

```python
node_cost, edge_cost = packet_marginal_costs("gg")
tau = node_cost + edge_cost * density
ratio = max(MIN_BUDGET_RATIO, lambda_ / (TOKEN_PENALTY_COST * tau))
```

`tau` is provably bounded away from zero, two call frames away:

```python
# planning/token_cost.py:30
return max(0.1, node_cost), max(0.1, edge_cost)

# planning/shape.py:388
return max(0.05, min(LOCAL_EDGE_DENSITY_CAP, raw_density))
```

So `tau ≥ 0.1 + 0.1 × 0.05 = 0.105`. The division is safe.

**Root cause shared with #6:** Locus analyzes the expression in isolation and does
not follow the `max(…)` clamps that establish the bound. Both hazards die to
one-hop interprocedural range propagation.

### 8. "Optimized equivalents" that are not optimizations — FALSE POSITIVE

Three `[proved] exact_rewrite` findings in the quality lane, each Z3-proved equal
and each marked as an operation saving. Checked against source:

| Site | Source | Locus "optimized equivalent" | Real saving? |
| --- | --- | --- | --- |
| `retrieval/scoping.py:150` | `max(0, line - 5)` | `max(0, (line + -5))` — "saving 1 op" | **None.** `a - 5` → `a + -5` is internal normalization, not a change |
| `retrieval/expansion.py:95` | `max(0.6, min(1.0, 1.0 - (cohesion - 0.4) * 0.67))` | `max((3 * (5^-1)), min(1, ((-67 * (((5^-1) * -2) + cohesion) * (100^-1)) + 1)))` — "saving 2 ops" | **None.** Same expression re-associated; strictly less readable |
| `retrieval/search.py:435` | `min(1.0, 0.20 + 0.80 * (doc_intensity / 0.25))` | `min(1, ((doc_intensity * (5^-1) * 16) + (5^-1)))` — "saving 3 ops" | **Marginal.** Folds `0.80/0.25`, but emits it as `× 0.2 × 16` — still two multiplies, and never folds to `3.2` |

The mathematics is correct — these *are* equal, and the Z3 proofs are sound. The
problem is the **cost model and the rendering**:

- `count_ops()` measures internal IR nodes, not Python operations. `line - 5` and
  `line + -5` are one IR node apart and zero Python operations apart.
- Internal normal forms leak into user-facing recommendations. `5^-1` for `0.2`,
  `100^-1` for `0.01`, `+ -5` for `- 5`. No developer would accept these as an
  improvement to source.

A rewrite should not reach the quality lane as `[recommend]` unless it is cheaper
*in the target language's operations* and renderable in idiomatic source.

### 9. Domain-role findings on graph code — noise (correctly low-confidence)

The discovery lane includes:

- *"consistent with an Arrow-Pratt risk-aversion coefficient −u''/u' (economics)"*
  at 20 % confidence, on `analysis/eval.py` and `acceptance/live_validation.py`
- *"structurally matches a monotone_bounded activation (sigmoid/softplus/ReLU),
  saturating regimes may cause vanishing gradients (ml:activation)"* at 45 %,
  on `graph/core.py` and `retrieval/search.py`

The supporting evidence for the Arrow-Pratt match is literally *"structural
operator `div` present"* — i.e. the code contains a division.

These are `note` severity at stated low confidence in the discovery (non-quality)
lane, which is the right place for them. They are not defects, but they are not
usable signal on a graph-retrieval codebase either.

---

## Assessment

**What Locus did well**

- Ran clean on a 132-file Python codebase in 20.8 s with no crashes or parse
  failures; coverage line reported 0 skipped, 0 read errors.
- Every equivalence it asserted was in fact a true equivalence — the Z3-backed
  proof layer did not produce a single unsound claim. The failures are all
  *relevance* failures, never *soundness* failures.
- It self-labels its weak evidence honestly: `inferred` vs `proved`, explicit
  obligations ("structural pattern match only", "over the unit input box"), and
  low confidence percentages on speculative role matches.
- Lane separation works. Every speculative domain guess landed in `discovery`, not
  `quality`.

**What limits its usefulness here**

1. **Signal-to-noise: 8 actionable findings out of 1,427 emitted (0.6 %).** The
   default report is dominated by per-file inventory notes.
2. **Six of the eight quality-lane findings are false positives.** For a
   general-purpose Python codebase, precision in the actionable lane is the number
   that matters, and it is currently ~25 %.
3. **No line numbers on formula findings.** Findings are attributed to a file
   (`at .../git_utils.py`) with no line, so each one requires a manual hunt.
   The redundancy findings *do* carry `file:line:col` — formula findings should too.
4. **Two systematic root causes account for 5 of the 6 false positives:**
   - *Lifter round-trip* — `log1p` normalized to `log(1+x)`, then re-discovered.
     Fix: mark IR nodes that came from an already-stable source form and suppress
     the corresponding advisor.
   - *Isolated-expression range analysis* — both conditioning hazards die to
     one-hop range propagation through `max(…)` guards and `enumerate`. Fix: follow
     clamps within the enclosing function before reporting a pole.
5. **The op-count cost model is IR-shaped, not source-shaped**, which is what
   makes the "optimized equivalent" findings unactionable.

**Would I run this on GraphGraph again?** Not as a routine gate at current
precision. It is worth re-running after the round-trip and range-propagation fixes,
because the underlying proof machinery is sound — the issue is entirely in which
true statements get surfaced as recommendations.

The single genuinely useful output of this run was **finding #4 by contradiction**:
noticing that the one real `log1p` opportunity in the codebase (`relevance.py:80`,
BM25 IDF) went unflagged. That is worth fixing in GraphGraph regardless of Locus.

---

## Actionable for GraphGraph

1. **`retrieval/relevance.py:80`** — consider `math.log1p((total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))`.
   Real, if minor: BM25 IDF arguments are usually far from zero, so the accuracy
   gain is small. Low priority, genuinely correct.
2. **`cli/__main__.py` / `mcp/__main__.py`** — identical shims. Idiomatic; no action
   recommended, recorded only for completeness.

Everything else Locus reported against GraphGraph is a false positive.
