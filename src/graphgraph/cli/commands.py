from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..cache import TopologicalKVCache, compute_cache_key
from ..eval import evaluate_graph, load_eval_tasks, results_to_json
from ..frontends import available_frontends
from ..io import load_any, save_graph, save_gg, find_graph_path, find_policies_path
from ..metrics import compare_graphs
from ..ontology import DEFAULT_RELATIONS
from ..packets import render_packet
from ..planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph
from ..scanner import scan_directory
from ..services import render_final_packet, render_query_context, render_stable_skeleton
from ..traversal import POLICIES, traversal_policy
from ..validate import validate_packet


def cmd_plan(args: argparse.Namespace) -> None:
    plan = plan_context(args.query_class, getattr(args, "query", ""))
    print(
        f"{plan.hops}hop {plan.direction} {plan.packet} "
        f"n={plan.node_budget} anchors={plan.anchor_limit}: {plan.reason}"
    )


def cmd_doctor(args: argparse.Namespace) -> None:
    import platform
    import sys
    import os
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
        import tree_sitter
        import tree_sitter_language_pack
        print("  tree-sitter: Installed (OK)")
    except ImportError:
        print("  tree-sitter: Missing (WARN - AST symbols scanning disabled)")

    try:
        import keyring
        print("  keyring: Installed (OK)")
    except ImportError:
        print("  keyring: Missing (WARN - Windows Credential Manager integration disabled)")

    try:
        import tiktoken
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
            print(f"    - Nodes: {len(nodes)}")
            print(f"    - Edges: {len(edges)}")
            has_symbols = any(n.kind in ("function", "class", "struct", "method") for n in nodes)
            print(f"    - Symbol-level scanner info: {'Yes (OK)' if has_symbols else 'No (Files only)'}")
        except Exception as e:
            print(f"    - Error loading graph: {e}")
    except FileNotFoundError:
        print("  Active Graph: No graph file found in .graphgraph/ or graphify-out/")

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
                        print(f"  Claude Desktop: Configured (OK)")
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
    starts = args.starts
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


def cmd_validate(args: argparse.Namespace) -> None:
    packet = Path(args.packet).read_text(encoding="utf-8") if args.packet else sys.stdin.read()
    result = validate_packet(packet)
    status = "PASS" if result.ok else "FAIL"
    print(f"{status} {result.format} nodes={result.node_count} edges={result.edge_count}")
    for error in result.errors:
        print(f"- {error}")


def cmd_scan(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    previous_graph_path = output_path if args.incremental else None
    manifest_path = (output_path.parent / "manifest.json") if args.incremental else None
    graph = scan_directory(
        root,
        max_nodes=args.max_nodes,
        generic_mentions=args.generic_mentions,
        skip_dirs=args.skip_dirs or [],
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        previous_graph_path=previous_graph_path,
        manifest_path=manifest_path,
    )
    save_graph(graph, output_path)
    print(f"Scanned {len(graph.nodes)} nodes and {len(graph.edges)} edges from {root.resolve()} -> {output_path}")


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
    save_graph(graph, output_path)
    print(f"Ingested {len(graph.nodes)} nodes, {len(graph.edges)} edges from {input_path} -> {output_path}")


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
