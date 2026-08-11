# graphgraph

A native context graph engine for LLM coding agents: scan a codebase into a
compact graph, then retrieve exactly the nodes/edges a query needs as a
token-efficient packet — instead of pasting whole files into context.

JSON and prose are high-level languages for context. `graphgraph` aims for
the LLM equivalent of a compact instruction stream: stable node symbols,
relation opcodes, local adjacency, and only the text a query actually needs.

The advanced platform follows the same rule: memory, time, federation,
semantic fallback, runtime traces, inference, and repair context compile into
the native graph IR and bounded packet pipeline. They are not separate graph
products hidden behind one CLI. See [LLM-native platform](docs/research/llm-native-platform.md).

## What it does

- **Scans** Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby, PHP, Kotlin,
  Scala, and Swift into a symbol-level graph (functions/classes/structs +
  calls/imports/contains edges), plus Markdown/RST/HTML doc structure.
- **Retrieves** query-scoped packets via anchor discovery, personalized
  PageRank, and continuous-budget planning — sized for the query, not the
  whole repo.
- **Updates incrementally** at three granularities: full rescan (hash-diffed
  against a manifest), targeted `update`/`remove` for files you already know
  changed (no directory walk, no hashing anything else — see
  [Incremental updates](#incremental-updates)), and a fine-grained
  operation-logged API (`add_node`/`expire_edge`/`expire_node`/`merge_node`)
  for single-mutation edits.
- **Compiles persisted multi-language CPG evidence** into the same graph IR:
  bounded reads/writes/control/type/field/return relations with per-file cache
  invalidation and exact accepted/duplicate/rejected/truncated receipts.
- **Plans auxiliary sources at query time**: scoped memory, temporal episodes,
  runtime traces, federated repository slices, and semantic seed IDs become
  normal graph evidence before packet selection.
- **Interoperates** with Graphify, code-review-graph, CSV, and other graph
  sources via `graphgraph ingest` — normalized into the same retrieval and
  packet pipeline. Nothing outside `.graphgraph/` is read by default; external
  graphs are only touched when you explicitly pass them to `ingest` or a
  graph-path argument.

## Design bar

Measured against five axes, in priority order:

1. **Context quality** — retrieve the right nodes, edges, paths, and facts.
2. **Token economy** — the smallest packet the model can still interpret.
3. **Interpretation accuracy** — prove the model answers correctly *from the
   packet*, not just that the packet is short.
4. **Update cost** — refresh changed regions, not the whole graph.
5. **Latency** — fast enough for a live agent edit/test loop.

## Install

Three steps: install the package, register it with your assistant, verify.

```powershell
# 1. Install (uv recommended; if 'graphgraph' isn't found after, run: uv tool update-shell)
uv tool install .
# alternatives: pipx install .   |   pip install -e .  (dev editable)

# 2. Register the skill + MCP server (global, for your user profile)
graphgraph install
# or scope to this repo instead: graphgraph install --project
# or target one client: --platform {codex, claude, cursor, gemini, antigravity, claude-desktop}

# 3. Verify
graphgraph doctor
```

`doctor` reports MCP registration status per client plus environment health,
and prints the exact `graphgraph install` command to fix anything it finds
"not configured."

<details>
<summary>Run without installing, manual per-client MCP config, Codex plugin details</summary>

### Run without installing (`uv run`, npx-style)

```powershell
uv run --project <path-to-graphgraph> graphgraph scan --directory .
uv run --project <path-to-graphgraph> graphgraph-mcp
```

### Manual MCP configuration

`graphgraph install` covers Claude Code, Claude Desktop, Codex, Cursor, and
Gemini/Antigravity. Hand-edit only if you need a client it doesn't cover yet.

**Cursor** (`Settings > Features > MCP > Add New MCP Server`) — name
`graphgraph`, type `stdio`:
- Command `uv`, args `run --project <path-to-graphgraph> graphgraph-mcp`, or
- Command `<path-to-graphgraph>/.venv/Scripts/graphgraph-mcp.exe` directly.

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "graphgraph": { "command": "uv", "args": ["run", "--project", "<path-to-graphgraph>", "graphgraph-mcp"] }
  }
}
```

**Codex plugin** — `graphgraph` ships a repo-local plugin at
`plugins/graphgraph` (plugin manifest, skill, portable MCP config, marketplace
entry). Generate/refresh it with:
```powershell
graphgraph install --project --platform codex
graphgraph artifacts --check
codex plugin marketplace add <path-to-graphgraph>
codex plugin add graphgraph@graphgraph-local
```
The packaged files under `src/graphgraph/assets` plus the typed generators in
`graphgraph.distribution` are canonical. Maintainers regenerate tracked
`.agents` and `plugins/graphgraph` copies with `graphgraph artifacts`; CI runs
`graphgraph artifacts --check`. Do not hand-edit those generated copies.
Then start a Codex thread and ask a structural codebase question, or invoke
`@graphgraph` directly. To pin the plugin to an uninstalled dev checkout
instead of the installed console script, run
`python scripts\configure_codex_plugin.py --repo-root <checkout>`.

</details>

## Quickstart

```powershell
# Build the graph (incremental by default: hash-diffs against a manifest)
graphgraph scan --directory . --depth symbols --output .graphgraph/graph.gg

# Ask a question — discovers anchors and renders a packet in one step
graphgraph context "what is the blast radius of auth changes" --show-stats

# Exact symbol already known — 1-hop tuple IR without planner/packet expansion
graphgraph relations authenticate --direction callers

# Same lookup when repository freshness matters (fused Git delta refresh)
graphgraph relations authenticate --direction callers --sync git
```

`context` and `query` route natural-language intent automatically with a
deterministic, no-I/O classifier. Explicit `--query-class` remains available
for repeatable benchmarks and callers that already know the policy they need.
For exact one-hop caller/callee maps, `relations` (MCP: `query_relations`) is
the low-level lane: compact tuple rows, tests opt-in, and separate receipts for
result truncation, call-topology coverage, and freshness. The default keeps
freshness unchecked to preserve the hot path; add `--sync git` (MCP:
`"sync":"git"`) to fuse an incremental Git-delta refresh into the same call.
Micro IR v2 is self-decoding: `tk` describes target tuple `t`, `k` describes
neighbor tuples `n`, `r` contains receipts, and optional `a` values are stable
next-action opcodes. `answer_complete` is true only when the returned rows are
untruncated, topology telemetry is complete, and freshness was checked.

Scans honor repository and nested `.gitignore`/`.ignore` rules (including
negation), and exclude secret-bearing environment files plus local agent/MCP
configuration by default. Compact `gg` packets include `@path:line` and a
definition-line signature when the scanner can extract one.

Before an initial build, inspect the repository's ignore rules and large or
generated paths, then pass project-specific exclusions with `--exclude` (MCP:
`exclude_dirs`). CLI scans emit timed discovery/hash/edge/symbol/doc/concept/
validation/save phase events to stderr and finish with an explicit receipt for
ignore files, pruned directories, frontend/fallbacks, validation, and
truncation. Ignore-matched directories are pruned before descent rather than
walked file by file. MCP `build_graph` returns the same frontend and exclusion
receipt in JSON. MCP `describe_frontends` reports `ready_languages` and
`unavailable_languages`; aggregate `tree_sitter.available=true` means at least
one grammar works, not that every advertised language grammar is installed.

Broad natural-language `subsystem_summary`/`blast_radius` queries use a
48-node orientation cap when anchor discovery cannot identify a targeted
symbol. Exact-symbol queries retain the 120-node recall budget; tests remain
connected support evidence unless the query is materially test-focused.

## Incremental updates

Three ways to keep the graph current, cheapest first:

| You know... | Use | Cost |
|---|---|---|
| One exact fact changed (an edge is stale, merge two nodes) | `add_node`/`expire_edge`/`expire_node`/`merge_node` (Python API, `graph/operations.py`) | O(1) |
| Exactly which files you just edited/deleted | `graphgraph update --files <path...>` / `graphgraph remove --files <path...>` | O(files named) |
| Nothing — just rescan and let it figure out what changed | `graphgraph scan` (hash-diffed against the manifest) | O(repo size) |

`update`/`remove` skip the directory walk and skip hashing anything you
didn't name — every other tracked file is trusted from the manifest.
Measured on a 41k-node/87k-edge real-world monorepo: a single-file `update`
takes ~2s versus ~16s for a full incremental rescan of the same repo. Both
require a prior `scan` (they splice into an existing graph) and fall back to
a full rebuild automatically if the manifest is missing or stale.

```powershell
# After editing these two files:
graphgraph update --files src/auth/session.py src/auth/tokens.py --depth symbols

# After deleting/renaming a file away:
graphgraph remove --files src/auth/legacy.py --depth symbols
```

MCP equivalents: `update_graph_files` / `remove_graph_files`, same shape as
`build_graph`. See `docs/incremental-update-instruction-set.md` for the full
design (profiling data, prior-art survey, correctness notes).

For an MCP agent that will query immediately after editing, `query_context`
is the lower-latency fused path. Pass `changed_paths` and/or `deleted_paths`
with the query; GraphGraph performs one O(named paths) splice, persists it,
and queries that exact in-memory graph without a second MCP call or disk
reload. Omitted extraction settings inherit from the saved graph.

For unrestricted read-only questions, use the uniform facade from any surface:

```python
import graphgraph

result = graphgraph.query("what calls Router::handle?")
```

```powershell
graphgraph query "what calls Router::handle?"
```

MCP exposes the same operation as `query`. Its deterministic compiler routes to
`relations`, `select`, `search`, `status`, or facet-aware `context` only when the
request is losslessly representable, returns the chosen plan, and never infers
a mutation or silently builds a missing graph. Expert operations remain public
for callers that already know the exact contract they need.

```json
{"query":"what should change next?","changed_paths":["src/auth/session.py"],"deleted_paths":["src/auth/legacy.py"]}
```

When the caller did not retain the exact edit list, use `sync: "git"` (MCP) or
`--sync git` (CLI). Git supplies only candidate paths; GraphGraph hashes those
against the manifest, reconciles paths newly covered by ignore rules, performs
one splice if anything is stale, and queries the refreshed graph. Repeating the
same call without another edit is a no-op.

```powershell
graphgraph context "what should change next?" --sync git --show-stats
```

See [the graph-tool usage audit](docs/evaluation/external-tool-interoperability-audit.md) for the
project-loop comparison, selection math, and capability roadmap.

## Command reference

| Command | Purpose |
|---|---|
| `scan` | Build/refresh the graph from a directory (hash-diffed incremental by default). |
| `update` | Re-extract only the named files; splice into the existing graph. |
| `remove` | Drop the named files from the existing graph. |
| `context` | One-step: ensure a graph exists, discover anchors, render a packet. |
| `query` | Discover anchors and render a packet from an existing graph only. |
| `relations` | Exact one-hop callers/callees as self-decoding micro IR; optionally `--sync git`. |
| `final` | Render a packet from confirmed node IDs (no anchor discovery). |
| `snippets` | Bounded source excerpts for selected node IDs/labels/paths. |
| `status` | Graph validity, code/doc balance, package metadata, optional runtime probes. |
| `profile` | Graph shape and dynamic budget candidates. |
| `validate` / `validate-graph` | Validate a rendered packet / a saved graph file. |
| `ingest` | Normalize an external graph (Graphify, CSV, TSV, ...) into `.graphgraph/graph.gg`. |
| `export` | Export the current graph to native binary `.gg`. |
| `compare` | Diff two graph files by size, relation types, and overlap. |
| `eval` | Retrieval recall and token cost against labeled tasks. |
| `ontology` / `traversal` / `frontends` | List relation types / query-class traversal policies / extraction frontend availability. |
| `doctor` | Full environment + MCP registration diagnostic. |
| `cache` | Inspect/clear packet caches or recompute and persist centrality (`--recompute-centrality`). |
| `install` | Register the skill + MCP server for a client. |
| `platform` | Compile evidence/memory/time/federation/trace/repair workflows into native GraphGraph IR and receipts. |

Run `graphgraph <command> --help` for full flags.

### Experimental: project representation

`context`, `query`, and `final` accept `--representation {flat,hybrid}` with
`--representation-budget`. **`flat` is the default and the only supported
setting.**

`hybrid` compiles the research candidate `C1-HYBRID-RESERVE-003`: it reserves a
token budget for an exact query frontier and represents every remaining active
entity through aggregate path cells, emitting a machine-checkable coverage
receipt. It has **not passed any tournament gate** and is not wired into the
MCP surface.

It is also currently degenerate on real graphs. Because influence diffuses
along edge direction and 62.9% of active entities are directed sinks, the far
field receives no mass — a live compile yields `aggregate_mass 0.0`,
`refinements 0`, and a single cover line for 98.8% of the project. See
[the consolidated influence-field measurement](docs/evaluation/graybox-cycles/README.md#influence-field-experiment)
for the measurement and
[the tournament](docs/research/context-system-tournament.md) for the promotion
rules. Use it to reproduce that result, not to get better context.

If a compiled hybrid packet misses its budget, the packet is withheld and the
command degrades to `flat`; the receipt records `status: fallback_flat` with
the observed `proxy_tokens`.

## Diagnostics

```powershell
graphgraph doctor
```

Checks toolchain, Python environment, optional dependencies, compiled graph
data, local runtime probes, optional benchmark credentials, and MCP
integrations.

## Optional external benchmark API keys

Normal scan/update/query/MCP workflows are entirely local — no API key
required. Keys are only needed for the optional external model-answer
benchmarks below, and `graphgraph` reads them from the OS credential store
(via `keyring`) with an environment-variable fallback.

<details>
<summary>Credential setup (Windows Credential Manager / keyring / env vars)</summary>

**Fastest — via Python:**
```powershell
python -c "import keyring; keyring.set_password('OpenAI', 'API_KEY', 'your-openai-api-key')"
python -c "import keyring; keyring.set_password('Gemini', 'API_KEY', 'your-gemini-api-key')"
```

**Via Windows GUI:** Start Menu → Credential Manager → Windows Credentials →
Add a generic credential → address `OpenAI` or `Gemini`, username `API_KEY`,
password your key.

**Fallback env vars**, used if `keyring` isn't installed or nothing is found:
```powershell
$env:OPENAI_API_KEY="your-openai-key"
$env:GEMINI_API_KEY="your-gemini-key"
```

</details>

## Benchmarks & testing

```powershell
python benchmarks\context_graph\run_all.py    # full benchmark suite
graphgraph eval --graph .graphgraph/graph.gg --tasks benchmarks/context_graph/data/locus_tasks.json --max-nodes 40
graphgraph eval --graph .graphgraph/graph.gg --tasks eval/graphgraph-self.json --calibration  # labeled confidence receipt; not a fitted production threshold
graphgraph platform benchmark --config multi-repo-acceptance.json  # enforced multi-repo gates
graphgraph platform acceptance --repo ../locus                     # sealed black-box release floor
graphgraph platform quality                                       # token/recall/precision regression gate
# Set GG_ACCEPT_EXEC=1 to prove recommended commands select real tests.
python -m pytest                              # unit tests
```

The shared console defaults to loopback and uses POST for compiler requests:

```powershell
graphgraph platform serve --port 8765
graphgraph platform serve --host 0.0.0.0 --token $env:GRAPHGRAPH_TOKEN --allow-origin https://client.example
graphgraph platform migrate --directory .graphgraph
```

Remote binds require a token. Platform state uses schema-v2 atomic writes and
cross-process locks; HTTP exposes bounded POST endpoints for query, memory,
episodes, runtime traces, and migrations.

## Import routes

```powershell
graphgraph ingest --input graphify-out/graph.json --output .graphgraph/graph.gg
```

External graph directories are never a default runtime source — only
`ingest` and explicit graph-path arguments read them. Run normal commands
against the resulting native `.graphgraph/graph.gg` afterward. The unified
graph contract is defined in
[graph.schema.json](src/graphgraph/schema/graph.schema.json).

## Documentation

- [`docs/README.md`](docs/README.md) — documentation index; start here
- [`docs/guides/getting-started.md`](docs/guides/getting-started.md) — the default path in six commands
- [`docs/guides/evidence-standards.md`](docs/guides/evidence-standards.md) — the evidence bar this
  project holds itself to; what's settled vs. still a hypothesis
- [`docs/open-work.md`](docs/open-work.md) — the open backlog: every unresolved idea/gap
  found so far, prioritized, with what's already ruled out and why
- [`docs/guides/terminology.md`](docs/guides/terminology.md) — academic ↔ legacy term map and doc conventions

**Architecture** — [`docs/architecture/SYSTEM.md`](docs/architecture/SYSTEM.md) is the L0 map; each
subsystem has a `SYSTEM.md` beneath it.

- [`docs/architecture/system-architecture.md`](docs/architecture/system-architecture.md) — end-to-end narrative
- [`docs/architecture/information-retrieval/confidence-and-routing.md`](docs/architecture/information-retrieval/confidence-and-routing.md) —
  measured grep-vs-graphgraph decision rule, latency breakdown, score-gap confidence signal
- [`docs/architecture/runtime-context-model.md`](docs/architecture/runtime-context-model.md) — runtime context model
- [`docs/architecture/storage/incremental-update-protocol.md`](docs/architecture/storage/incremental-update-protocol.md) —
  incremental update primitives, profiling, prior art
- [`docs/architecture/intermediate-representation/relation-ontology.md`](docs/architecture/intermediate-representation/relation-ontology.md) —
  edge types and traversal weights; see also interpretation layer and schema alignment alongside it
- [`docs/architecture/static-analysis/language-frontend-ir.md`](docs/architecture/static-analysis/language-frontend-ir.md) —
  extraction frontends (regex vs. tree-sitter)
- [`docs/architecture/package-structure.md`](docs/architecture/package-structure.md) — repo layout
- [`docs/guides/integration-interfaces.md`](docs/guides/integration-interfaces.md) — external graph interop

**Evaluation**

- [`docs/evaluation/empirical-evaluation.md`](docs/evaluation/empirical-evaluation.md) — benchmark results
- [`docs/evaluation/graybox-cycles/`](docs/evaluation/graybox-cycles/README.md) — dated gray-box evidence records
- [`docs/evaluation/defect-ledger.md`](docs/evaluation/defect-ledger.md) — confirmed defects and resolutions

**Research**

- [`docs/research/related-work.md`](docs/research/related-work.md) — how comparable code-graph/agent-memory
  systems work, and which of their ideas are already covered vs. worth exploring
- [`docs/research/llm-native-context-representation.md`](docs/research/llm-native-context-representation.md) — core design
- [`docs/research/semantic-locality-and-llm-efficiency.md`](docs/research/semantic-locality-and-llm-efficiency.md) —
  corrected latent-space framing and its translation into bounded LLM-native retrieval
- [`docs/research/semantic-locality-llm-efficiency-paper.md`](docs/research/semantic-locality-llm-efficiency-paper.md) —
  research-scoped position paper, evidence boundary, falsifiable evaluation plan
- [`docs/research/hardware-compilation-analogy.md`](docs/research/hardware-compilation-analogy.md) —
  assembly/hardware teaching analogy for the packet formats; clearly marks which parts are
  implemented vs. still a hypothesis
- [`docs/research/comparisons/graphify.md`](docs/research/comparisons/graphify.md) — how this compares to Graphify
