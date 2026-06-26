from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Query
from .io import load_graph, load_policies, save_graph, find_graph_path, find_policies_path, find_graphify_path, merge_graphify
from .packets import render_packet
from .planner import choose_packet
from .policies import render_policy_packet, select_policies
from .scanner import scan_directory
from .validate import validate_packet


def cmd_plan(args: argparse.Namespace) -> None:
    choice = choose_packet(args.query_class)
    print(f"{choice.hops}hop {choice.packet}: {choice.reason}")


def cmd_render(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_graph(graph_path)
    choice = choose_packet(args.query_class)
    starts = args.starts
    nodes, edges = graph.expand(starts, hops=choice.hops)
    print(render_packet(graph, nodes, edges, choice.packet))


def cmd_final(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    policies_path = Path(args.policies) if args.policies else find_policies_path()
    graph = load_graph(graph_path)
    policies = load_policies(policies_path) if policies_path else []
    query = Query(
        text=args.query,
        query_class=args.query_class,
        paths=tuple(args.path),
        tags=tuple(args.tag),
    )
    choice = choose_packet(args.query_class)
    nodes, edges = graph.expand(args.starts, hops=choice.hops)
    selected = select_policies(policies, query)
    policy_packet = render_policy_packet(selected, compact=True)
    graph_packet = render_packet(graph, nodes, edges, choice.packet)
    if policy_packet:
        print("CONSTRAINTS:")
        print(policy_packet)
        print("\nGRAPH:")
    print(graph_packet)


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
    graph = scan_directory(
        root,
        max_nodes=args.max_nodes,
        generic_mentions=args.generic_mentions,
        skip_dirs=args.skip_dirs or [],
        depth=args.depth,
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
            input_path = Path("graphify-out/graph.json")
            if not input_path.exists():
                raise FileNotFoundError("Could not find input graph. Specify --input explicitly.")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_graph(input_path)
    save_graph(graph, output_path)
    print(f"Ingested and normalized {len(graph.nodes)} nodes and {len(graph.edges)} edges to {output_path}")


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
    render.set_defaults(func=cmd_render)

    final = sub.add_parser("final")
    final.add_argument("--graph")
    final.add_argument("--policies")
    final.add_argument("--query", default="")
    final.add_argument("--query-class", required=True)
    final.add_argument("--starts", nargs="+", required=True)
    final.add_argument("--path", action="append", default=[])
    final.add_argument("--tag", action="append", default=[])
    final.set_defaults(func=cmd_final)

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
    scan.set_defaults(func=cmd_scan)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--input")
    ingest.add_argument("--output")
    ingest.set_defaults(func=cmd_ingest)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
