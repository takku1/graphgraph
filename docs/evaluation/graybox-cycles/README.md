# Gray-Box Measurement Ledger

Compact, current authority for the dated gray-box campaign. Raw historical run
narratives were retired after their durable claims moved here, into architecture
ADRs, executable tests/benchmarks, the defect ledger, or the research registry.
The original tracked narratives remain recoverable from Git history.

This is evidence, not a task list. Open work lives only in
[`docs/open-work.md`](../../open-work.md). A value below is valid only for its
named corpus, revision, and date; current runtime status must be measured again.

## Current raw receipts

| Receipt | Durable result |
|---|---|
| [2026-08-08 packed exact-relation cold path](2026-08-08-packed-relation-cold-path.md) | Embedded hash/CSR/CSC indexes replaced whole-view object materialization: 57.08 → 3.81 ms p50 in-process on the self graph. |
| [2026-08-07 external gray-box cycle](2026-08-07-graybox-cycle.md) | Five-repository CLI audit: 1,297/1,297 extraction recall; node-id collision fixed to 441/441 exact Flask definitions; identified fixed-confidence, Go receiver, lexical-semantic, packet-declaration, and update-scaling defects. |

These newest receipts are retained because they are not yet represented wholly
by a later campaign. Their derived tasks still belong in `docs/open-work.md`.

## Instrument and representation measurements

| Historical receipt | Durable verdict | Current owner |
|---|---|---|
| `2026-07-30-token-proxy-recalibration` | The old word-count proxy had 47.2% cross-format spread. The replacement measured 2.78% mean error; all older proxy-denominated comparisons are invalid. | `packets/metrics.py`, token calibration benchmark, context-packet ADRs |
| `2026-07-31-caching-and-compression-prototypes` | A cache key containing GraphGraph's generated state self-invalidated; excluding generated artifacts restored reuse. Two compression candidates failed their gates. | `services/cache_identity.py`, storage/application-service ADRs and cache tests |
| `2026-08-02-agent-cycle-efficiency-quality-tracker` | Established the acceptance workstream scorecard; live status subsequently moved to `docs/open-work.md`. | acceptance suite and open-work receipts |
| `2026-08-05-flask-corpus-benchmark-vs-peers` | SQL packet cost was documented backwards and fixed; isolated lexical anchors and missing incremental timing were found. Unsupported-anchor pruning later preserved recall/MRR and improved Express NDCG@10 0.376 → 0.438. | packet contracts, retrieval quality tests, information-retrieval ADR |

## Influence-field experiment

The three-step campaign (`2026-07-29-influence-field-coupling`,
`2026-07-30-recoupled-cover-verdicts`, and
`2026-07-30-coupling-has-no-production-leverage`) ended in one terminal negative
result: symmetric coupling improved a field-ranked selection by +0.066, then
changed production recall/MRR not at all and NDCG@10 by only +0.0021 at 11.9×
latency. The candidate is measured but not promotable. The executable research
registry preserves the hypothesis/experiment chain.

## Retrieval and compiler findings

| Historical receipt | Durable verdict | Current owner |
|---|---|---|
| `2026-08-05-tb07-preflight-veto-fix-falsified` | Lexical and raw-cosine cutoff fixes rescued an adversarial near miss with the true answer; no threshold was safe. | abstention red controls; compound-facet/ranking work remains in open-work |
| `2026-08-01-retrieval-and-shared-path-optimization` | Promoted retrieval/shared Tree-sitter work; a parallelism candidate failed. | retrieval and `SourceIR` tests/ADRs |
| `2026-08-05-graybox-cycle` | Single-file JavaScript update deleted cross-file external call edges; retain-by-owning-file logic was fixed. Also found probe-casing and orient-subdirectory gaps. | incremental scanner regression tests and defect ledger |

## Static-analysis findings

| Historical receipt | Durable verdict | Current owner |
|---|---|---|
| `2026-07-31-p02-typed-fact-heldout` | Held-out receiver-type comparison established the typed-fact direction. | receiver-resolution tests and static-analysis ADRs |
| `2026-07-31-q02c-persistent-type-facts` | Persistent type facts and affected-key rejoin survived the stage gate. | frontend IR and incremental scanner tests |
| `2026-07-31-q02d-js-structural-owners` | JavaScript structural receiver ownership closed the measured gap. | JS frontend tests |
| `2026-07-31-q02d-language-volume-and-cpp-hold` | Recorded per-language volume; the C++ candidate was held rather than promoted. | frontend capability contracts |
| `2026-07-31-remaining-language-coverage` | Seven-language direct-call closure was measured against the polyglot oracle. | static-analysis tests and fixture below |
| `2026-07-31-scan-hot-path-optimization` | Removed one quadratic path, two redundant computations, and a determinism defect. | scanner performance/regression tests |

## Historical ceiling campaigns

The dated ceiling series (`2026-07-27-graybox-comprehensive`,
`2026-07-30-critical-graybox-graph-tool-ceiling`,
`2026-07-30-graybox-multilang-critical`,
`2026-07-31-critical-graybox-universal-limit`,
`2026-07-31-critical-graybox-fix-delta`,
`2026-07-31-critical-graybox-scope-resolution`,
`2026-08-01-graybox-flask-multilang`, and
`2026-08-01-graybox-express-theoretical-ceiling`) established successive
baselines and fix deltas. Terminal defects and current measurements were
promoted to `defect-ledger.md`, `empirical-evaluation.md`, architecture
invariants, and regression tests; the intermediate narratives no longer carry
independent authority.

## Executable corpora

These remain the reproducible inputs behind the retired narratives:

- [`2026-07-30-express-graybox-tasks.json`](2026-07-30-express-graybox-tasks.json)
- [`2026-07-30-flask-graybox-tasks.json`](2026-07-30-flask-graybox-tasks.json)
- [`2026-07-30-ripgrep-graybox-tasks.json`](2026-07-30-ripgrep-graybox-tasks.json)
- `fixtures/flask_suite.json`
- [`fixtures/polyglot-scope-2026-07-31/ORACLE.md`](fixtures/polyglot-scope-2026-07-31/ORACLE.md) and its seven-language source corpus
