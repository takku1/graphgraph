from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .cli import cmd_final
from .core import Query
from .frontends import available_frontends
from .io import load_graph, load_any, save_graph, save_gg, find_graph_path, find_policies_path, load_policies
from .ontology import DEFAULT_RELATIONS
from .packets import render_packet
from .planner import choose_packet
from .policies import render_policy_packet, select_policies
from .retrieval import retrieve_context, search_nodes
from .scanner import scan_directory
from .temporal import graph_at
from .traversal import POLICIES, traversal_policy
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
        "name": "query_context",
        "description": (
            "Native graphgraph retrieval: find graph anchors from a natural-language query, "
            "expand the graph, and render the chosen compact packet. Use this when the caller "
            "does not already know node IDs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string", "description": "Path to native graphgraph graph; auto-detected if omitted."},
                "query": {"type": "string"},
                "query_class": {"type": "string", "description": "direct_lookup, reverse_lookup, multi_hop_path, blast_radius, subsystem_summary, negative_query."},
                "packet": {"type": "string", "description": "Optional packet override."},
                "anchor_limit": {"type": "integer", "description": "Max anchor nodes before expansion. Default: adaptive by query class."},
                "max_nodes": {"type": "integer", "description": "Expanded node budget."},
                "as_of": {"type": "string", "description": "Optional ISO timestamp/date for point-in-time graph view."},
                "scopes": {"type": "array", "items": {"type": "string"}, "description": "Optional scope/path prefixes to constrain retrieval."},
                "show_anchors": {"type": "boolean", "description": "Include ranked anchors before packet."},
            },
            "required": ["query"],
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
                "depth": {"type": "string", "enum": ["files", "symbols"], "description": "'files' (default): one node per file. 'symbols': adds native function/class/struct nodes with call/reference edges."},
                "frontend": {"type": "string", "enum": ["auto", "regex", "tree_sitter"], "description": "Symbol extraction frontend for depth=symbols. auto prefers Tree-sitter when available."},
                "docs": {"type": "boolean", "description": "Extract document sections and concept nodes from Markdown/RST/HTML/text."},
                "communities": {"type": "boolean", "description": "Add deterministic path/scope community summary nodes."},
                "incremental": {"type": "boolean", "description": "Enable hash-based incremental scanning. Defaults to true."},
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
        "name": "export_graph",
        "description": (
            "Export the current graph to the native .gg adjacency-list format — "
            "the token-optimal, self-describing format LLMs can read cold with zero schema overhead. "
            "Also the recommended format for LLM-generated context graphs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string", "description": "Source graph path. Auto-detected if omitted."},
                "output_path": {"type": "string", "description": "Output .gg path. Defaults to same dir as source."},
            },
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
    {
        "name": "describe_ontology",
        "description": "List native relation semantics, traversal weights, and weak/strong relation families.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "family": {"type": "string", "description": "Optional relation family filter."},
            },
        },
    },
    {
        "name": "describe_frontends",
        "description": "List available extraction frontend layers and whether optional parsers are installed.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "describe_traversal",
        "description": "List query-class traversal policies used for graph retrieval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_class": {"type": "string"},
            },
        },
    },
]


FORMAT_TABLE = [
    {"format": "gg_max", "schema_tokens": 20, "relative_tokens": "1.00x", "description": "Token floor for large graphs: integer indices + relation map. Best for 2-hop topology queries."},
    {"format": "svo", "schema_tokens": 0, "relative_tokens": "~1.1x", "description": "Self-describing SVO triples. Zero schema overhead — LLMs read cold. Best for small 1-hop queries."},
    {"format": "lowlevel", "schema_tokens": 20, "relative_tokens": "1.03x", "description": "XML-tagged adjacency. Slightly more tokens than gg_max."},
    {"format": "sql", "schema_tokens": 10, "relative_tokens": "1.38x", "description": "Table row layout. Best for 1-hop direct/reverse lookups (no relation-map overhead)."},
    {"format": "semantic_arrow", "schema_tokens": 15, "relative_tokens": "1.49x", "description": "Subject-verb-object arrows with @nodes/@edges preamble."},
    {"format": "gg_max_hybrid", "schema_tokens": 20, "relative_tokens": "~1.6x", "description": "gg_max + inline node kind/summary. Best for subsystem summaries."},
    {"format": "doc_summary", "schema_tokens": 2, "relative_tokens": "~0.6x", "description": "Grounded section/file notes with no topology. Best for README/docs/install/usage questions."},
    {"format": "hybrid", "schema_tokens": 5, "relative_tokens": "~2.3x", "description": "Markdown bullet lists. Readable but high token overhead."},
    {"format": "json", "schema_tokens": 0, "relative_tokens": "3.9-6.7x", "description": "Raw JSON. Never use as LLM wire format."},
    {"format": ".gg file", "schema_tokens": 0, "relative_tokens": "~0.9x", "description": "Native adjacency-list storage format. Nodes then their edges co-located. LLMs can generate this directly."},
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
        choice = choose_packet(str(args["query_class"]), str(args.get("query", "")))
        return content(json.dumps({"hops": choice.hops, "packet": choice.packet, "reason": choice.reason}))
    if name == "final_packet":
        return content(build_final_packet(args))
    if name == "query_context":
        return content(build_query_context(args))
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
    if name == "export_graph":
        return content(handle_export_graph(args))
    if name == "describe_formats":
        return content(json.dumps(FORMAT_TABLE, indent=2))
    if name == "describe_ontology":
        family = args.get("family")
        rows = [
            {
                "name": name,
                "family": spec.family,
                "direction": spec.direction,
                "strength": spec.strength,
                "traversable": spec.traversable,
                "weak": spec.weak,
                "description": spec.description,
            }
            for name, spec in DEFAULT_RELATIONS.items()
            if not family or spec.family == family
        ]
        return content(json.dumps(rows, indent=2))
    if name == "describe_frontends":
        return content(json.dumps([cap.__dict__ for cap in available_frontends()], indent=2))
    if name == "describe_traversal":
        if args.get("query_class"):
            return content(json.dumps(traversal_policy(str(args["query_class"])).__dict__, indent=2))
        return content(json.dumps({name: policy.__dict__ for name, policy in POLICIES.items()}, indent=2))
    raise ValueError(f"unknown tool: {name}")


def build_final_packet(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    
    # Try KV Cache first
    from .cache import TopologicalKVCache, compute_cache_key
    cache = TopologicalKVCache()
    
    query_text = str(args.get("query", ""))
    query_class = str(args["query_class"])
    choice = choose_packet(query_class, query_text)
    starts = [str(item) for item in args["starts"]]
    
    cache_key = compute_cache_key(
        starts,
        query_class,
        choice.hops,
        choice.packet + f"|mcp_final|{query_text}|{args.get('paths')}|{args.get('tags')}|{args.get('max_nodes')}"
    )
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        return cached_packet

    graph = load_any(graph_path)
    if args.get("as_of"):
        graph = graph_at(graph, str(args["as_of"]))

    policies_path_str = args.get("policies_path")
    policies_path = Path(policies_path_str) if policies_path_str else find_policies_path()
    policies = load_policies(policies_path) if policies_path else []

    query = Query(
        text=query_text,
        query_class=query_class,
        paths=tuple(str(item) for item in args.get("paths", [])),
        tags=tuple(str(item) for item in args.get("tags", [])),
    )
    max_nodes = args.get("max_nodes")
    nodes, edges = graph.expand(starts, hops=choice.hops, max_nodes=int(max_nodes) if max_nodes else None)

    selected = select_policies(policies, query)
    policy_packet = render_policy_packet(selected, compact=True)
    graph_packet = render_packet(graph, nodes, edges, choice.packet)

    validation = validate_packet(graph_packet)
    if not validation.ok:
        raise ValueError("generated graph packet failed validation: " + "; ".join(validation.errors))

    final_packet = f"CONSTRAINTS:\n{policy_packet}\n\nGRAPH:\n{graph_packet}" if policy_packet else graph_packet
    cache.set(graph_path, cache_key, final_packet)
    return final_packet


def build_query_context(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    query = str(args["query"])
    query_class = str(args.get("query_class") or "blast_radius")
    choice = choose_packet(query_class, query)

    from .cache import TopologicalKVCache, compute_cache_key
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        [query],
        query_class,
        choice.hops,
        f"mcp_query|{args.get('anchor_limit')}|{args.get('max_nodes')}|{args.get('scopes')}|{args.get('packet')}"
    )
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        return cached_packet

    graph = load_any(graph_path)
    result = retrieve_context(
        graph,
        query,
        query_class,
        hops=choice.hops,
        anchor_limit=int(args["anchor_limit"]) if args.get("anchor_limit") is not None else None,
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") else None,
        scopes=tuple(str(scope) for scope in args.get("scopes") or []),
    )
    if not result.starts:
        return json.dumps({"anchors": [], "packet": "", "message": "No matching graph anchors found for query."})

    packet = render_packet(graph, result.nodes, result.edges, str(args.get("packet") or choice.packet))
    
    if not args.get("show_anchors"):
        response = packet
    else:
        anchors = [
            {
                "id": match.node.id,
                "label": match.node.label,
                "kind": match.node.kind,
                "path": match.node.path,
                "score": match.score,
                "reasons": list(match.reasons),
            }
            for match in result.matches[: int(args["anchor_limit"]) if args.get("anchor_limit") is not None else len(result.starts)]
        ]
        response = json.dumps({"anchors": anchors, "packet": packet}, indent=2)

    cache.set(graph_path, cache_key, response)
    return response


def handle_build_graph(args: dict[str, Any]) -> str:
    input_graph_str = args.get("input_graph")
    output_path_str = args.get("output_path") or ".graphgraph/graph.json"
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if input_graph_str:
        graph = load_any(Path(input_graph_str))
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
    frontend = str(args.get("frontend") or "auto")
    docs = bool(args.get("docs", False))
    communities = bool(args.get("communities", False))
    incremental = bool(args.get("incremental", True))
    previous_graph_path = output_path if incremental else None
    manifest_path = (output_path.parent / "manifest.json") if incremental else None

    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=skip_dirs,
        depth=depth,
        frontend=frontend,
        docs=docs,
        communities=communities,
        previous_graph_path=previous_graph_path,
        manifest_path=manifest_path,
    )

    save_graph(graph, output_path)
    return json.dumps({
        "action": "scanned",
        "directory": str(directory.resolve()),
        "output": str(output_path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    })


def handle_export_graph(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    graph = load_any(graph_path)
    out_str = args.get("output_path")
    output_path = Path(out_str) if out_str else graph_path.with_suffix(".gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_gg(graph, output_path)
    return json.dumps({
        "output": str(output_path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "format": "gg",
    })


def handle_search_nodes(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    graph = load_any(graph_path)

    q = str(args["query"]).lower()
    limit = int(args.get("limit") or 20)

    matches = search_nodes(graph, q, limit=limit)
    return json.dumps({
        "matches": [
            {
                "id": match.node.id,
                "label": match.node.label,
                "kind": match.node.kind,
                "path": match.node.path,
                "score": match.score,
                "reasons": list(match.reasons),
                "summary": match.node.summary,
            }
            for match in matches
        ],
        "total": len(matches),
    })


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
