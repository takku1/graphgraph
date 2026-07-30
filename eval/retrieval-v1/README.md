# Retrieval policy evaluation v1

This is the frozen evaluation boundary for retrieval-policy work beginning with
P01. The suite measures GraphGraph, but GraphGraph output never supplies an
answer key. Every expectation is tied to direct source inspection at a pinned
repository commit; [`task-schema.json`](task-schema.json) describes the task
contract and `load_eval_manifest` enforces the stronger cross-file invariants.

## Frozen split

| Split | Repository | Language | Tasks | Purpose |
| --- | --- | --- | ---: | --- |
| train | `takku1/graphgraph@44a84ed` | Python | 6 | policy development only |
| calibration | `pallets/flask@954f568` | Python | 6 | thresholds and calibration only |
| test | `expressjs/express@18e5985` | JavaScript | 5 | held-out transfer |
| test | `BurntSushi/ripgrep@227381d` | Rust | 7 | held-out transfer |

The repository is the split unit: no repository occurs in more than one split.
The 24 tasks include lexical-disjoint conceptual questions, compound facets,
ambiguous names, qualified members, multi-hop questions, documentation,
cross-language receiver oracles, and one independently verified negative per
repository. `lexical_disjoint` is executable: the loader rejects any normalized
query token shared with an expected identifier.

Protocol versions are deliberately separate:

- schema: `graphgraph.eval.v1`;
- task/qrel resolver: `node-qrel-v3-facets`;
- reference tokenizers: `cl100k_base+o200k_base@tiktoken-0.13.0`;
- deterministic token proxy: `piece-punctuation-ls-v1`;
- oracle contract: `independent-source-receipt-v1`.

Changing any of these requires a new suite version, not an in-place rewrite of
the baseline.

## Metrics and comparisons

`graphgraph eval --report` emits raw task results plus overall, query-class,
split, and stratum reports. Each report includes node/edge recall, first-hit
MRR, NDCG@5/10, facet completeness, token and cold/warm query distributions,
Brier/ECE when labels exist, abstention utility, and explicit failing task IDs.
A weak stratum therefore cannot disappear inside the overall mean.

`graphgraph eval --baseline-results incumbent.json` performs a deterministic
paired percentile bootstrap by stable task ID. Promotion requires the lower
confidence bound to meet `--minimum-effect`; a merely positive mean delta is
`inconclusive`. The default is 10,000 resamples with seed 1337.

For a complete four-project run, use `scripts/run_eval_suite.py` and provide one
`--graph PROJECT=PATH` and `--project-root PROJECT=PATH` per manifest project.
The runner verifies every checkout commit. `--repeat 2` rejects any non-latency
result drift before it prints a baseline.

## Frozen structural baseline — 2026-07-30

The deterministic comparison baseline uses `source_mode=off`; optional source
indexes remain a separately measured production treatment. Two complete
repetitions matched exactly on every non-latency result.

| Slice | Node recall | MRR | NDCG@10 | Facet completeness |
| --- | ---: | ---: | ---: | ---: |
| Overall (20 scored + 4 negatives) | 0.695833 | 0.424954 | 0.299862 | 0.489583 |
| Reverse lookup | 1.000000 | — | — | — |
| Subsystem summary | 0.319444 | — | — | — |
| Multi-hop path | 0.500000 | — | — | — |
| Lexical-disjoint | 0.152778 | — | 0.000000 | — |
| Receiver oracle | 0.777778 | — | — | — |
| Qualified member | 1.000000 | — | — | — |
| Held-out test repositories | 0.800000 | — | — | — |

Overall Brier is `0.160045`, ECE is `0.152075`, and risk utility at the frozen
0.5 abstention threshold is `0.166667` across all 24 tasks. All four negative
controls abstain correctly (`1.0` utility). Seven tasks are deliberately red at
the incumbent: `EXPRESS-TEST-001`, `FLASK-CAL-003`, `GG-TRAIN-001`,
`GG-TRAIN-003`, `GG-TRAIN-004`, `GG-TRAIN-005`, and `RIPGREP-TEST-003`.

Packet-token proxy samples are
`[68, 79, 80, 94, 101, 112, 113, 178, 178, 190, 230, 243, 360, 507, 636,
640, 706, 878, 1029, 1106, 1123, 1358, 1363, 1527]`: mean `537.458333`,
p50 `301.5`, p95 `1362.25`.

Latency environment: Windows 11 Pro 10.0.26200, Intel i7-11850H (8 cores / 16
logical processors), 31.2 GiB RAM, Python 3.11.15, uv 0.11.24. Timers exclude
graph loading/runtime construction. First-query samples per project are
`[198.5221, 911.2847, 1418.9182, 1447.7763] ms` (p50 `1165.1015`, p95
`1443.4476`). Reused-runtime samples are `[78.7302, 117.7108, 229.3162,
236.8248, 284.3036, 352.1985, 360.8328, 389.2769, 435.1512, 473.6830,
504.1785, 527.9319, 643.3856, 700.9733, 923.0875, 962.1217, 1295.2973,
1359.5333, 1440.5344, 1509.4284] ms` (p50 `488.9307`, p95 `1443.9791`).

Production `source_mode=auto` is not frozen as the comparison oracle yet: two
identical process runs changed overall MRR (`0.418467` to `0.418358`) and token
p95 (`1447.2` to `1501.55`). That nondeterminism is retained as an explicit
P08 source-planning/calibration defect rather than averaged away.
