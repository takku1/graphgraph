from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from ..cache import TopologicalKVCache, compute_cache_key
from ..eval import evaluate_graph, load_eval_tasks, results_to_json
from ..frontends import available_frontends
from ..io import find_graph_path, find_policies_path, load_any, save_gg, save_validated_graph
from ..metrics import compare_graphs
from ..ontology import DEFAULT_RELATIONS
from ..packets import render_packet
from ..planning import (
    compute_subgraph_stats,
    plan_context,
    profile_graph_shape,
    recommend_node_budget,
    refine_plan_for_subgraph,
)
from ..services import render_final_packet, render_query_context, render_stable_skeleton
from ..services.context import resolve_start_nodes
from ..services.native import build_project_status, graph_shape, render_native_context, scan_validated_graph
from ..traversal import POLICIES, traversal_policy
from ..validate import validate_any, validate_graph_json


def cmd_plan(args: argparse.Namespace) -> None:
    plan = plan_context(args.query_class, getattr(args, "query", ""))
    print(
        f"{plan.hops}hop {plan.direction} {plan.packet} "
        f"n={plan.node_budget} anchors={plan.anchor_limit}: {plan.reason}"
    )


def cmd_profile(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    shape = profile_graph_shape(graph)
    query = getattr(args, "query", "")
    report = {
        "graph": str(graph_path),
        "shape": shape.__dict__,
        "budget_candidates": [
            recommend_node_budget(query_class, query, shape).__dict__
            for query_class in (
                "direct_lookup",
                "reverse_lookup",
                "multi_hop_path",
                "blast_radius",
                "subsystem_summary",
                "negative_query",
            )
        ],
    }
    print(json.dumps(report, indent=2))


def cmd_doctor(args: argparse.Namespace) -> None:
    import os
    import platform
    import sys
    from pathlib import Path
    
    print("GraphGraph Doctor - System Diagnostic Utility")
    print("=============================================")
    
    # 1. Environment and Python Checks
    print("\n[Environment]")
    print(f"  Python Version: {sys.version.split()[0]} ({'OK' if sys.version_info >= (3, 10) else 'FAIL (>=3.10 required)'})")
    print(f"  Platform: {platform.system()} {platform.release()}")
    in_venv = sys.prefix != sys.base_prefix or 'VIRTUAL_ENV' in os.environ
    print(f"  Virtual Environment Active: {in_venv}")
    
    # 2. Package Dependency Checks
    print("\n[Dependencies]")
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_language_pack  # noqa: F401
        print("  tree-sitter: Installed (OK)")
    except ImportError:
        print("  tree-sitter: Missing (WARN - AST symbols scanning disabled)")

    try:
        import keyring
        print("  keyring: Installed (OK)")
    except ImportError:
        print("  keyring: Missing (WARN - Windows Credential Manager integration disabled)")

    try:
        import tiktoken  # noqa: F401
        print("  tiktoken: Installed (OK)")
    except ImportError:
        print("  tiktoken: Missing (WARN - using approximate token count)")
        
    # 3. Secure Credential Checks
    print("\n[Secure Credentials]")
    try:
        import keyring
        openai_key = keyring.get_password("OpenAI", "API_KEY")
        if openai_key:
            masked = openai_key[:7] + "..." + openai_key[-4:] if len(openai_key) > 10 else "..."
            print(f"  OpenAI API Key: Found in Credential Manager ({masked})")
        else:
            env_key = os.environ.get("OPENAI_API_KEY")
            if env_key:
                masked = env_key[:7] + "..." + env_key[-4:] if len(env_key) > 10 else "..."
                print(f"  OpenAI API Key: Found in environment ({masked})")
            else:
                print("  OpenAI API Key: Not found in Credential Manager or environment")
                
        gemini_key = keyring.get_password("Gemini", "API_KEY")
        if gemini_key:
            masked = gemini_key[:7] + "..." + gemini_key[-4:] if len(gemini_key) > 10 else "..."
            print(f"  Gemini API Key: Found in Credential Manager ({masked})")
        else:
            env_key = os.environ.get("GEMINI_API_KEY")
            if env_key:
                masked = env_key[:7] + "..." + env_key[-4:] if len(env_key) > 10 else "..."
                print(f"  Gemini API Key: Found in environment ({masked})")
            else:
                print("  Gemini API Key: Not found in Credential Manager or environment")
    except Exception as e:
        print(f"  Credential lookup error: {e}")
        
    # 4. Local Graph File Checks
    print("\n[Graph Files]")
    try:
        graph_path = find_graph_path()
        print(f"  Active Graph: Found at {graph_path}")
        try:
            graph = load_any(graph_path)
            nodes = list(graph.nodes.values())
            edges = graph.edges
            print(f"    - Nodes: {len(nodes)}  |  Edges: {len(edges)}")
            has_symbols = any(n.kind in ("function", "class", "struct", "method") for n in nodes)
            print(f"    - Symbol-level scanner info: {'Yes (OK)' if has_symbols else 'No (Files only)'}")

            # Kind breakdown
            kind_counts: dict[str, int] = {}
            for n in nodes:
                kind_counts[n.kind] = kind_counts.get(n.kind, 0) + 1
            top = sorted(kind_counts.items(), key=lambda kv: -kv[1])[:10]
            print(f"    - Node kinds: {', '.join(f'{k}={v}' for k, v in top)}")

            source_kinds = {"python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
                            "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
                            "kotlin", "scala", "haskell", "lean", "function", "class",
                            "struct", "method", "interface"}
            source_count = sum(v for k, v in kind_counts.items() if k in source_kinds)
            if source_count == 0:
                print("    - [!] WARNING: No source-code nodes found in graph.")
                print("      The scanner may have missed your source directory due to:")
                print("      * max_nodes cap (default 2000 -- try --max-nodes 5000)")
                print("      * Source dir is inside a skipped directory (repos/, references/, etc.)")
                print("      * Files are staged but not committed (re-scan after git add)")
                print("      Rescan with: graphgraph scan --depth symbols --docs")
            else:
                print(f"    - Source nodes: {source_count} (OK)")
        except Exception as e:
            print(f"    - Error loading graph: {e}")
    except FileNotFoundError:
        print("  Active Graph: No native graph file found in .graphgraph/")
        print("    - Build one with: graphgraph scan --directory . --depth symbols --docs --output .graphgraph/graph.json")
        print("    - Import external graphs explicitly with: graphgraph ingest --input <path> --output .graphgraph/graph.json")


    # 5. MCP Settings Verification
    print("\n[MCP Server Integration]")
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            claude_config = Path(appdata) / "Claude" / "claude_desktop_config.json"
            if claude_config.exists():
                try:
                    with open(claude_config, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    servers = data.get("mcpServers", {})
                    if "graphgraph" in servers:
                        info = servers["graphgraph"]
                        print("  Claude Desktop: Configured (OK)")
                        print(f"    - Command: {info.get('command')}")
                    else:
                        print("  Claude Desktop: Found, but 'graphgraph' server is not configured")
                except Exception as e:
                    print(f"  Claude Desktop: Found config but failed to parse: {e}")
            else:
                print("  Claude Desktop: Claude config directory exists, but claude_desktop_config.json is missing")
        else:
            print("  Claude Desktop: APPDATA path not found")
    else:
        print("  Claude Desktop config check is only supported on Windows in this doctor version")


def cmd_render(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    starts = resolve_start_nodes(graph, args.starts)
    plan = plan_context(args.query_class, max_nodes=args.max_nodes)
    nodes, edges = graph.expand(starts, hops=plan.hops, max_nodes=plan.node_budget, direction=plan.direction)
    plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, nodes, edges))
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(args.starts, args.query_class, plan.hops, f"{plan.packet}|render|{plan.planner_version}|{plan.node_budget}|{plan.direction}")
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    packet = render_packet(graph, nodes, edges, plan.packet)
    cache.set(graph_path, cache_key, packet)
    print(packet)


def cmd_final(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    policies_path = Path(args.policies) if args.policies else find_policies_path()

    if getattr(args, "stable_skeleton", False):
        max_nodes = getattr(args, "max_nodes", 100) or 100
        print(render_stable_skeleton(graph_path, max_nodes=max_nodes, packet=getattr(args, "packet", "gg_max") or "gg_max"))
        return

    if not args.starts:
        print("Error: --starts is required unless --stable-skeleton is specified.", file=sys.stderr)
        sys.exit(1)
    if not args.query_class:
        print("Error: --query-class is required unless --stable-skeleton is specified.", file=sys.stderr)
        sys.exit(1)

    print(
        render_final_packet(
            starts=args.starts,
            query_class=args.query_class,
            query_text=args.query,
            graph_path=graph_path,
            policies_path=policies_path,
            paths=tuple(args.path),
            tags=tuple(args.tag),
            max_nodes=args.max_nodes,
            cache_namespace="cli_final",
            packet=getattr(args, "packet", None),
        )
    )


def cmd_query(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    output = render_query_context(
        query=args.query,
        query_class=args.query_class,
        graph_path=graph_path,
        packet=args.packet,
        anchor_limit=args.anchor_limit,
        max_nodes=args.max_nodes,
        scopes=tuple(args.scope),
        show_anchors=args.show_anchors,
        cache_namespace="cli_query",
    )
    print(output)


def cmd_context(args: argparse.Namespace) -> None:
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = tuple(skip_dirs + [d for d in exclude_dirs if d not in skip_dirs])
    output, status = render_native_context(
        query=args.query,
        query_class=args.query_class,
        directory=Path(args.directory) if args.directory else Path("."),
        graph_path=Path(args.graph) if args.graph else None,
        rebuild=args.rebuild,
        max_nodes=args.max_nodes,
        scan_max_nodes=args.scan_max_nodes,
        packet=args.packet,
        anchor_limit=args.anchor_limit,
        scopes=tuple(args.scope),
        skip_dirs=all_skip,
        show_anchors=args.show_anchors,
    )
    if args.show_stats:
        shape = graph_shape(status.graph)
        action = "built" if status.built else "loaded"
        print(
            (
                f"GraphGraph context {action}: {status.path} "
                f"nodes={shape['nodes']} edges={shape['edges']} "
                f"source={shape['source_nodes']} docs={shape['doc_nodes']} other={shape['other_nodes']}"
            ),
            file=sys.stderr,
        )
    print(output)


def cmd_status(args: argparse.Namespace) -> None:
    report = build_project_status(
        directory=Path(args.directory) if args.directory else Path("."),
        graph_path=Path(args.graph) if args.graph else None,
        run_probes=bool(args.probe),
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    graph = report["graph"]  # type: ignore[index]
    package = report["package"]  # type: ignore[index]
    validation = graph["validation"]  # type: ignore[index]
    shape = graph["shape"]  # type: ignore[index]
    print("GraphGraph Status")
    print("=================")
    print(f"Graph: {graph['path']}")
    print(
        f"Validation: {'PASS' if validation['ok'] else 'FAIL'} "
        f"{validation['format']} nodes={validation['nodes']} edges={validation['edges']}"
    )
    print(
        f"Shape: source={shape['source_nodes']} docs={shape['doc_nodes']} "
        f"other={shape['other_nodes']} total={shape['nodes']}"
    )
    print("Top kinds: " + ", ".join(f"{k}={v}" for k, v in graph["top_kinds"].items()))
    if package.get("name"):
        print(f"Package: {package['name']} {package.get('version') or ''}".rstrip())
        print(f"Module: {package.get('module') or '(unknown)'}")
    if package.get("src_layout"):
        print(f"Runtime hint: {package['import_hint']}")
    scripts = package.get("scripts") or {}
    if scripts:
        print("Scripts: " + ", ".join(f"{name}={target}" for name, target in scripts.items()))
    probes = report.get("runtime_probes") or []
    notes = report.get("runtime_notes") or []
    if notes:
        print("Runtime notes:")
        for note in notes:
            print(f"  - {note}")
    if probes:
        print("Runtime probes:")
        for probe in probes:
            status = "PASS" if probe.get("ok") else "FAIL"
            label = probe.get("name") or "probe"
            env = probe.get("env") or ""
            print(f"  {status} {label} [{env}] {probe.get('command')} rc={probe.get('returncode', '')}")
            for line in probe.get("output", [])[:2]:
                print(f"    {line}")


def cmd_validate(args: argparse.Namespace) -> None:
    packet = Path(args.packet).read_text(encoding="utf-8") if args.packet else sys.stdin.read()
    result = validate_any(packet)
    status = "PASS" if result.ok else "FAIL"
    print(f"{status} {result.format} nodes={result.node_count} edges={result.edge_count}")
    for error in result.errors:
        print(f"- {error}")


def cmd_validate_graph(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    result = validate_graph_json(graph_path.read_text(encoding="utf-8"))
    status = "PASS" if result.ok else "FAIL"
    print(f"{status} {result.format} nodes={result.node_count} edges={result.edge_count} path={graph_path}")
    for error in result.errors:
        print(f"- {error}")


def cmd_scan(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.json")
    # Merge --skip-dirs and --exclude into a single list
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = skip_dirs + [d for d in exclude_dirs if d not in skip_dirs]

    status = scan_validated_graph(
        directory=root,
        output_path=output_path,
        max_nodes=args.max_nodes,
        generic_mentions=args.generic_mentions,
        skip_dirs=tuple(all_skip),
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        incremental=args.incremental,
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None

    # Rich diagnostic summary
    total_nodes = len(graph.nodes)
    total_edges = len(graph.edges)

    # Count nodes by kind
    kind_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1

    source_kinds = {"python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
                    "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
                    "kotlin", "scala", "haskell", "lean", "function", "class",
                    "struct", "method", "interface"}
    source_nodes = sum(v for k, v in kind_counts.items() if k in source_kinds)
    doc_nodes = sum(v for k, v in kind_counts.items() if k in {"markdown", "rst", "html", "text", "concept", "section"})

    print(f"Scanned {total_nodes} nodes, {total_edges} edges  ->  {output_path}")
    print(f"  Validation   : PASS {validation.format} nodes={validation.node_count} edges={validation.edge_count}")
    if status.repaired:
        print("  Repair       : incremental scan was invalid; promoted a clean full rebuild")
    print(f"  Source nodes : {source_nodes}  |  Doc nodes : {doc_nodes}  |  Other : {total_nodes - source_nodes - doc_nodes}")
    if all_skip:
        print(f"  Excluded dirs: {', '.join(all_skip)}")
    top_kinds = sorted(kind_counts.items(), key=lambda kv: -kv[1])[:8]
    print("  Top kinds    : " + "  ".join(f"{k}={v}" for k, v in top_kinds))
    if source_nodes == 0:
        print()
        print("  !  WARNING: zero source nodes found. Possible causes:")
        print("     * All source files are inside excluded/skipped directories")
        print("     * The --directory flag points to the wrong root")
        print("     * max_nodes cap hit before source files were reached (try --max-nodes 5000)")
        print()
        print("  Tip: run  graphgraph doctor  for a full environment check.")



def cmd_ingest(args: argparse.Namespace) -> None:
    if args.input:
        input_path = Path(args.input)
    else:
        try:
            input_path = find_graph_path()
        except FileNotFoundError:
            raise FileNotFoundError("Could not find input graph. Specify --input explicitly.")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(input_path)
    validation = save_validated_graph(graph, output_path)
    print(
        f"Ingested {len(graph.nodes)} nodes, {len(graph.edges)} edges from {input_path} -> {output_path} "
        f"(validation PASS {validation.format})"
    )


def cmd_export(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    output_path = Path(args.output) if args.output else Path(str(graph_path).replace(".json", ".gg"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(graph_path)
    save_gg(graph, output_path)
    print(f"Exported {len(graph.nodes)} nodes, {len(graph.edges)} edges -> {output_path}")


def cmd_ontology(args: argparse.Namespace) -> None:
    for name, spec in DEFAULT_RELATIONS.items():
        if args.family and spec.family != args.family:
            continue
        weak = " weak" if spec.weak else ""
        print(f"{name}: family={spec.family} strength={spec.strength:g} direction={spec.direction}{weak} - {spec.description}")


def cmd_compare(args: argparse.Namespace) -> None:
    left = load_any(Path(args.left))
    right = load_any(Path(args.right))
    comparison = compare_graphs(left, right)
    data = {
        "left": comparison.left.__dict__,
        "right": comparison.right.__dict__,
        "shared_node_paths": comparison.shared_node_paths,
        "shared_edge_keys": comparison.shared_edge_keys,
        "left_only_edge_keys": comparison.left_only_edge_keys,
        "right_only_edge_keys": comparison.right_only_edge_keys,
        "shared_normalized_edges": comparison.shared_normalized_edges,
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_cache(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if getattr(args, "graph", None) else None
    cache_file = (graph_path.parent / "kv_cache.json") if graph_path else Path(".graphgraph") / "kv_cache.json"
    cache = TopologicalKVCache(cache_file)
    if getattr(args, "clear", False):
        n = cache.clear()
        print(f"Cleared {n} cache entries from {cache_file}")
    else:
        s = cache.stats()
        print(f"Cache: {s['entries']}/{s['max_entries']} entries  hits={s['hits']}  misses={s['misses']}  hit_rate={s['hit_rate_pct']}%")
        print(f"File: {cache_file}")


def cmd_eval(args: argparse.Namespace) -> None:
    tasks = load_eval_tasks(Path(args.tasks))
    results = evaluate_graph(Path(args.graph), tasks, max_nodes=args.max_nodes)
    print(results_to_json(results))


def cmd_frontends(_args: argparse.Namespace) -> None:
    data = [cap.__dict__ for cap in available_frontends()]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_traversal(args: argparse.Namespace) -> None:
    if args.query_class:
        print(json.dumps(traversal_policy(args.query_class).__dict__, indent=2, ensure_ascii=False))
        return
    print(json.dumps({name: policy.__dict__ for name, policy in POLICIES.items()}, indent=2, ensure_ascii=False))


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
            "args": ["run", "--project", root, "graphgraph-mcp"],
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
            "1. **Zero-Exploration Contract:** Immediately check if `.graphgraph/graph.json` exists in the workspace. "
            "If it does not exist, immediately run `graphgraph scan --depth symbols --docs` to generate it. "
            "Do NOT run custom shell listings or file-discovery loops.\n"
            "2. **Context Compilation -- preferred (no node IDs needed):** Call `graphgraph/query_context` with a "
            "natural-language query. It auto-discovers anchors and returns a ready packet.\n"
            "3. **Context Compilation -- when you know node IDs:** Call `graphgraph/search_nodes` to confirm the ID, "
            "then `graphgraph/final_packet` with the confirmed IDs.\n"
            "4. **Zero-Hallucination Reasoning:** Rely *only* on the compressed topological packet returned by GraphGraph "
            "to understand the project structure, imports, and calls.\n"
            "5. **No Direct Graph File Inspection:** NEVER read `.graphgraph/graph.json` directly. "
            "If you need to verify the graph, call `graphgraph/validate_packet` or trust the scanner output.\n\n"
            "### Available MCP Tools\n"
            "* **`graphgraph/query_context`**: **Preferred.** Natural-language query -> auto-discovered anchors -> graph packet. No node IDs needed.\n"
            "* **`graphgraph/search_nodes`**: Find node IDs by label, path, or kind substring. Use before `final_packet`.\n"
            "* **`graphgraph/final_packet`**: Render compressed context packet from known anchor node IDs.\n"
            "* **`graphgraph/project_status`**: Validate the graph, summarize code/doc balance, package metadata, and optional runtime probes.\n"
            "* **`graphgraph/plan_context`**: Pass `query_class` to plan the expansion depth.\n"
            "* **`graphgraph/build_graph`**: Scan a directory. Accepts `exclude_dirs` to skip large external dirs.\n\n"
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
        "GraphGraph is installed for native codebase context retrieval in Codex, Antigravity, and CLI workflows. Use it to orient on code structure before broad source searches.\n\n"
        "> [!IMPORTANT]\n"
        "> **DEFAULT PATH**\n"
        "> Prefer the MCP `graphgraph/query_context` tool when available. If MCP is unavailable, run `graphgraph context \"<query>\" --query-class <class>`; it builds `.graphgraph/graph.json` if missing, then returns a packet.\n\n"
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
        "| `build_graph` | Build `.graphgraph/graph.json`; accepts `exclude_dirs`. |\n"
        "| `validate_packet` | Validate a rendered packet, not a saved graph JSON file. |\n\n"
        "## CLI Fallback\n\n"
        "- One-step default: `graphgraph context \"<query>\" --query-class subsystem_summary --show-stats`\n"
        "- Project status: `graphgraph status --probe`\n"
        "- Force rebuild: `graphgraph context \"<query>\" --rebuild --scan-max-nodes 5000 --show-stats`\n"
        "- Focus scope: `graphgraph context \"<query>\" --scope src/graphgraph/retrieval --query-class blast_radius`\n"
        "- Validate graph: `graphgraph validate-graph`\n"
        "- Validate packet from stdin: `graphgraph query \"<query>\" --packet doc_summary | graphgraph validate`\n\n"
        "## Query Classes\n\n"
        "| Query Class | Description / Example Question | Hops | Format | Reason |\n"
        "| :--- | :--- | :---: | :--- | :--- |\n"
        "| `direct_lookup` | Specific file/symbol details | 1 | `gg_max_hybrid` | inline source facts |\n"
        "| `reverse_lookup` | References/callers/users of a symbol | 1 | `gg_max_hybrid` | reverse evidence |\n"
        "| `subsystem_summary` | High-level status or architecture area | 1 | `gg_max_hybrid` | balanced summary |\n"
        "| `blast_radius` | What changes if this is modified? | 2 | `gg_max` | topology-first |\n"
        "| `multi_hop_path` | How does A reach/call B? | 2 | `gg_max` | path evidence |\n"
        "| `doc_summary` | README/docs/install/usage summaries | 1 | `doc_summary` | grounded docs, no topology |\n"
        "| `negative_query` | Is this isolated/missing? | 1 | `semantic_arrow` | minimal evidence |\n\n"
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
