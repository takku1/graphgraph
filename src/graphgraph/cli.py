from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import Query
from .eval import evaluate_graph, load_eval_tasks, results_to_json
from .frontends import available_frontends
from .io import load_graph, load_any, save_graph, save_gg, find_graph_path, find_policies_path, load_policies
from .metrics import compare_graphs
from .ontology import DEFAULT_RELATIONS
from .packets import render_packet
from .planner import choose_packet
from .policies import render_policy_packet, select_policies
from .retrieval import retrieve_context
from .scanner import scan_directory
from .semantic import load_semantic_triples, merge_semantic_triples
from .temporal import graph_at
from .traversal import POLICIES, traversal_policy
from .validate import validate_packet


def cmd_plan(args: argparse.Namespace) -> None:
    choice = choose_packet(args.query_class)
    print(f"{choice.hops}hop {choice.packet}: {choice.reason}")


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
    graph_path = find_graph_path()
    if graph_path and graph_path.exists():
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
    else:
        print("  Active Graph: No graph.json found in .graphgraph/ or graphify-out/")

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
    choice = choose_packet(args.query_class)
    
    from .cache import TopologicalKVCache, compute_cache_key
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(args.starts, args.query_class, choice.hops, choice.packet)
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    graph = load_any(graph_path)
    as_of = getattr(args, "as_of", None)
    if as_of:
        graph = graph_at(graph, as_of)
    starts = args.starts
    nodes, edges = graph.expand(starts, hops=choice.hops)
    packet = render_packet(graph, nodes, edges, choice.packet)
    cache.set(graph_path, cache_key, packet)
    print(packet)


def cmd_final(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    policies_path = Path(args.policies) if args.policies else find_policies_path()

    if getattr(args, "stable_skeleton", False):
        graph = load_any(graph_path)
        as_of = getattr(args, "as_of", None)
        if as_of:
            graph = graph_at(graph, as_of)
        max_nodes = getattr(args, "max_nodes", 100) or 100
        pr = graph.pagerank()
        top_nodes = sorted(pr, key=pr.get, reverse=True)[:max_nodes]
        top_set = set(top_nodes)
        skeleton_edges = [e for e in graph.edges if e.active and e.source in top_set and e.target in top_set]
        from .packets import render_gg_max
        graph_packet = render_gg_max(graph, top_set, skeleton_edges)
        print(graph_packet)
        return

    if not args.starts:
        print("Error: --starts is required unless --stable-skeleton is specified.", file=sys.stderr)
        sys.exit(1)
    if not args.query_class:
        print("Error: --query-class is required unless --stable-skeleton is specified.", file=sys.stderr)
        sys.exit(1)

    choice = choose_packet(args.query_class, args.query)
    from .cache import TopologicalKVCache, compute_cache_key
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        args.starts,
        args.query_class,
        choice.hops,
        choice.packet + f"|cli_final|{args.query}|{args.path}|{args.tag}"
    )
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    graph = load_any(graph_path)
    as_of = getattr(args, "as_of", None)
    if as_of:
        graph = graph_at(graph, as_of)
    policies = load_policies(policies_path) if policies_path else []
    query = Query(
        text=args.query,
        query_class=args.query_class,
        paths=tuple(args.path),
        tags=tuple(args.tag),
    )
    nodes, edges = graph.expand(args.starts, hops=choice.hops)
    selected = select_policies(policies, query)
    policy_packet = render_policy_packet(selected, compact=True)
    graph_packet = render_packet(graph, nodes, edges, choice.packet)
    
    out_lines = []
    if policy_packet:
        out_lines.append("CONSTRAINTS:")
        out_lines.append(policy_packet)
        out_lines.append("\nGRAPH:")
    out_lines.append(graph_packet)
    final_output = "\n".join(out_lines)
    
    cache.set(graph_path, cache_key, final_output)
    print(final_output)


def cmd_query(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    choice = choose_packet(args.query_class, args.query)
    
    from .cache import TopologicalKVCache, compute_cache_key
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        [args.query],
        args.query_class,
        args.hops if args.hops is not None else choice.hops,
        f"cli_query|{args.anchor_limit}|{args.max_nodes}|{args.scope}|{args.packet}|{args.show_anchors}"
    )
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    graph = load_any(graph_path)
    result = retrieve_context(
        graph,
        args.query,
        args.query_class,
        hops=args.hops if args.hops is not None else choice.hops,
        anchor_limit=args.anchor_limit,
        max_nodes=args.max_nodes,
        scopes=tuple(args.scope),
    )
    if not result.starts:
        print("No matching graph anchors found for query.")
        return
        
    out_lines = []
    if args.show_anchors:
        out_lines.append("ANCHORS:")
        shown = args.anchor_limit if args.anchor_limit is not None else len(result.starts)
        for match in result.matches[:shown]:
            node = match.node
            out_lines.append(f"- {node.id} {node.label} [{node.kind}] {node.path} score={match.score:g}")
        out_lines.append("\nGRAPH:")
        
    out_lines.append(render_packet(graph, result.nodes, result.edges, args.packet or choice.packet))
    output_str = "\n".join(out_lines)
    cache.set(graph_path, cache_key, output_str)
    print(output_str)


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
        communities=args.communities,
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


def cmd_merge_semantic(args: argparse.Namespace) -> None:
    graph = load_any(Path(args.graph))
    triples = load_semantic_triples(Path(args.triples))
    merged = merge_semantic_triples(graph, triples)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_graph(merged, output)
    print(f"Merged {len(triples)} semantic triples -> {len(merged.nodes)} nodes, {len(merged.edges)} edges -> {output}")


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graphgraph")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--query-class", required=True)
    plan.set_defaults(func=cmd_plan)

    render = sub.add_parser("render")
    render.add_argument("--graph")
    render.add_argument("--query-class", required=True)
    render.add_argument("--starts", nargs="+", required=True)
    render.add_argument("--as-of", help="Use a point-in-time graph view for ISO timestamp/date.")
    render.set_defaults(func=cmd_render)

    final = sub.add_parser("final")
    final.add_argument("--graph")
    final.add_argument("--policies")
    final.add_argument("--query", default="")
    final.add_argument("--query-class", required=False)
    final.add_argument("--starts", nargs="+", required=False)
    final.add_argument("--path", action="append", default=[])
    final.add_argument("--tag", action="append", default=[])
    final.add_argument("--as-of", help="Use a point-in-time graph view for ISO timestamp/date.")
    final.add_argument("--stable-skeleton", action="store_true", help="Compile a stable, PageRank-based skeleton of top architectural nodes to use as a static prompt cache prefix.")
    final.add_argument("--max-nodes", type=int, default=100, help="Max nodes for the stable skeleton (default: 100).")
    final.set_defaults(func=cmd_final)

    query = sub.add_parser("query", help="Retrieve a query-specific graph context packet without preselecting node IDs.")
    query.add_argument("query", help="Natural-language query used to find graph anchors.")
    query.add_argument("--graph")
    query.add_argument("--query-class", default="blast_radius")
    query.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg_max", "gg_max_hybrid", "svo", "doc_summary"])
    query.add_argument("--hops", type=int)
    query.add_argument("--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class.")
    query.add_argument("--max-nodes", type=int)
    query.add_argument("--as-of", help="Use a point-in-time graph view for ISO timestamp/date.")
    query.add_argument("--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable.")
    query.add_argument("--show-anchors", action="store_true")
    query.set_defaults(func=cmd_query)

    validate = sub.add_parser("validate")
    validate.add_argument("--packet")
    validate.set_defaults(func=cmd_validate)

    scan = sub.add_parser("scan", help="Scan a directory and build a graph from import relationships.")
    scan.add_argument("--directory", "-d", help="Root directory to scan (default: cwd).")
    scan.add_argument("--output", "-o", help="Output graph JSON path (default: .graphgraph/graph.json).")
    scan.add_argument("--max-nodes", type=int, default=500, help="Max nodes to collect (default: 500).")
    scan.add_argument("--generic-mentions", action="store_true", default=False,
                      help="Add weak 'references' edges for any file that mentions another file's stem name.")
    scan.add_argument("--skip-dirs", nargs="*", metavar="DIR",
                      help="Additional directory names to skip (e.g. --skip-dirs spikes test-inputs).")
    scan.add_argument("--depth", choices=["files", "symbols"], default="files",
                      help="'files' (default): one node per file. 'symbols': adds function/class/struct nodes.")
    scan.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto",
                      help="Symbol extraction frontend for --depth symbols. auto prefers Tree-sitter when available.")
    scan.add_argument("--docs", action="store_true", help="Extract document sections and concept nodes.")
    scan.add_argument("--communities", action="store_true", help="Add deterministic path/scope community summary nodes.")
    scan.add_argument("--incremental", action="store_true", default=True, help="Use hash-based incremental scanner (default: True).")
    scan.add_argument("--no-incremental", action="store_false", dest="incremental", help="Disable incremental scanning.")
    scan.set_defaults(func=cmd_scan)

    ingest = sub.add_parser("ingest", help="Ingest any graph format (.gg, .json, .csv, .tsv) into .graphgraph/graph.json.")
    ingest.add_argument("--input", "-i", help="Input file (.gg, .json, .csv, .tsv). Auto-detected if omitted.")
    ingest.add_argument("--output", "-o", help="Output path (default: .graphgraph/graph.json).")
    ingest.set_defaults(func=cmd_ingest)

    export = sub.add_parser("export", help="Export current graph to native .gg adjacency-list format.")
    export.add_argument("--graph", help="Source graph path. Auto-detected if omitted.")
    export.add_argument("--output", "-o", help="Output .gg path (default: same dir as source).")
    export.set_defaults(func=cmd_export)

    ontology = sub.add_parser("ontology", help="List native relation ontology and traversal weights.")
    ontology.add_argument("--family", help="Filter by relation family.")
    ontology.set_defaults(func=cmd_ontology)

    compare = sub.add_parser("compare", help="Compare two graph files by size, relation types, and overlap.")
    compare.add_argument("--left", required=True)
    compare.add_argument("--right", required=True)
    compare.set_defaults(func=cmd_compare)

    semantic = sub.add_parser("merge-semantic", help="Merge grounded semantic triples into a graph with provenance.")
    semantic.add_argument("--graph", required=True)
    semantic.add_argument("--triples", required=True)
    semantic.add_argument("--output", required=True)
    semantic.set_defaults(func=cmd_merge_semantic)

    eval_cmd = sub.add_parser("eval", help="Evaluate retrieval recall and packet token cost against task expectations.")
    eval_cmd.add_argument("--graph", required=True)
    eval_cmd.add_argument("--tasks", required=True)
    eval_cmd.add_argument("--max-nodes", type=int)
    eval_cmd.set_defaults(func=cmd_eval)

    frontends = sub.add_parser("frontends", help="List extraction frontend capabilities.")
    frontends.set_defaults(func=cmd_frontends)

    traversal = sub.add_parser("traversal", help="List query-class traversal policies.")
    traversal.add_argument("--query-class")
    traversal.set_defaults(func=cmd_traversal)

    doctor = sub.add_parser("doctor", help="Run system diagnostics and verify environment, tools, credentials, and MCP configs.")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
