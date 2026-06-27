# Context Graph Benchmark

This folder is a small, repeatable lab for comparing context storage formats:

- plain Markdown files
- SQLite tables
- graph JSON adjacency
- compact graph packets
- hybrid graph-plus-source snippets

The goal is not to prove a universal winner. It gives a grounded baseline for
this question:

> Is a stored context graph more effective than plain English Markdown for LLM
> context?

The benchmark separates storage from the final LLM-facing packet. It measures:

- retrieval latency
- token pressure
- expected evidence recall
- expected edge recall
- composite score

The answer key is stored separately in `data/tasks.json`. Retrieval strategies
receive only `data/seed_context.json`, which contains corpus nodes and edges.

## Run

Run the main suite:

```powershell
python benchmarks\context_graph\run_all.py
```

The current architecture recommendation is summarized in:

- `benchmarks/context_graph/architecture_blueprint.md`

Individual runs:

```powershell
python benchmarks\context_graph\run_benchmark.py
```

Outputs are written to:

- `benchmarks/context_graph/out/context_graph.db`
- `benchmarks/context_graph/out/graph.json`
- `benchmarks/context_graph/out/results.csv`
- `benchmarks/context_graph/out/results.md`

For pure format overhead:

```powershell
python benchmarks\context_graph\format_benchmark.py
```

Additional outputs:

- `benchmarks/context_graph/out/format_results.csv`
- `benchmarks/context_graph/out/format_results.md`

`format_benchmark.py` uses `tiktoken` with `cl100k_base` when available. If
`tiktoken` is not installed, the output explicitly labels the tokenizer as an
approximation.

Optional live API latency:

```powershell
$env:RUN_OPENAI_LATENCY="1"
$env:OPENAI_LATENCY_MODEL="gpt-4o-mini"
python benchmarks\context_graph\format_benchmark.py
```

This measures streaming time-to-first-token and total response time only when
the `openai` package and `OPENAI_API_KEY` are available.

## Protocol Runner

For the fuller baseline protocol:

```powershell
python benchmarks\context_graph\protocol_benchmark.py
```

The protocol is controlled by:

- `benchmark_manifest.json`

It adds:

- multiple corpus sizes and densities
- noisy documents
- direct lookup, reverse lookup, path, blast-radius, summary, and negative tasks
- keyword, BM25-style, graph-hop, hybrid, full-dump, and hierarchical-summary baselines
- saved context packets for every corpus/task/strategy
- saved prompt records for later LLM runs
- storage-size, build-time, render-time, retrieval-latency, recall, path-recall, and irrelevant-context metrics

Outputs:

- `benchmarks/context_graph/out/protocol/protocol_results.csv`
- `benchmarks/context_graph/out/protocol/protocol_summary.md`
- `benchmarks/context_graph/out/protocol/packets/`
- `benchmarks/context_graph/out/protocol/saved_prompts.jsonl`

Optional model-answer evaluation:

```powershell
$env:RUN_OPENAI_ANSWER_EVAL="1"
$env:OPENAI_ANSWER_MODEL="gpt-4o-mini"
python benchmarks\context_graph\llm_answer_benchmark.py
```

This consumes `saved_prompts.jsonl`, streams model answers, records TTFT and
total latency, compares answer node IDs against the generated answer key, and
flags node IDs that appear in the answer but not in the provided packet. It is
intentionally separate from retrieval scoring so a model cannot influence the
retrieval baseline.

For the stricter schema-bearing reasoning test:

```powershell
python benchmarks\context_graph\model_reasoning_benchmark.py
```

Without API env vars, this writes:

- `benchmarks/context_graph/out/protocol/model_reasoning_prompts.jsonl`

To run live scoring:

```powershell
$env:RUN_OPENAI_REASONING_EVAL="1"
$env:OPENAI_REASONING_MODEL="gpt-4o-mini"
python benchmarks\context_graph\model_reasoning_benchmark.py
```

This compares `lowlevel_schema`, `sql_schema`, and `hybrid_schema` using strict
JSON answers with node and edge recall.

The first live-model battery is specified in:

- `benchmarks/context_graph/model_answer_test_plan.md`

Before spending API calls, summarize the frozen prompt set:

```powershell
python benchmarks\context_graph\prompt_preflight.py
```

Optional cost estimates are explicit inputs because provider prices change:

```powershell
python benchmarks\context_graph\prompt_preflight.py --input-price-per-1m 0.15 --output-price-per-1m 0.60
```

Outputs:

- `benchmarks/context_graph/out/protocol/prompt_preflight.csv`
- `benchmarks/context_graph/out/protocol/prompt_preflight.md`

## Min-Max Analysis

After running `format_benchmark.py` and `protocol_benchmark.py`, generate the
optimization report:

```powershell
python benchmarks\context_graph\minmax_analysis.py
```

Output:

- `benchmarks/context_graph/out/protocol/minmax_report.md`

This report computes format overhead, estimated input cost, the smallest
passing retrieval strategy per corpus, and the Pareto frontier.

## Binary / Bitmap Storage

To measure the conceptual machine-storage floor:

```powershell
python benchmarks\context_graph\bitpack_benchmark.py
```

Output:

- `benchmarks/context_graph/out/bitpack/bitpack_results.csv`
- `benchmarks/context_graph/out/bitpack/bitpack_results.md`

This is not a direct prompt benchmark. Binary, CSR, and bitmap forms must be
decoded into an LLM-facing packet unless the inference runtime supports custom
binary, embedding, or KV-cache memory.

## Interpretability Overhead

To measure how much schema/instruction overhead compact packets need:

```powershell
python benchmarks\context_graph\interpretability_benchmark.py
```

Output:

- `benchmarks/context_graph/out/protocol/interpretability_results.csv`
- `benchmarks/context_graph/out/protocol/interpretability_summary.md`

This reports both uncached prompt tokens and cached prompt tokens, because a
stable packet schema can be placed in a cached prefix.

## Source Route Ablation

To compare document/wiki/database parsing against code/graph parsing:

```powershell
python benchmarks\context_graph\source_route_benchmark.py
```

Outputs:

- `benchmarks/context_graph/out/protocol/source_routes/source_route_results.csv`
- `benchmarks/context_graph/out/protocol/source_routes/source_route_summary.md`

This normalizes every route into the same node/edge/document IR before packet
rendering. The current routes are:

- `code_graph_direct`
- `wiki_with_edges`
- `wiki_prose_relations`
- `wiki_noisy_prose`
- `wiki_plain_no_edges`
- `sqlite_rows`

## Constraint Context

To test whether project standards and LLM values should be stored as context:

```powershell
python benchmarks\context_graph\constraint_context_benchmark.py
```

Outputs:

- `benchmarks/context_graph/out/protocol/constraints/constraint_context_results.csv`
- `benchmarks/context_graph/out/protocol/constraints/constraint_context_summary.md`
- `benchmarks/context_graph/out/protocol/constraints/policy_records.json`

Design note:

- `benchmarks/context_graph/constraint_context_design.md`

The short version: store standards as scoped policy records, not as an always-on
Markdown dump.

## Adaptive Policy Report

To convert benchmark outputs into a concrete route/packet/policy choice:

```powershell
python benchmarks\context_graph\adaptive_policy_report.py
```

Output:

- `benchmarks/context_graph/out/protocol/adaptive_policy_report.md`

This report gates source routes by extraction recall/precision, picks the
cheapest passing packet shape, and chooses the scoped constraint strategy.

## Final Packet Composition

To estimate the actual LLM-facing packet after adding scoped policies:

```powershell
python benchmarks\context_graph\final_packet_benchmark.py
```

Output:

- `benchmarks/context_graph/out/protocol/final_packets/final_packet_summary.md`
- `benchmarks/context_graph/out/protocol/final_packets/final_packet_results.csv`

## Packet Round-Trip Validation

To verify generated packets are mechanically parseable:

```powershell
python benchmarks\context_graph\packet_roundtrip_validator.py
```

Output:

- `benchmarks/context_graph/out/protocol/packet_roundtrip_results.csv`
- `benchmarks/context_graph/out/protocol/packet_roundtrip_results.md`

This does not measure model reasoning. It proves the compressed packet did not
lose graph evidence before live model testing.

## External Repo Fixtures

After the synthetic benchmark is stable, use pinned public repos as real-world
fixtures:

```powershell
python benchmarks\context_graph\prep_external_repos.py --dry-run
python benchmarks\context_graph\prep_external_repos.py --only python_click
```

The repo set is defined in:

- `benchmarks/context_graph/external_repos.json`

The first real clone writes:

- `benchmarks/context_graph/external_repos.lock.json`

The lockfile records the resolved commit SHA for every cloned repo. Treat that
file as the source of truth for reproducible real-repo runs. Do not benchmark
against a moving branch without either regenerating the lockfile intentionally
or recording the branch, date, and resolved commit.

Suggested fixture tiers:

- tiny/small Python repos first, to validate extraction and packet rendering
- medium Python/Rust repos next, to expose real dependency paths
- large TypeScript monorepos last, to stress retrieval selectivity and token
  pressure

## Local Locus Fixture

For this workstation, `locus` is the main real-world fixture. It compares native
graphgraph against Graphify import on the same task file:

```powershell
$env:PYTHONPATH="src"
python benchmarks\context_graph\locus_benchmark.py
```

Optional controls:

```powershell
$env:LOCUS_REPO="C:\Users\dcarn\aiprojects\locus"
$env:LOCUS_REBUILD="1"
$env:LOCUS_FRONTEND="tree_sitter"
$env:LOCUS_MAX_NODES="1200"
```

Outputs:

- `benchmarks/context_graph/out/locus/locus_eval.csv`
- `benchmarks/context_graph/out/locus/locus_summary.md`
- `benchmarks/context_graph/out/locus/native_vs_graphify.json`

The Locus runner enforces native graphgraph recall/token thresholds by default.
Set `LOCUS_ENFORCE_THRESHOLDS=0` to generate reports without failing the
process.

## Local Project Smoke Fixture

Use this to catch scanner regressions across non-Locus project shapes: Python,
TypeScript, docs-heavy repos, and mixed web/Python repos.

```powershell
$env:LOCAL_PROJECT_FRONTEND="tree_sitter"
$env:LOCAL_PROJECT_MAX_NODES="800"
uv run --with tree-sitter --with tree-sitter-language-pack python benchmarks\context_graph\local_project_smoke.py
```

Optional controls:

```powershell
$env:AIPROJECTS_ROOT="C:\Users\dcarn\aiprojects"
$env:LOCAL_PROJECTS="activation,chess,contextminer,ebaypostingautomation,slotmachine,tuya-ble-scanner"
```

Outputs:

- `benchmarks/context_graph/out/local_projects/local_project_smoke.csv`
- `benchmarks/context_graph/out/local_projects/local_project_smoke.md`
- `benchmarks/context_graph/out/local_projects/<project>.json`

Then run the retrieval regression tasks over those saved graphs:

```powershell
uv run --with tree-sitter --with tree-sitter-language-pack python benchmarks\context_graph\local_project_eval.py
```

Outputs:

- `benchmarks/context_graph/out/local_projects/local_project_eval.csv`
- `benchmarks/context_graph/out/local_projects/local_project_eval.md`

## Cross-Repo Anchor Stress

Use this harsher fixed-policy benchmark to test anchor/search generalization
across local projects and cloned resources. It generates exact-node tasks from
the scanned graphs, holds the production policy fixed, and reports recall,
tokens per hit, and over-retrieval/noise.

```powershell
$env:CROSS_REPO_MAX_NODES="700"
$env:CROSS_REPO_REUSE_GRAPHS="0"
python benchmarks\context_graph\cross_repo_anchor_stress.py
```

Optional project override:

```powershell
$env:CROSS_REPO_PATHS="C:\Users\dcarn\aiprojects\graphgraph;C:\Users\dcarn\aiprojects\resources\requests"
```

Outputs:

- `benchmarks/context_graph/out/cross_repo_anchor/cross_repo_anchor_stress.csv`
- `benchmarks/context_graph/out/cross_repo_anchor/cross_repo_anchor_stress.md`
- `benchmarks/context_graph/out/cross_repo_anchor/graphs/<project>.json`

## Interpretation

High recall with low token pressure is the useful region.

Plain Markdown is expected to do well for broad narrative context. Graph forms
should do better when the question depends on dependency paths, blast radius,
or multi-hop relationships. The hybrid strategy is often the practical target:
store graph-structured context, then render a compact Markdown packet for the
LLM.

## Anti-Cheating Rules

- Retrieval code must not read `data/tasks.json` except inside the evaluator.
- External repo runs must use `external_repos.lock.json` commit SHAs, not a
  floating branch head.
- Live model comparisons must reuse saved prompt records; do not tune prompts
  per format after seeing answers.
- Generated context stores must not contain expected nodes or expected edges.
- Node recall requires the node id or label to appear in retrieved context.
- Edge recall requires relation evidence, not merely the two endpoint nodes.
- The benchmark is deterministic and local; no model is asked to judge itself.
- Format-overhead tests compare identical generated graphs at multiple sizes,
  not a single three-node example.
- Protocol tasks are generated after the corpus, and expected answers are only
  used by the evaluator.
- Every rendered packet is saved so a suspicious score can be inspected.
