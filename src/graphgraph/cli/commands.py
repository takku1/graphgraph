from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..eval import evaluate_graph, load_eval_tasks, results_to_json
from ..frontends import available_frontends
from ..graph.ontology import DEFAULT_RELATIONS
from ..graph.traversal import POLICIES, traversal_policy
from ..io import find_graph_path, find_policies_path, load_any, save_gg, save_validated_graph, validate_graph_file
from ..metrics import compare_graphs
from ..packets import render_packet
from ..packets.validation import validate_any
from ..planning import (
    compute_subgraph_stats,
    plan_context,
    profile_graph_shape,
    recommend_node_budget,
    refine_plan_for_subgraph,
)
from ..retrieval import apply_shape_budget
from ..runtime.cache import TopologicalKVCache, compute_cache_key
from ..services import render_final_packet, render_query_context, render_source_snippets, render_stable_skeleton
from ..services.context import resolve_start_nodes
from ..services.native import build_project_status, graph_shape, render_native_context, scan_validated_graph
from .install import cmd_install as cmd_install


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
        print("  keyring: Installed (OK - optional external benchmark credential storage available)")
    except ImportError:
        print("  keyring: Missing (OK - only needed for optional external benchmark credentials)")

    try:
        import tiktoken  # noqa: F401
        print("  tiktoken: Installed (OK)")
    except ImportError:
        print("  tiktoken: Missing (WARN - using approximate token count)")
        
    # 3. Optional provider credentials. GraphGraph's local skill/MCP/CLI
    # workflow does not need these; they only matter for paid external model
    # benchmark scripts.
    print("\n[Optional External Benchmark Credentials]")
    print("  Local GraphGraph scan/query/packet workflows do not require provider API keys.")
    try:
        import keyring
        openai_key = keyring.get_password("OpenAI", "API_KEY")
        if openai_key:
            masked = openai_key[:7] + "..." + openai_key[-4:] if len(openai_key) > 10 else "..."
            print(f"  OpenAI API Key: Found for optional benchmarks ({masked})")
        else:
            env_key = os.environ.get("OPENAI_API_KEY")
            if env_key:
                masked = env_key[:7] + "..." + env_key[-4:] if len(env_key) > 10 else "..."
                print(f"  OpenAI API Key: Found in environment for optional benchmarks ({masked})")
            else:
                print("  OpenAI API Key: Not configured (OK; external OpenAI benchmarks will be skipped)")
                
        gemini_key = keyring.get_password("Gemini", "API_KEY")
        if gemini_key:
            masked = gemini_key[:7] + "..." + gemini_key[-4:] if len(gemini_key) > 10 else "..."
            print(f"  Gemini API Key: Found for optional benchmarks ({masked})")
        else:
            env_key = os.environ.get("GEMINI_API_KEY")
            if env_key:
                masked = env_key[:7] + "..." + env_key[-4:] if len(env_key) > 10 else "..."
                print(f"  Gemini API Key: Found in environment for optional benchmarks ({masked})")
            else:
                print("  Gemini API Key: Not configured (OK; external Gemini benchmarks will be skipped)")
    except Exception as e:
        print(f"  Credential lookup skipped/failed (OK for local GraphGraph use): {e}")
        
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
        print("    - Build one with: graphgraph scan --directory . --depth symbols --docs --output .graphgraph/graph.gg")
        print("    - Import external graphs explicitly with: graphgraph ingest --input <path> --output .graphgraph/graph.gg")


    # 5. MCP Settings Verification (per client, not a single generic "OK").
    print("\n[MCP Server Integration]")

    def _report_mcp_client(label: str, config_path: Path | None, missing_hint: str) -> bool:
        """Print whether the graphgraph MCP server is registered for one client."""
        if config_path is None:
            print(f"  {label}: config location unavailable on this platform")
            return False
        if not config_path.exists():
            print(f"  {label}: not configured ({missing_hint})")
            return False
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  {label}: found config but failed to parse: {e}")
            return False
        servers = data.get("mcpServers", {})
        if "graphgraph" in servers:
            print(f"  {label}: Configured (OK)  [{config_path}]")
            print(f"    - Command: {servers['graphgraph'].get('command')}")
            return True
        print(f"  {label}: config present but 'graphgraph' server not registered ({missing_hint})")
        return False

    home = Path.home()
    appdata = os.environ.get("APPDATA")
    desktop_cfg = (Path(appdata) / "Claude" / "claude_desktop_config.json") if appdata else None

    code_global = _report_mcp_client(
        "Claude Code (user ~/.claude.json)",
        home / ".claude.json",
        "run: graphgraph install --platform claude-code",
    )
    code_project = _report_mcp_client(
        "Claude Code (project ./.mcp.json)",
        Path(".mcp.json"),
        "run: graphgraph install --project --platform claude-code",
    )
    desktop = _report_mcp_client(
        "Claude Desktop",
        desktop_cfg,
        "run: graphgraph install --platform claude-desktop",
    )
    codex_project = _report_mcp_client(
        "Codex plugin (project ./plugins/graphgraph/.mcp.json)",
        Path("plugins/graphgraph/.mcp.json"),
        "run: graphgraph install --project --platform codex",
    )
    cursor_project = _report_mcp_client(
        "Cursor (project ./.cursor/mcp.json)",
        Path(".cursor/mcp.json"),
        "run: graphgraph install --project --platform cursor",
    )
    cursor_global = _report_mcp_client(
        "Cursor (user ~/.cursor/mcp.json)",
        home / ".cursor" / "mcp.json",
        "run: graphgraph install --platform cursor",
    )
    gemini_project = _report_mcp_client(
        "Gemini/Antigravity (project ./.gemini/settings.json)",
        Path(".gemini/settings.json"),
        "run: graphgraph install --project --platform gemini",
    )
    gemini_global = _report_mcp_client(
        "Gemini/Antigravity (user ~/.gemini/settings.json)",
        home / ".gemini" / "settings.json",
        "run: graphgraph install --platform gemini",
    )

    if not (
        code_global or code_project or desktop
        or codex_project or cursor_project or cursor_global
        or gemini_project or gemini_global
    ):
        print("  [!] No client has the graphgraph MCP server registered.")
        print("      In a Claude Code session, MCP tools will be unavailable; use the `graphgraph` CLI instead.")


def cmd_render(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    starts = resolve_start_nodes(graph, args.starts)
    plan = plan_context(args.query_class, max_nodes=args.max_nodes)
    if args.max_nodes is None:
        plan = apply_shape_budget(graph, plan, getattr(args, "query", ""))
    nodes, edges = graph.expand(starts, hops=plan.hops, max_nodes=plan.node_budget, direction=plan.direction)
    plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, nodes, edges))
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(args.starts, args.query_class, plan.hops, f"{plan.packet}|render|{plan.planner_version}|{plan.node_budget}|{plan.direction}")
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    packet = render_packet(graph, nodes, edges, plan.packet)
    cache.set(
        graph_path,
        cache_key,
        packet,
        node_ids=nodes,
        paths=[graph.nodes[node_id].path for node_id in nodes if node_id in graph.nodes and graph.nodes[node_id].path],
    )
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
        hops=args.hops,
        anchor_limit=args.anchor_limit,
        max_nodes=args.max_nodes,
        scopes=tuple(args.scope),
        show_anchors=args.show_anchors,
        cache_namespace="cli_query",
    )
    print(output)


def cmd_snippets(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    print(
        render_source_snippets(
            starts=list(args.starts),
            graph_path=graph_path,
            context_lines=args.context_lines,
            max_lines=args.max_lines,
        )
    )


def cmd_context(args: argparse.Namespace) -> None:
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = tuple(skip_dirs + [d for d in exclude_dirs if d not in skip_dirs])
    include_dirs: list[str] = list(getattr(args, "include", None) or [])
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
        include_dirs=tuple(include_dirs),
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        history=args.history,
        generic_mentions=args.generic_mentions,
        incremental=args.incremental,
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
    if args.packet:
        packet = Path(args.packet).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        packet = sys.stdin.read()
    else:
        packet = ""

    # When no packet/stdin is supplied, honor the documented "auto-detect saved
    # graph JSON" behavior instead of failing on empty input.
    if not packet.strip():
        try:
            graph_path = find_graph_path()
        except FileNotFoundError:
            graph_path = None
        if graph_path is not None:
            print(f"No packet supplied; auto-detected saved graph: {graph_path}")
            result = validate_graph_file(graph_path)
            status = "PASS" if result.ok else "FAIL"
            print(f"{status} {result.format} nodes={result.node_count} edges={result.edge_count} path={graph_path}")
            for error in result.errors:
                print(f"- {error}")
            if not result.ok:
                sys.exit(1)
            return
        print("FAIL no input: pipe a packet via stdin, pass --packet <file>, or run `graphgraph validate-graph`.")
        print("  (no saved graph found under .graphgraph/ to auto-detect)")
        sys.exit(1)
        return

    result = validate_any(packet)
    status = "PASS" if result.ok else "FAIL"
    print(f"{status} {result.format} nodes={result.node_count} edges={result.edge_count}")
    for error in result.errors:
        print(f"- {error}")
    if not result.ok:
        sys.exit(1)


def cmd_validate_graph(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    result = validate_graph_file(graph_path)
    status = "PASS" if result.ok else "FAIL"
    print(f"{status} {result.format} nodes={result.node_count} edges={result.edge_count} path={graph_path}")
    for error in result.errors:
        print(f"- {error}")
    if not result.ok:
        sys.exit(1)


def cmd_scan(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")
    # Merge --skip-dirs and --exclude into a single list
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = skip_dirs + [d for d in exclude_dirs if d not in skip_dirs]
    include_dirs: list[str] = list(getattr(args, "include", None) or [])

    status = scan_validated_graph(
        directory=root,
        output_path=output_path,
        max_nodes=args.max_nodes,
        generic_mentions=args.generic_mentions,
        skip_dirs=tuple(all_skip),
        include_dirs=tuple(include_dirs),
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        history=args.history,
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
    if include_dirs:
        print(f"  Force-included: {', '.join(include_dirs)}")
    # Surface default-skip directories that actually held content, so real
    # project dirs literally named e.g. `build`/`out` are not dropped silently.
    # Never-real infra/VCS/tooling dirs are excluded from the note to keep it
    # low-noise; ambiguous names (build, out, dist, target, archive, ...) remain.
    from ..scanner.files import SKIP_DIRS, find_pruned_dirs
    _NEVER_REPORT = {
        ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "env", ".tox",
        ".mypy_cache", ".pytest_cache", ".eggs", "site-packages", "node_modules",
        ".graphgraph", ".cache", ".next", ".nuxt", "graphify-out",
        ".code-review-graph", ".artifacts",
    }
    default_skipped = (SKIP_DIRS - set(all_skip) - set(include_dirs)) - _NEVER_REPORT
    pruned = find_pruned_dirs(root, frozenset(default_skipped))
    if pruned:
        print(
            "  Auto-skipped : "
            + ", ".join(sorted(pruned))
            + "  (default rule; re-scan with --include <dir> to keep any of these)"
        )
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
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(input_path, normalize_external_refs=True)
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


