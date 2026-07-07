# graphgraph

`graphgraph` is a native context graph engine for LLM agents.

The goal is to build, store, retrieve, compress, validate, and benchmark
graph-shaped project context in the format an LLM can use with the least token
waste and the least interpretation loss. GraphGraph owns this runtime path, and
also interoperates with Graphify, code-review-graph, CSV, and other graph
systems as import sources and comparison baselines.

Current native pieces:

- **Deterministic AST/Doc Scanning:** Builds topological dependency graphs in `.graphgraph/graph.gg` with **Import-Guided Disambiguation** (resolves ambiguous callable definitions using local module import stems).
- **Personalized PageRank (PPR):** Context-contextual ranking of node relevance relative to search keyword anchors (teleportation vector matches lexical hits).
- **Continuous KKT Budget Planning:** Dynamically calculates optimal node bounds using continuous Lagrangian/KKT stationarity, saving **14%+ tokens** with perfect answerability.
- **Bellman MDP Traversal stopping:** Early-terminates spreading activation propagation when marginal relevance energy per token falls below `0.005`.
- **Lessons Reflection Integration:** Injects past session reflections (`lessons.md`) directly into final prompt packets to ground the assistant.
- **Native Binary Storage:** Compresses and persists full-fidelity graphs in `.gg` format.
- **Agent Skill & Installer:** Streamlined registration via `graphgraph install` CLI utility.
- **Repeatable Benchmarking:** In-tree integration checks (`promote_check.py`) evaluating recall, token calibration, and answerability limits.

Interop is part of the architecture, not a fallback wrapper. `graphgraph ingest
--input graphify-out/graph.json` normalizes outside graph data into the same
retrieval and packet pipeline. Default graph discovery still uses native files
under `.graphgraph/` so generated exports do not silently pollute scans;
Graphify, code-review-graph, CSV, and other external graph shapes are passed
explicitly to `ingest` or commands that accept a graph path.

Install, scan, `context`, query, and MCP default workflows do not invoke
Graphify, code-review-graph, or other graph tools, and they do not read those
generated export directories. Those systems are used only when the user
explicitly imports a graph file or runs a benchmark/comparison route.

## Design Bar

The project should compete with graph/context systems on five axes:

1. **Context quality**: retrieve the right nodes, edges, paths, and source facts.
2. **Token economy**: emit the smallest packet the model can still interpret.
3. **Interpretation accuracy**: prove the model answers correctly from the
   packet, not merely that the packet is short.
4. **Update cost**: incrementally refresh changed graph regions instead of
   rebuilding everything.
5. **Latency**: keep retrieval and packet rendering fast enough for agent loops.

The low-level thesis is simple: JSON and prose are high-level languages for
context. `graphgraph` is trying to find the LLM equivalent of a compact
instruction stream: stable node symbols, relation opcodes, local adjacency, and
only the semantic text needed for the query.

## Installation & Setup

You can install `graphgraph` using `uv` (recommended) or `pipx`. This is the
single quickstart path for every supported client (Claude Code, Codex, Cursor,
Gemini/Antigravity, and Claude Desktop) — three steps, then verify.

### Step 1 — Install the package:

```powershell
# Recommended (isolated env; if 'graphgraph' isn't found after, run: uv tool update-shell):
uv tool install .

# Alternatives:
pipx install .
pip install -e .  # Developer editable installation only
```

### Step 2 — Register with your AI assistant:

```powershell
# Register the skill + MCP server globally for your user profile
graphgraph install

# Or install into the current repository instead of your user profile:
graphgraph install --project

# Target a specific platform (choices: codex, claude, cursor, gemini,
# antigravity, agy, all — "all" is the default). Each platform gets a working
# MCP server registration (portable, no absolute paths baked in) plus, where
# applicable, a skill/rules file:
graphgraph install --project --platform codex
graphgraph install --project --platform cursor
graphgraph install --project --platform gemini    # also covers antigravity / agy
graphgraph install --platform claude-desktop       # global-only; Claude Desktop has no project scope
```

### Step 3 — Verify:

```powershell
graphgraph doctor
```

This reports MCP registration status for every client above, plus environment/dependency health. If a client shows "not configured," it prints the exact `graphgraph install` command to fix it.

### Alternative: run without installing (`uv run`, NPX-style)

If you're using `uv` and want to execute the CLI or MCP server directly without activating a virtual environment (similar to Node's `npx` / `npx -y` workflow):

```powershell
# Run the scanner via uv run
uv run --project <path-to-graphgraph> graphgraph scan --directory .

# Run the MCP server via uv run
uv run --project <path-to-graphgraph> graphgraph-mcp
```

---

## Manual MCP Configuration (fallback / advanced)

`graphgraph install` (above) is the recommended path and covers Claude Code, Claude Desktop, Codex, Cursor, and Gemini/Antigravity. Use the snippets below only if you need to hand-edit a config, or you're using a client `graphgraph install` doesn't cover yet.

### Cursor
`graphgraph install --platform cursor` already writes `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) for you. To hand-edit instead (`Settings > Features > MCP > Add New MCP Server`):

- **Name**: `graphgraph`
- **Type**: `stdio`
- **Command / Args Option (Recommended - `uv run` mode)**:
  - **Command**: `uv`
  - **Args**: `run --project <path-to-graphgraph> graphgraph-mcp`
- **Command / Args Option (Alternative - Local Virtualenv)**:
  - **Command**: `<path-to-graphgraph>/.venv/Scripts/graphgraph-mcp.exe`

### Claude Desktop
`graphgraph install --platform claude-desktop` already does this for you. To hand-edit `claude_desktop_config.json` instead (typically `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "graphgraph": {
      "command": "uv",
      "args": ["run", "--project", "<path-to-graphgraph>", "graphgraph-mcp"]
    }
  }
}
```

### Codex Plugin / Skill / MCP Configuration

`graphgraph` also ships a repo-local Codex plugin wrapper in
`plugins/graphgraph`. This does not replace the existing OpenAI or Gemini
benchmark paths; it adds Codex as another installation surface.

The plugin bundles:

- `.codex-plugin/plugin.json`,
- a Codex skill for structural codebase retrieval workflows,
- a portable MCP server config (`{"command": "graphgraph-mcp"}` — no absolute
  paths, works from any clone once the package is installed),
- a repo marketplace entry at `.agents/plugins/marketplace.json`.

Generate or refresh the repo-local Codex plugin with:

```powershell
graphgraph install --project --platform codex
```

To make the repo marketplace visible to Codex:

```powershell
codex plugin marketplace add <path-to-graphgraph>
codex plugin add graphgraph@graphgraph-local
```

Then start a new Codex thread and ask for `@graphgraph`, or ask a structural
codebase question and let Codex invoke the bundled skill/MCP server.

If you'd rather pin the plugin to an uninstalled dev checkout (`uv run
--project <path> graphgraph-mcp` instead of relying on the installed
`graphgraph-mcp` console script), `python scripts\configure_codex_plugin.py
--repo-root <checkout>` rewrites `plugins/graphgraph/.mcp.json` into that
pinned form — an optional dev-mode convenience, not a required repair step.

---

## Usage Guide

Once installed, the CLI tools `graphgraph` and `graphgraph-mcp` are added to your environment path.

### 1. Build a Native Context Graph
The scanner builds a symbol-level graph. With Tree-sitter installed, `--depth symbols` emits class/function/method/struct/enum/interface nodes (with `contains` edges) for Python, JavaScript/TypeScript, Go, Rust, Java, C#, C/C++, Ruby, PHP, Kotlin, Scala, and Swift. Files in languages without a symbol frontend fall back to file-level nodes. By default, scanning uses **incremental updates** to only parse changed files.

```powershell
# Standard incremental scan
graphgraph scan --directory . --depth symbols --output .graphgraph/graph.gg

# Scan using Tree-sitter frontend
graphgraph scan --directory . --depth symbols --frontend tree_sitter --output .graphgraph/graph.gg

# Force a full rebuild (disable incremental updates)
graphgraph scan --directory . --depth symbols --no-incremental --output .graphgraph/graph.gg
```

### 2. Retrieve Context & Render Packets
Retrieve relevant context packets from natural-language queries. This is the
preferred agent workflow because GraphGraph discovers anchors before rendering
the packet:

```powershell
# One-step workflow: build/load .graphgraph/graph.gg, discover anchors, render packet
graphgraph context "what is the blast radius of auth changes" --query-class blast_radius --show-stats

# Query an existing graph directly and show the resolved anchors
graphgraph query "what is the blast radius of auth changes" --query-class blast_radius --show-anchors

# Use final only when you already have confirmed node IDs
graphgraph final --query-class blast_radius --starts src_graphgraph_cli_py

# Optional stable prefix for prompt-cache workflows
graphgraph final --stable-skeleton --max-nodes 120
```

### 3. Profile Graph Shape
Measure graph shape and inspect dynamic budget candidates without changing
runtime defaults:

```powershell
graphgraph profile --graph .graphgraph/graph.gg
```

### 4. Summarize Project Status
Validate the active graph, report code/doc balance, inspect package metadata,
and optionally run lightweight Python import/module probes. Probe mode compares
raw checkout behavior with src-layout `PYTHONPATH=src` behavior and prints
runtime notes when a package only works after that path fix:

```powershell
graphgraph status --probe
graphgraph status --json
```

### 5. Exporters & Validators

```powershell
# Export JSON or imported graph data to native binary .gg
graphgraph export --graph graphify-out/graph.json --output .graphgraph/graph.gg

# Validate a generated context packet
Get-Content packet.txt | graphgraph validate
```

---

## Diagnostics

Verify that your system toolchain, Python environment, optional dependencies,
compiled graph data, local runtime probes, optional benchmark credentials, and
MCP integrations are operational:

```powershell
graphgraph doctor
```

---

## Optional External Benchmark API Keys

Normal `graphgraph` CLI, skill, and MCP workflows are local. They scan the
workspace, compile graph packets, validate those packets, and let the active AI
assistant use them as context. No OpenAI, Gemini, or other provider API key is
required for that path.

API keys are only needed when you explicitly run optional external model-answer
benchmarks (below). For those benchmark scripts, `graphgraph` supports reading keys
securely from the Windows Credential Manager via the `keyring` library (with
automatic fallback to environment variables).

### How to set up credentials:

#### Option A: Set via Python CLI (Fastest)
Run the following commands in your terminal to securely store your keys:
```powershell
# Store OpenAI API key
python -c "import keyring; keyring.set_password('OpenAI', 'API_KEY', 'your-openai-api-key')"

# Store Gemini API key
python -c "import keyring; keyring.set_password('Gemini', 'API_KEY', 'your-gemini-api-key')"
```

#### Option B: Set via Windows GUI
1. Open the **Start Menu** and search for **Credential Manager**.
2. Click on **Windows Credentials**.
3. Click **Add a generic credential**.
4. Set the fields:
   - **Internet or network address**: `OpenAI` or `Gemini`
   - **User name**: `API_KEY`
   - **Password**: `your-api-key-here`
5. Click **OK**.

#### Option C: Fallback Environment Variables
If `keyring` is not installed or keys are not found in the Credential Manager, `graphgraph` will fall back to reading:
```powershell
$env:OPENAI_API_KEY="your-openai-key"
$env:GEMINI_API_KEY="your-gemini-key"
```

---

## Benchmarks & Testing

`graphgraph` has an extensive benchmark suite to measure context quality, token efficiency, and reasoning accuracy.

### Run All Benchmarks
```powershell
python benchmarks\context_graph\run_all.py
```

### Run Recall Evaluation
```powershell
graphgraph eval --graph .graphgraph/graph.gg --tasks benchmarks/context_graph/data/locus_tasks.json --max-nodes 40
```

### Run Unit Tests
```powershell
python -m pytest
```

---

## Import Routes

Import/align third-party graphs (e.g. from `graphify`) into the native context graph format:
```powershell
graphgraph ingest --input graphify-out/graph.json --output .graphgraph/graph.gg
```

External graph directories are not default runtime sources. After import,
run normal commands against the native `.graphgraph/graph.gg` output.

The unified graph contract is defined in [graph.schema.json](src/graphgraph/schema/graph.schema.json).

## Documentation

For deep-dives into the design and architectures:
- `docs/architecture.md`
- `docs/llm-native-context-graph.md`
- `docs/runtime-context-graph.md`
- `docs/relation-ontology.md`
- `docs/source-layout.md`
- `docs/interpretation-layer.md`
- `docs/frontend-ir-strategy.md`
- `docs/empirical-findings.md`
- `docs/schema-alignment.md`
- `docs/integration-surfaces.md`
- `docs/graphgraph-vs-graphify.md`
