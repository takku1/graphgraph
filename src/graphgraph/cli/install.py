from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def _codex_plugin_json() -> dict:
    return {
        "name": "graphgraph",
        "version": "0.1.0",
        "description": "Codex integration for GraphGraph codebase context retrieval, packet validation, and MCP tools.",
        "author": {"name": "GraphGraph"},
        "license": "MIT",
        "keywords": ["codex", "mcp", "codebase-context", "graph-rag", "retrieval"],
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "GraphGraph",
            "shortDescription": "Use compact graph packets for codebase context in Codex.",
            "longDescription": (
                "GraphGraph bundles a Codex skill and MCP server configuration for scanning repositories, "
                "finding graph anchors, rendering final context packets, and validating compressed codebase graph evidence."
            ),
            "developerName": "GraphGraph",
            "category": "Productivity",
            "capabilities": ["Codebase context", "MCP tools", "Local retrieval"],
            "defaultPrompt": [
                "Use GraphGraph to explain this subsystem.",
                "Find the blast radius with GraphGraph.",
                "Validate a GraphGraph packet.",
            ],
            "brandColor": "#2563EB",
        },
    }


def _mcp_server_config(project_root: Path | None) -> dict:
    """Build an ``{"mcpServers": {...}}`` block for the graphgraph MCP server.

    When ``project_root`` is given, pin ``uv`` to that project (used for
    project-scoped configs like Codex plugins and Claude Code ``.mcp.json``).
    When it is ``None`` (global install), use the installed ``graphgraph-mcp``
    entry point so the server resolves from any working directory.
    """
    if project_root is not None:
        root = project_root.resolve().as_posix()
        server = {
            "command": "uv",
            "args": ["run", "--no-sync", "--project", root, "graphgraph-mcp"],
            "cwd": root,
            "startup_timeout_sec": 20,
            "tool_timeout_sec": 120,
        }
    elif shutil.which("uv") is not None:
        server = {"command": "uv", "args": ["run", "graphgraph-mcp"]}
    else:
        server = {"command": "graphgraph-mcp", "args": []}
    return {"mcpServers": {"graphgraph": server}}


def _codex_mcp_json(project_root: Path) -> dict:
    return _mcp_server_config(project_root)


def _upsert_mcp_servers(config_path: Path, server_block: dict) -> None:
    """Merge the graphgraph MCP server entry into a JSON config, preserving others."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.setdefault("mcpServers", {}).update(server_block["mcpServers"])
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_claude_code(
    is_project: bool,
    project_root: Path | None,
    skill_content: str,
    rule_block: str,
) -> None:
    """Register GraphGraph for Claude Code (the CLI/IDE agent, not Claude Desktop).

    Project scope writes a repo-local ``.mcp.json``, a ``.claude/skills`` skill,
    and appends workspace rules to ``CLAUDE.md``. Global scope writes a user
    skill under ``~/.claude/skills`` and registers the MCP server in
    ``~/.claude.json``.
    """
    if is_project and project_root is not None:
        root = project_root
        _upsert_mcp_servers(root / ".mcp.json", _mcp_server_config(root))
        skill_dir = root / ".claude" / "skills" / "graphgraph"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")
        claude_md = root / "CLAUDE.md"
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        if "# GraphGraph Workspace Rules" not in existing:
            claude_md.write_text(existing + rule_block, encoding="utf-8")
        print(f"Registered GraphGraph for Claude Code (project): {root / '.mcp.json'}, {skill_dir / 'SKILL.md'}")
    else:
        skill_dir = Path.home() / ".claude" / "skills" / "graphgraph"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")
        _upsert_mcp_servers(Path.home() / ".claude.json", _mcp_server_config(None))
        print(f"Registered GraphGraph for Claude Code (global): {skill_dir / 'SKILL.md'}, {Path.home() / '.claude.json'}")


def _write_codex_plugin(plugin_root: Path, project_root: Path, skill_content: str) -> None:
    (plugin_root / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_root / "skills" / "graphgraph").mkdir(parents=True, exist_ok=True)

    (plugin_root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(_codex_plugin_json(), indent=2) + "\n",
        encoding="utf-8",
    )
    (plugin_root / ".mcp.json").write_text(
        json.dumps(_codex_mcp_json(project_root), indent=2) + "\n",
        encoding="utf-8",
    )
    (plugin_root / "skills" / "graphgraph" / "SKILL.md").write_text(skill_content, encoding="utf-8")


def _upsert_codex_marketplace(market_file: Path, plugin_name: str = "graphgraph") -> None:
    market_file.parent.mkdir(parents=True, exist_ok=True)
    if market_file.exists():
        try:
            market_data = json.loads(market_file.read_text(encoding="utf-8"))
        except Exception:
            market_data = {}
    else:
        market_data = {}

    market_data.setdefault("name", "graphgraph-local")
    interface = market_data.setdefault("interface", {})
    interface.setdefault("displayName", "GraphGraph Local")
    plugins = market_data.setdefault("plugins", [])

    entry = {
        "name": plugin_name,
        "source": {
            "source": "local",
            "path": f"./plugins/{plugin_name}",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }
    for idx, existing in enumerate(plugins):
        if existing.get("name") == plugin_name:
            plugins[idx] = entry
            break
    else:
        plugins.append(entry)

    market_file.write_text(json.dumps(market_data, indent=2) + "\n", encoding="utf-8")


def cmd_install(args: argparse.Namespace) -> None:
    # 1. Determine destination root
    if args.project:
        dest_root = Path(".")
        print(f"Installing GraphGraph skill locally in project root: {dest_root.resolve()}")
    else:
        dest_root = Path.home() / ".gemini"
        print(f"Installing GraphGraph skill globally in: {dest_root.resolve()}")

    # 2. Write/Register AGENTS.md rules
    agents_file = (dest_root / "config" / "AGENTS.md") if not args.project else (dest_root / ".agents" / "AGENTS.md")
    agents_file.parent.mkdir(parents=True, exist_ok=True)

    existing_content = ""
    if agents_file.exists():
        existing_content = agents_file.read_text(encoding="utf-8")

    rule_marker = "# GraphGraph Workspace Rules" if args.project else "# GraphGraph Global Rules"
    if True:
        rule_content = f"\n\n{rule_marker}\n\n"
        rule_content += (
            "You have direct access to the **`graphgraph`** codebase context serialization engine. "
            "It is available as a CLI tool (`graphgraph`) and, on platforms with MCP config, as an MCP server (`graphgraph` server).\n\n"
            "## Instinctive Tool Guide\n\n"
            "When the user asks codebase structure/dependency questions or says \"using graphgraph now to build context\":\n"
            "0. **Check MCP availability first:** The `graphgraph/*` MCP tools exist only if a graphgraph MCP server is registered for *this* client; many sessions have none even when Claude Desktop does. If those tools are not present, use the `graphgraph` CLI instead and do NOT map MCP tool names onto CLI flags (the CLI subcommands `context`/`query`/`final` have different options). `graphgraph doctor` shows per-client MCP status.\n"
            "1. **Graph-first orientation:** Check if `.graphgraph/graph.gg` or another native graph exists in the workspace. "
            "If it does not exist, run `graphgraph scan --depth symbols --docs` to generate it before broad structural exploration.\n"
            "2. **Context Compilation -- preferred (no node IDs needed):** Call `graphgraph/query_context` with a "
            "natural-language query. It auto-discovers anchors and returns a ready packet.\n"
            "3. **Context Compilation -- when you know node IDs:** Call `graphgraph/search_nodes` to confirm the ID, "
            "then `graphgraph/final_packet` with the confirmed IDs.\n"
            "4. **Evidence discipline:** Use the compressed topological packet as orientation evidence for project structure, imports, and calls.\n"
            "5. **Verification:** Validate graph packets with `graphgraph/validate_packet` or `graphgraph validate`, and verify final claims against source files, tests, or explicitly requested command output.\n"
            "### Available MCP Tools\n"
            "* **`graphgraph/query_context`**: **Preferred.** Natural-language query -> auto-discovered anchors -> graph packet. No node IDs needed.\n"
            "* **`graphgraph/search_nodes`**: Find node IDs by label, path, or kind substring. Use before `final_packet`.\n"
            "* **`graphgraph/final_packet`**: Render compressed context packet from known anchor node IDs.\n"
            "* **`graphgraph/project_status`**: Validate the graph, summarize code/doc balance, package metadata, and optional runtime probes.\n"
            "* **`graphgraph/plan_context`**: Pass `query_class` to plan the expansion depth.\n"
            "* **`graphgraph/build_graph`**: Scan a directory. Accepts `exclude_dirs` to skip large external dirs and `include_dirs` to keep real project dirs that match default skip names.\n\n"
            "### Available CLI Commands\n"
            "* **Scan**: `graphgraph scan --depth symbols --docs` (default max-nodes=2000)\n"
            "* **Scan with exclusions**: `graphgraph scan --depth symbols --docs --exclude repos references_temp`\n"
            "* **Project status**: `graphgraph status --probe`\n"
            "* **One-step context packet**: `graphgraph context \"<text>\" --query-class subsystem_summary --show-stats`\n"
            "* **Natural-language query on an existing graph**: `graphgraph query \"<text>\" --query-class blast_radius --show-anchors`\n"
            "* **Known-node packet only**: `graphgraph final --graph <graph_path> --query-class <query_class> --starts <node_id>...`\n"
            "* **Stable prompt-cache skeleton**: `graphgraph final --stable-skeleton --max-nodes 120`\n"
            "* **System diagnostics**: `graphgraph doctor`\n"
        )
    if rule_marker not in existing_content:
        agents_file.write_text(existing_content + rule_content, encoding="utf-8")
        print(f"Updated rules in: {agents_file}")
    else:
        print(f"Rules already present in: {agents_file}")

    # 3. Write/Register SKILL.md
    skills_dir = (dest_root / "config" / "skills" / "graphgraph") if not args.project else (dest_root / ".agents" / "skills" / "graphgraph")
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skills_dir / "SKILL.md"

    skill_content = (
        "---\n"
        "name: graphgraph\n"
        "description: Use GraphGraph for codebase context retrieval: one-step graph build/query, dependency lookup, blast radius analysis, status packets, packet validation, or graph-backed source orientation.\n"
        "---\n\n"
        "# GraphGraph Operational Contract\n\n"
        "GraphGraph is installed for native codebase context retrieval across coding agents (Codex, Gemini/Antigravity, Claude Code, Cursor, and other MCP/CLI-capable clients) and CLI workflows. Use it to orient on code structure before broad source searches.\n\n"
        "> [!IMPORTANT]\n"
        "> **STEP 0 -- CHECK TOOL AVAILABILITY FIRST**\n"
        "> The `graphgraph/*` MCP tools only exist if a graphgraph MCP server is registered for *this* client. Many sessions (e.g. Claude Code without project `.mcp.json`) have **no** graphgraph MCP server even when Claude Desktop does. Before following any MCP step, confirm a tool named `graphgraph/query_context` (or similar) is actually available. **If it is not, silently switch to the CLI path below -- do NOT try to translate MCP tool names into CLI flags.** Run `graphgraph doctor` to see per-client MCP status.\n\n"
        "> **DEFAULT PATH**\n"
        "> If MCP tools are available, prefer `graphgraph/query_context`. Otherwise run `graphgraph context \"<query>\" --query-class <class>`; it builds `.graphgraph/graph.gg` if missing, then returns a packet. Leave `max_nodes` unset for normal use so GraphGraph can choose the dynamic query-class and graph-shape budget; pass an explicit cap only for repeatable tests or intentionally small packets.\n\n"
        "> **BENCHMARK DISCIPLINE**\n"
        "> Do not use expected answer keys or benchmark fixture answers as evidence when answering codebase questions. Use only the retrieved graph packet, source files, docs, and explicitly requested command output.\n\n"
        "## Decision Rules\n\n"
        "1. For natural-language codebase questions, call `graphgraph/query_context` first. Do not preselect node IDs unless the user supplied exact files/symbols.\n"
        "2. If no graph exists or MCP is unavailable, run `graphgraph context \"<query>\" --query-class subsystem_summary --show-stats`.\n"
        "3. For focused implementation work, add `--scope src/path` or use `search_nodes` before `final_packet`.\n"
        "4. Validate saved graph files with `graphgraph validate-graph`; validate rendered packets with `graphgraph validate`.\n"
        "5. Treat GraphGraph as orientation evidence. Verify final claims against source files or test output before changing code.\n\n"
        "## MCP Tools\n\n"
        "| Tool | Purpose |\n"
        "|------|---------|\n"
        "| `query_context` | Natural-language query -> anchors -> compressed packet. Best default. |\n"
        "| `search_nodes` | Resolve file/symbol labels to node IDs for exact follow-up packets. |\n"
        "| `final_packet` | Render a packet from known node IDs. |\n"
        "| `project_status` | Validate graph, summarize code/doc balance, package metadata, and optional probes. |\n"
        "| `build_graph` | Build `.graphgraph/graph.gg`; accepts `exclude_dirs` and `include_dirs`. |\n"
        "| `validate_packet` | Validate a rendered packet, not a saved graph JSON file. |\n\n"
        "## CLI Commands (the real subcommands)\n\n"
        "The MCP tool names above are NOT CLI flags. The CLI has distinct subcommands with **disjoint** options -- do not, e.g., pass `--starts` to `query` (it has no such flag). Use this map:\n\n"
        "| Need | Subcommand | Anchors | Example |\n"
        "|------|-----------|---------|---------|\n"
        "| Ask a natural-language question (auto-finds anchors) | `context` | auto | `graphgraph context \"how does retrieval work\" --query-class subsystem_summary --show-stats` |\n"
        "| Same, on an existing graph only (no auto-build) | `query` | auto | `graphgraph query \"callers of retrieve_context\" --query-class reverse_lookup --show-anchors` |\n"
        "| Render from node IDs you already know | `final` | `--starts <id>...` | `graphgraph final --query-class blast_radius --starts src_graphgraph_retrieval_context_py` |\n"
        "| Low-level render from known IDs (no policies) | `render` | `--starts <id>...` | `graphgraph render --query-class direct_lookup --starts <id>` |\n\n"
        "Notes: `--starts` exists only on `final` and `render`. `context`/`query` take free text and discover anchors themselves; use `--show-anchors` to see what they picked. Other helpers:\n\n"
        "- Project status: `graphgraph status --probe`\n"
        "- Force rebuild: `graphgraph context \"<query>\" --rebuild --scan-max-nodes 5000 --show-stats`\n"
        "- Focus scope: `graphgraph context \"<query>\" --scope src/graphgraph/retrieval --query-class blast_radius`\n"
        "- Dynamic sizing: omit `--max-nodes` for production context packets; use `--scan-max-nodes` only to control how much of the repo is indexed.\n"
        "- Validate a saved graph file: `graphgraph validate-graph` (or bare `graphgraph validate`, which auto-detects the native graph under `.graphgraph/`)\n"
        "- Validate a rendered packet from stdin: `graphgraph query \"<query>\" --packet gg_max | graphgraph validate`\n\n"
        "## Query Classes\n\n"
        "| Query Class | Description / Example Question | Hops | Format | Reason |\n"
        "| :--- | :--- | :---: | :--- | :--- |\n"
        "| `direct_lookup` | Specific file/symbol details | 1 | `gg_max` | measured token floor |\n"
        "| `reverse_lookup` | References/callers/users of a symbol | 1 | `gg_max` | measured token floor |\n"
        "| `subsystem_summary` | High-level status or architecture area | 1 | `gg_max` | measured token floor |\n"
        "| `blast_radius` | What changes if this is modified? | 2 | `gg_max` | topology-first |\n"
        "| `multi_hop_path` | How does A reach/call B? | 2 | `gg_max` | path evidence |\n"
        "| `doc_summary` | README/docs/install/usage summaries | 1 | `doc_summary` | grounded docs, no topology |\n"
        "| `negative_query` | Is this isolated/missing? | 1 | `semantic_arrow` | minimal evidence |\n\n"
        "Format note: `gg_max`/`gg_max_hybrid` use short integer node handles and are the most token-efficient. `sql` also uses integer handles but carries extra `kind`/`path`/`weight` columns, so it is larger than topology-only `gg_max` (typically ~2x on real repos, more when names are long) -- pick it only when you need those columns. Token ratios between formats are repo-dependent; measure on your own codebase with `--show-stats` or `graphgraph compare` rather than assuming fixed multipliers.\n\n"
        "## Noise Controls\n\n"
        "Default scanning skips generated artifact directories such as `.graphgraph`, `graphify-out`, `.code-review-graph`, `evidence`, `artifacts`, `scratch`, `tmp`, build outputs, vendors, and cloned external repos. Normal install, scan, context, query, and MCP workflows do not invoke Graphify, code-review-graph, or other graph tools; external graph outputs are read only when explicitly passed to `ingest` or a graph-path argument. For project-specific noise, pass `exclude_dirs` in MCP or `--exclude <dir>` in CLI.\n"
    )
    skill_file.write_text(skill_content, encoding="utf-8")
    print(f"Registered skill in: {skill_file}")

    # 4. Handle Platform-Specific Registrations (Codex, Claude, Cursor)
    platform = getattr(args, "platform", "all")
    if platform in ("codex", "all"):
        if args.project:
            project_root = Path(".").resolve()
            plugins_dir = dest_root / "plugins" / "graphgraph"
            market_file = dest_root / ".agents" / "plugins" / "marketplace.json"
        else:
            project_root = Path.cwd().resolve()
            plugins_dir = Path.home() / "plugins" / "graphgraph"
            market_file = Path.home() / ".agents" / "plugins" / "marketplace.json"

        _write_codex_plugin(plugins_dir, project_root, skill_content)
        _upsert_codex_marketplace(market_file)
        print(f"Registered Codex plugin in: {plugins_dir}")
        print(f"Registered Codex marketplace entry in: {market_file}")

    # Claude Code (project-scoped CLI/IDE agent): .mcp.json + .claude/skills + CLAUDE.md
    if platform in ("claude", "claude-code", "all"):
        claude_project_root = Path(".").resolve() if args.project else None
        _write_claude_code(args.project, claude_project_root, skill_content, rule_content)

    # Claude Desktop (global MCP app): claude_desktop_config.json
    if platform in ("claude", "claude-desktop", "all") and not args.project:
        appdata = os.environ.get("APPDATA")
        if appdata:
            claude_path = Path(appdata) / "Claude" / "claude_desktop_config.json"
            claude_path.parent.mkdir(parents=True, exist_ok=True)
            claude_data = {}
            if claude_path.exists():
                try:
                    claude_data = json.loads(claude_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            servers = claude_data.setdefault("mcpServers", {})
            has_uv = shutil.which("uv") is not None
            servers["graphgraph"] = {
                "command": "uv" if has_uv else "graphgraph-mcp",
                "args": ["run", "--project", str(Path(".").resolve().as_posix()), "graphgraph-mcp"] if has_uv else []
            }
            claude_path.write_text(json.dumps(claude_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Registered GraphGraph in Claude Desktop config: {claude_path}")
