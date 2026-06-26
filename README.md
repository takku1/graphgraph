# graphgraph

`graphgraph` is a standalone context graph engine for LLM agents.

The goal is not to wrap another indexer. The goal is to build, store, retrieve,
compress, validate, and benchmark graph-shaped project context in the format an
LLM can use with the least token waste and the least interpretation loss.

Current native pieces:

- deterministic code/doc graph scanning into `.graphgraph/graph.json`,
- native `.gg` adjacency-list storage for compact graph persistence,
- natural-language graph retrieval with `graphgraph query`,
- query-class-aware packet planning,
- low-token packet encoders (`gg_max`, `semantic_arrow`, `sql`, `svo`),
- scoped policy packets for agent constraints,
- MCP tools for build/search/query/final-packet workflows,
- repeatable benchmarks for token cost, recall, irrelevant context, and packet
  round-trip validity.

Compatibility is still useful, but it is not the architecture. `graphgraph
ingest --input graphify-out/graph.json` is an import route, not the source of
truth.

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

You can set up `graphgraph` using `uv` (recommended) or standard `pip`.

### 1. Developer Installation

Install the package in editable mode. By default, this sets up the core engine along with the required parsing dependencies (`tree-sitter` and `tree-sitter-language-pack`) and secure credential storage (`keyring`).

#### Using `uv` (Fastest)
```powershell
# Clone the repository
git clone https://github.com/takku1/graphgraph.git
cd graphgraph

# Create a virtual environment and install in editable mode
uv venv
.venv\Scripts\activate
uv pip install -e .

# Optional: Install extra dependencies for running the LLM benchmark suite
uv pip install -e ".[benchmark]"
```

#### Using standard `pip`
```powershell
# Standard editable install
pip install -e .

# Optional: Install extra dependencies for running the LLM benchmark suite
pip install -e ".[benchmark]"
```

### 2. Zero-Install / Agent Tool Execution (NPX-style)

If you are using `uv` and want to execute the CLI or MCP server directly without activating a virtual environment (similar to Node's `npx` / `npx -y` workflow), you can run:

```powershell
# Run the scanner via uv run
uv run --project C:\path\to\graphgraph graphgraph scan --directory .

# Run the MCP server via uv run
uv run --project C:\path\to\graphgraph graphgraph-mcp
```

---

## Secure API Key Storage (Windows Credentials Manager)

To run LLM answer benchmarks or query tasks, you need access to OpenAI or Gemini API keys. `graphgraph` supports reading keys securely from the Windows Credential Manager via the `keyring` library (with automatic fallback to environment variables).

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

## MCP Server Configuration

You can expose `graphgraph` to AI agents (like Cursor or Claude Desktop) as a Model Context Protocol (MCP) server.

### 1. Cursor Configuration
Add the following to your Cursor MCP settings (`Settings > Features > MCP > Add New MCP Server`):

- **Name**: `graphgraph`
- **Type**: `stdio`
- **Command / Args Option (Recommended - Local Virtualenv)**:
  - **Command**: `C:/Users/dcarn/aiprojects/graphgraph/.venv/Scripts/graphgraph-mcp.exe`
- **Command / Args Option (Alternative - `uv run` mode)**:
  - **Command**: `uv`
  - **Args**: `run --project C:/Users/dcarn/aiprojects/graphgraph graphgraph-mcp`

### 2. Claude Desktop Configuration
Add the following to your `claude_desktop_config.json` (typically located at `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "graphgraph": {
      "command": "C:/Users/dcarn/aiprojects/graphgraph/.venv/Scripts/graphgraph-mcp.exe",
      "args": []
    }
  }
}
```

---

## Usage Guide

Once installed, the CLI tools `graphgraph` and `graphgraph-mcp` are added to your environment path.

### 1. Build a Native Context Graph
The scanner builds a symbol-level graph. By default, scanning uses **incremental updates** to only parse changed files.

```powershell
# Standard incremental scan
graphgraph scan --directory . --depth symbols --output .graphgraph/graph.json

# Scan using Tree-sitter frontend
graphgraph scan --directory . --depth symbols --frontend tree_sitter --output .graphgraph/graph.json

# Force a full rebuild (disable incremental updates)
graphgraph scan --directory . --depth symbols --no-incremental --output .graphgraph/graph.json
```

### 2. Retrieve Context & Render Packets
Retrieve relevant context paths from natural-language queries:

```powershell
# Retrieve query context anchors
graphgraph query "what is the blast radius of auth changes" --query-class blast_radius --show-anchors

# Generate a final prompt packet for the LLM from anchor nodes
graphgraph final --query-class blast_radius --starts src_graphgraph_cli_py
```

### 3. Exporters & Validators

```powershell
# Export to compact .gg adjacency format
graphgraph export --graph .graphgraph/graph.json --output .graphgraph/graph.gg

# Validate a generated context packet
Get-Content packet.txt | graphgraph validate
```

---

## Diagnostics

Verify that your system toolchain, Python environment, optional dependencies, API key credentials, compiled graph data, and MCP integrations are fully operational:

```powershell
graphgraph doctor
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
graphgraph eval --graph .graphgraph/graph.json --tasks benchmarks/context_graph/data/locus_tasks.json --max-nodes 40
```

### Run Unit Tests
```powershell
python -m unittest discover -s tests
```

---

## Import Routes

Import/align third-party graphs (e.g. from `graphify`) into the native context graph format:
```powershell
graphgraph ingest --input graphify-out/graph.json --output .graphgraph/graph.json
```

The unified graph contract is defined in [graph.schema.json](src/graphgraph/schema/graph.schema.json).

## Documentation

For deep-dives into the design and architectures:
- `docs/architecture.md`
- `docs/llm-native-context-graph.md`
- `docs/runtime-context-graph.md`
- `docs/relation-ontology.md`
- `docs/frontend-ir-strategy.md`
- `docs/empirical-findings.md`
- `docs/schema-alignment.md`
- `docs/integration-surfaces.md`
