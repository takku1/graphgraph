# Welcome to GraphGraph

Welcome to the **GraphGraph** setup guide. If you are an AI agent or a developer getting started, this file will guide you through installing and configuring GraphGraph in one step.

---

## For AI Agents

You can complete the entire setup and configuration process automatically. Simply execute the bootstrap command below:

```powershell
python setup_graphgraph.py --non-interactive
```

This bootstrap script will:
1. Detect or create a virtual environment (`.venv`) using `uv` (if installed) or standard `venv`.
2. Install the `graphgraph` package in editable mode (`-e .`), setting up all dependencies.
3. Automatically configure Claude Desktop MCP server configurations.
4. Verify that the CLI executes successfully.

### Workspace Skill Activation
Upon cloning this repository, the custom workspace skill located at [.agents/skills/graphgraph/SKILL.md](file:///.agents/skills/graphgraph/SKILL.md) is automatically registered. Read that file next to learn the integration commands and contract.

---

## For Humans

Run the interactive setup tool to set up the package and configure MCP server settings:

```powershell
python setup_graphgraph.py
```

Provider API keys are not needed for normal GraphGraph skill/tool use. They are
only for optional external model verification benchmarks.

---

## Verification & Next Steps

Once the setup script finishes, verify the environment and explore:

1. **Run Doctor Diagnostics**:
   Verify local dependencies, graph files, runtime probes, optional benchmark credentials, and MCP integration:
   ```powershell
   graphgraph doctor
   ```

2. **Verify CLI**:
   ```powershell
   # If venv is activated:
   graphgraph --help
   
   # Or directly:
   .venv\Scripts\graphgraph --help
   ```

3. **Run Tests**:
   ```powershell
   python -m unittest discover -s tests
   ```

4. **Read Integration Contract**:
   Read [.agents/skills/graphgraph/SKILL.md](file:///.agents/skills/graphgraph/SKILL.md) for full documentation on how to perform codebase scans, query classes, and final LLM packet generation.
