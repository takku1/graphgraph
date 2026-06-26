from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .cli import cmd_final
from .core import Query
from .io import load_graph, load_policies, save_graph, find_graph_path, find_policies_path, find_graphify_path, merge_graphify
from .packets import render_packet
from .planner import choose_packet
from .policies import render_policy_packet, select_policies
from .scanner import scan_directory
from .validate import validate_packet


SERVER_INFO = {"name": "graphgraph", "version": "0.1.0"}


TOOLS = [
    {
        "name": "plan_context",
        "description": (
            "Choose the empirically-measured optimal graph packet strategy for a query class. "
            "Returns hops, packet format, and rationale. Query classes: direct_lookup, "
            "reverse_lookup, multi_hop_path, blast_radius, subsystem_summary, negative_query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_class": {"type": "string"},
            },
            "required": ["query_class"],
        },
    },
    {
        "name": "final_packet",
        "description": (
            "Render a final LLM-facing packet: optional scoped policies plus an ultra-compact "
            "graph packet. Use starts to name anchor nodes (file paths or node IDs). "
            "graphgraph packets use 40-60% fewer tokens than verbose JSON or graphify output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string", "description": "Path to graph JSON; auto-detected if omitted."},
                "policies_path": {"type": "string", "description": "Path to policies JSON; auto-detected if omitted."},
                "query": {"type": "string"},
                "query_class": {"type": "string"},
                "starts": {"type": "array", "items": {"type": "string"}, "description": "Anchor node IDs."},
                "paths": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "max_nodes": {"type": "integer", "description": "Token budget cap (node count). Default: unlimited."},
            },
            "required": ["query_class", "starts"],
        },
    },
    {
        "name": "validate_packet",
        "description": "Mechanically validate a graphgraph packet (lowlevel, sql, semantic_arrow, or gg_max).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "packet": {"type": "string"},
            },
            "required": ["packet"],
        },
    },
    {
        "name": "build_graph",
        "description": (
            "Scan a directory (or ingest an existing graph JSON) and save a normalized graph "
            "to .graphgraph/graph.json. Works on any codebase or documentation tree. "
            "Detects import/dependency edges for Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby; "
            "link edges for Markdown, RST, and HTML. "
            "Optionally enable generic_mentions to extract weak 'references' edges from any text file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory to scan. Defaults to current working directory."},
                "input_graph": {"type": "string", "description": "Path to an existing graph JSON (e.g. graphify output) to ingest instead of scanning."},
                "output_path": {"type": "string", "description": "Where to save the graph. Defaults to .graphgraph/graph.json."},
                "max_nodes": {"type": "integer", "description": "Max file/node count during directory scan. Default: 500."},
                "generic_mentions": {"type": "boolean", "description": "Also add weak 'references' edges for any file that mentions another file's name. Useful for docs-heavy repos. Default: false."},
                "skip_dirs": {"type": "array", "items": {"type": "string"}, "description": "Extra directory names to exclude (beyond built-ins). E.g. ['spikes', 'test-inputs']."},
                "depth": {"type": "string", "enum": ["files", "symbols"], "description": "'files' (default): one node per file. 'symbols': adds function/class/struct nodes with call edges (graphify-level depth)."},
            },
        },
    },
    {
        "name": "search_nodes",
        "description": (
            "Search nodes in a graph by label, path, or kind. Returns a list of matching node IDs "
            "and metadata. Use this to find the right anchor node IDs before calling final_packet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match against node label, path, or kind."},
                "graph_path": {"type": "string", "description": "Path to graph JSON; auto-detected if omitted."},
                "limit": {"type": "integer", "description": "Max results to return. Default: 20."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "describe_formats",
        "description": "List available packet formats with token-cost benchmarks to help choose the right one.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


FORMAT_TABLE = [
    {"format": "gg_max", "relative_tokens": "1.00x", "description": "Token floor: integer node indices + bracket delimiters. Best for topology queries."},
    {"format": "lowlevel", "relative_tokens": "1.03x", "description": "XML-tagged adjacency. Slightly more tokens than gg_max."},
    {"format": "sql", "relative_tokens": "1.38x", "description": "Table row layout. Best for 1-hop direct/reverse lookups (no relation-map overhead)."},
    {"format": "semantic_arrow", "relative_tokens": "1.49x", "description": "Subject-verb-object arrows. Matches LLM attention priors; relation name is inline."},
    {"format": "gg_max_hybrid", "relative_tokens": "~1.6x", "description": "gg_max + inline node summaries/facts. Best for subsystem summaries."},
    {"format": "hybrid", "relative_tokens": "~2.3x", "description": "Markdown bullet lists. Readable but high overhead."},
    {"format": "json", "relative_tokens": "3.9-6.7x", "description": "Raw JSON. Never use as LLM wire format for graphs."},
]


def content(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def handle_initialize(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    }


def handle_tools_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {"tools": TOOLS}


def handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments") or {}
    if name == "plan_context":
        choice = choose_packet(str(args["query_class"]))
        return content(json.dumps({"hops": choice.hops, "packet": choice.packet, "reason": choice.reason}))
    if name == "final_packet":
        return content(build_final_packet(args))
    if name == "validate_packet":
        result = validate_packet(str(args["packet"]))
        return content(json.dumps({
            "ok": result.ok,
            "format": result.format,
            "node_count": result.node_count,
            "edge_count": result.edge_count,
            "errors": list(result.errors),
        }))
    if name == "build_graph":
        return content(handle_build_graph(args))
    if name == "search_nodes":
        return content(handle_search_nodes(args))
    if name == "describe_formats":
        return content(json.dumps(FORMAT_TABLE, indent=2))
    raise ValueError(f"unknown tool: {name}")


def build_final_packet(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    graph = load_graph(graph_path)

    policies_path_str = args.get("policies_path")
    policies_path = Path(policies_path_str) if policies_path_str else find_policies_path()
    policies = load_policies(policies_path) if policies_path else []

    query = Query(
        text=str(args.get("query", "")),
        query_class=str(args["query_class"]),
        paths=tuple(str(item) for item in args.get("paths", [])),
        tags=tuple(str(item) for item in args.get("tags", [])),
    )
    choice = choose_packet(query.query_class)
    starts = [str(item) for item in args["starts"]]
    max_nodes = args.get("max_nodes")
    nodes, edges = graph.expand(starts, hops=choice.hops, max_nodes=int(max_nodes) if max_nodes else None)

    selected = select_policies(policies, query)
    policy_packet = render_policy_packet(selected, compact=True)
    graph_packet = render_packet(graph, nodes, edges, choice.packet)

    validation = validate_packet(graph_packet)
    if not validation.ok:
        raise ValueError("generated graph packet failed validation: " + "; ".join(validation.errors))

    if not policy_packet:
        return graph_packet
    return f"CONSTRAINTS:\n{policy_packet}\n\nGRAPH:\n{graph_packet}"


def handle_build_graph(args: dict[str, Any]) -> str:
    input_graph_str = args.get("input_graph")
    output_path_str = args.get("output_path") or ".graphgraph/graph.json"
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if input_graph_str:
        graph = load_graph(Path(input_graph_str))
        save_graph(graph, output_path)
        return json.dumps({
            "action": "ingested",
            "source": input_graph_str,
            "output": str(output_path),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        })

    directory = Path(args.get("directory") or ".")
    max_nodes = int(args.get("max_nodes") or 500)
    generic_mentions = bool(args.get("generic_mentions", False))
    skip_dirs = [str(d) for d in args.get("skip_dirs") or []]
    depth = str(args.get("depth") or "files")
    graph = scan_directory(directory, max_nodes=max_nodes, generic_mentions=generic_mentions, skip_dirs=skip_dirs, depth=depth)

    save_graph(graph, output_path)
    return json.dumps({
        "action": "scanned",
        "directory": str(directory.resolve()),
        "output": str(output_path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    })


def handle_search_nodes(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    graph = load_graph(graph_path)

    q = str(args["query"]).lower()
    limit = int(args.get("limit") or 20)

    # Precompute degree so hub nodes float to the top of results.
    degree: dict[str, int] = {}
    for edge in graph.edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1

    matches = []
    for node in graph.nodes.values():
        if q in node.label.lower() or q in node.path.lower() or q in node.kind.lower():
            matches.append({
                "id": node.id,
                "label": node.label,
                "kind": node.kind,
                "path": node.path,
                "degree": degree.get(node.id, 0),
                "summary": node.summary,
            })

    matches.sort(key=lambda m: m["degree"], reverse=True)
    matches = matches[:limit]
    return json.dumps({"matches": matches, "total": len(matches)})


def dispatch(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    try:
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result = handle_initialize(request.get("params") or {})
        elif method == "tools/list":
            result = handle_tools_list(request.get("params") or {})
        elif method == "tools/call":
            result = handle_tools_call(request.get("params") or {})
        else:
            raise ValueError(f"unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = dispatch(json.loads(line))
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
