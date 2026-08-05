# Gray-Box Evaluation Cycles

Dated experiment records from the gray-box evaluation era (2026-07-27 → 2026-08-02).
Each file is the primary source for the claims it states: measured numbers,
verdicts, red-test receipts, instrument bugs found, and explicit caveats.

These are **evidence records, not a task list**. Incomplete work derived from them
lives only in [../../open-work.md](../../open-work.md). Promoted, still-current
results are summarized in [../empirical-evaluation.md](../empirical-evaluation.md);
confirmed defects in [../defect-ledger.md](../defect-ledger.md).

**Reading rule:** a cycle record is true *as of its date*. Where a later cycle
supersedes an earlier one, the later record says so explicitly — see the
influence-field arc below for the clearest example.

## 2026-08-05 cycle

| Record | Result |
|--------|--------|
| [2026-08-05 gray-box cycle](2026-08-05-graybox-cycle.md) | **Critical:** a single-file JS `update` silently deleted ~65% of cross-file `calls` edges. Root-caused and fixed: external nodes carry a synthetic `npm:` locator, so the update's retain-by-owning-file test dropped every external belonging to an untouched file. Also: `status --probe` casing, and `orient` omitting subdirectories. |
| [2026-08-05 T-B07 preflight-veto fix falsified](2026-08-05-tb07-preflight-veto-fix-falsified.md) | Two candidate fixes for the conceptual-query preflight veto both rescue the adversarial near-miss red control along with the real answer — neither lexical-score nor raw-cosine-embedding corroboration has a safe threshold. Nothing shipped; needs compound-facet-aware re-ranking or margin scoring, not a cutoff. |

## Methodology and instrument validity

| Record | Result |
|--------|--------|
| [2026-07-30 token proxy recalibration](2026-07-30-token-proxy-recalibration.md) | `estimate_tokens` was a bare word count with **47.2% cross-format spread**; recalibrated to 2.78% mean error. **Invalidates every `estimate_tokens`-denominated figure recorded before this date.** |
| [2026-08-02 agent-cycle efficiency and quality tracker](2026-08-02-agent-cycle-efficiency-quality-tracker.md) | Workstream scorecard behind the OW-AC-* rows in open-work. |

## Influence-field arc (three cycles, ending in a negative result)

| Record | Result |
|--------|--------|
| [2026-07-29 influence field coupling](2026-07-29-influence-field-coupling.md) | The influence field, not the cover formula, is the failing stage. |
| [2026-07-30 recoupled cover verdicts](2026-07-30-recoupled-cover-verdicts.md) | Fixing the field did not rescue the cover — it raised the baseline (`+0.066` exact recall, field-ranked selection). |
| [2026-07-30 coupling has no production leverage](2026-07-30-coupling-has-no-production-leverage.md) | **Superseding verdict.** In production `search_nodes`, recall and MRR are unchanged; NDCG@10 moves `+0.0021` at **11.9x** latency. `F1-SYMMETRIC-COUPLING` is measured but not promotable. |

## Critical gray-box ceiling and scope resolution

| Record | Result |
|--------|--------|
| [2026-07-27 comprehensive gray-box evaluation](2026-07-27-graybox-comprehensive.md) | Full post-update evaluation baseline. |
| [2026-07-30 graph-tool ceiling](2026-07-30-critical-graybox-graph-tool-ceiling.md) | Ceiling evaluation with reproducible task fixtures. |
| [2026-07-31 universal limit](2026-07-31-critical-graybox-universal-limit.md) | Universal-limit evaluation. |
| [2026-07-31 post-fix delta](2026-07-31-critical-graybox-fix-delta.md) | Delta after the scope-resolution fixes. |
| [2026-07-31 scope resolution, scale, fluidity](2026-07-31-critical-graybox-scope-resolution.md) | File-local scope resolution, scale, and fluidity. |

## Multi-language corpora

| Record | Result |
|--------|--------|
| [2026-07-30 multi-language critical evaluation](2026-07-30-graybox-multilang-critical.md) | Six external repositories. |
| [2026-08-01 Flask and multi-language corpora](2026-08-01-graybox-flask-multilang.md) | Flask corpus results. |
| [2026-08-01 Express theoretical ceiling](2026-08-01-graybox-express-theoretical-ceiling.md) | Express ceiling and implementation roadmap; drives the defect-ledger follow-up checklist. |
| [2026-07-31 remaining language coverage](2026-07-31-remaining-language-coverage.md) | Seven-language direct-call closure. |

## Typed facts and receiver resolution

| Record | Result |
|--------|--------|
| [2026-07-31 P02 typed-fact held-out](2026-07-31-p02-typed-fact-heldout.md) | Held-out receiver comparison. |
| [2026-07-31 Q02-C persistent type facts](2026-07-31-q02c-persistent-type-facts.md) | Persistent type facts and affected-key re-join. |
| [2026-07-31 Q02-D JavaScript structural owners](2026-07-31-q02d-js-structural-owners.md) | JS structural receiver owners. |
| [2026-07-31 Q02-D language volume and C++ hold](2026-07-31-q02d-language-volume-and-cpp-hold.md) | Per-language volume; C++ experiment held. |

## Performance and caching

| Record | Result |
|--------|--------|
| [2026-07-31 scan hot path optimization](2026-07-31-scan-hot-path-optimization.md) | One quadratic, two redundancies, and a determinism bug. |
| [2026-08-01 retrieval and shared-path optimization](2026-08-01-retrieval-and-shared-path-optimization.md) | Retrieval, the shared tree-sitter path, and a parallelism result that failed. |
| [2026-07-31 caching and compression prototypes](2026-07-31-caching-and-compression-prototypes.md) | Three candidates, two falsified. |

## Task fixtures

Reproducible task sets and polyglot scope fixtures referenced by the records above:

- [`2026-07-30-express-graybox-tasks.json`](2026-07-30-express-graybox-tasks.json)
- [`2026-07-30-flask-graybox-tasks.json`](2026-07-30-flask-graybox-tasks.json)
- [`2026-07-30-ripgrep-graybox-tasks.json`](2026-07-30-ripgrep-graybox-tasks.json)
- `fixtures/flask_suite.json`, `fixtures/polyglot-scope-2026-07-31/` (seven-language scope corpus with `ORACLE.md`)
