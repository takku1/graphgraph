from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from ..io import (
    find_graph_path,
    load_any,
    validate_graph_file,
)
from ..packets import packet_format_schema
from ..packets.validation import validate_any
from ..planning import plan_context, query_class_schema
from ..retrieval import encode_relation_micro, query_relations, query_saved_relations, search_nodes
from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..services import render_final_packet, render_full_graph, render_source_snippets
from ..services.compiler_driver import CompilerDriver, DriverRequest
from ..services.freshness import (
    inspect_saved_graph_freshness,
    source_root_for_saved_graph,
)
from ..services.lifecycle import (
    refresh_saved_graph,
)
from ..services.project_atlas import build_project_atlas
from ..services.project_status import build_project_status
from ..services.query import execute_query
from .descriptions import (
    DESCRIPTION_TOOL_NAMES,
    DESCRIPTION_TOOLS,
    handle_description_tool,
)
from .descriptions import (
    FORMAT_TABLE as FORMAT_TABLE,
)
from .dispatch import dispatch
from .graph_management import (
    GRAPH_MANAGEMENT_TOOLS,
)
from .graph_management import (
    handle_build_graph as handle_build_graph,
)
from .graph_management import (
    handle_export_graph as handle_export_graph,
)
from .graph_management import (
    handle_remove_graph_files as handle_remove_graph_files,
)
from .graph_management import (
    handle_update_graph_files as handle_update_graph_files,
)
from .machine_contract import compact_json, compact_tool_contracts
from .platform_tools import (
    PLATFORM_TOOL_NAMES,
    PLATFORM_TOOLS,
    handle_platform_tool,
)


def _json(payload: object) -> str:
    """Serialize an MCP response compactly.

    Every byte here is read by a model, never a person, and indentation is
    a quarter of the envelope: pretty-printing one `select_symbols` response
    cost 1221 of 4261 tokens (29%). Compact separators change nothing a
    parser can observe.
    """
    return compact_json(payload)


SERVER_INFO = {"name": "graphgraph", "version": "0.1.0"}


TOOLS = [
    {
        "name": "plan_context",
        "description": (
            "Choose the empirically-measured optimal graph packet strategy for a query class. "
            "Returns hops, packet format, and rationale. Query classes: direct_lookup, "
            "reverse_lookup, multi_hop_path, blast_radius, subsystem_summary, negative_query, "
            "recent_changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_class": query_class_schema(),
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
                "query_class": query_class_schema(),
                "starts": {"type": "array", "items": {"type": "string"}, "description": "Anchor node IDs."},
                "paths": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "max_nodes": {
                    "type": "integer",
                    "description": "Expanded node budget. Default: dynamic by query class and graph shape.",
                },
                "packet": packet_format_schema(),
            },
            "required": ["query_class", "starts"],
        },
    },
    {
        "name": "full_graph",
        "description": (
            "Render EVERY active node/edge in the graph as one packet -- no query, no budget. "
            "Not the default path: query_context/final_packet exist precisely so a caller never "
            "has to pay for the whole graph to answer one question. Use this only when you "
            "genuinely need a complete snapshot (e.g. full-corpus offline analysis), not for "
            "normal codebase questions. Refuses (raises an error) above max_tokens unless raised "
            "or disabled -- a full graph can easily be 100,000+ tokens on a real repo."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string", "description": "Path to graph JSON; auto-detected if omitted."},
                "packet": {
                    "type": "string",
                    "description": "Packet format (default gg, the measured token floor for full topology).",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Token guard (default 20000). Pass 0 to disable and render regardless of size.",
                },
            },
        },
    },
    {
        "name": "query",
        "description": (
            "Canonical read-only GraphGraph query facade. Accepts arbitrary user text, "
            "compiles it into the cheapest lossless typed operator (exact relations, set "
            "predicate, search, status, or general context), and returns the plan and receipt. "
            "It never builds, removes, or exports implicitly; a missing graph returns needs_index."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "context", "relations", "select", "search", "status"],
                    "default": "auto",
                },
                "directory": {"type": "string", "description": "Project root; default current directory."},
                "graph_path": {"type": "string", "description": "Saved graph; auto-detected if omitted."},
                "sync": {"type": "string", "enum": ["none", "git"], "default": "none"},
                "target": {"type": "string", "description": "Explicit target for relations/search override."},
                "direction": {"type": "string", "enum": ["callers", "callees"]},
                "predicate": {"type": "string", "description": "Explicit typed predicate for select override."},
                "result_mode": {"type": "string", "enum": ["select", "count", "exists"], "default": "select"},
                "limit": {"type": "integer", "minimum": 0, "default": 20},
                "include_tests": {"type": "boolean", "default": False},
                "include_external": {"type": "boolean", "default": False},
                "query_class": query_class_schema(include_auto=True, default="auto"),
                "packet": packet_format_schema(),
                "max_nodes": {"type": "integer"},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "scope_mode": {"type": "string", "enum": ["strict", "expand"], "default": "strict"},
                "source_mode": {"type": "string", "enum": ["auto", "off", "all"], "default": "auto"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_context",
        "description": (
            "Native graphgraph retrieval: find graph anchors from a natural-language query, "
            "automatically route its structural intent, expand the graph, and render the chosen compact packet. "
            "Optionally splice changed/deleted files into the persisted graph first, then query that exact "
            "in-memory result in the same call. Use this when the caller does not already know node IDs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {
                    "type": "string",
                    "description": "Path to native graphgraph graph; auto-detected if omitted.",
                },
                "query": {"type": "string"},
                "query_class": query_class_schema(include_auto=True, default="auto"),
                "packet": packet_format_schema(),
                "hops": {
                    "type": "integer",
                    "description": "Override traversal radius. Default: measured by query class.",
                },
                "anchor_limit": {
                    "type": "integer",
                    "description": "Max anchor nodes before expansion. Default: adaptive by query class.",
                },
                "max_nodes": {
                    "type": "integer",
                    "description": "Expanded node budget. Default: dynamic by query class and graph shape.",
                },
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional scope/path prefixes to constrain retrieval.",
                },
                "scope_mode": {
                    "type": "string",
                    "enum": ["strict", "expand"],
                    "description": "strict keeps all results in scope; expand permits structurally connected boundary crossings. Default: strict.",
                },
                "show_anchors": {"type": "boolean", "description": "Include ranked anchors before packet."},
                "include_snippets": {
                    "type": "boolean",
                    "description": "Fuse bounded exact source windows for selected anchors into this response, avoiding a second source_snippets call. Default: false.",
                },
                "snippet_limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Maximum selected anchors with fused source windows. Default: 3.",
                },
                "snippet_context_lines": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Lines before/after each fused symbol. Default: 2.",
                },
                "snippet_max_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum lines per fused source excerpt. Default: 24.",
                },
                "source_mode": {
                    "type": "string",
                    "enum": ["auto", "off", "all"],
                    "description": "Auxiliary source planner mode. Default: auto.",
                },
                "memory_scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Memory scopes eligible for query-time projection. Default: project and session.",
                },
                "changed_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional edited/created files to re-extract before querying. Cost scales with supplied paths, not repository size.",
                },
                "deleted_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional deleted/renamed-away files to remove in the same graph splice before querying.",
                },
                "directory": {
                    "type": "string",
                    "description": "Project root for changed/deleted paths. Defaults to current working directory.",
                },
                "scan_max_nodes": {
                    "type": "integer",
                    "description": f"Max symbols for the changed-file batch. Default: {DEFAULT_SCAN_MAX_NODES}.",
                },
                "depth": {
                    "type": "string",
                    "enum": ["files", "symbols"],
                    "description": "Refresh extraction depth. Defaults to the saved graph's scan depth.",
                },
                "frontend": {
                    "type": "string",
                    "enum": ["auto", "regex", "tree_sitter"],
                    "description": "Refresh frontend. Defaults to the saved graph's frontend.",
                },
                "docs": {
                    "type": "boolean",
                    "description": "Refresh document sections/concepts. Defaults to the saved graph setting.",
                },
                "history": {
                    "type": "boolean",
                    "description": "Refresh bug-fix history. Defaults to the saved graph setting.",
                },
                "sync": {
                    "type": "string",
                    "enum": ["none", "git"],
                    "description": "Optional work-loop sync before querying. 'git' hashes only Git-changed candidates against the manifest and refreshes stale paths. Default: none.",
                },
                "format": {
                    "type": "string",
                    "enum": ["compact", "detailed"],
                    "default": "compact",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "project_status",
        "description": (
            "Summarize graph validity, code/doc balance, package metadata, and optional "
            "runtime probes. Use this before project-status answers that need more than a packet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Project root directory. Defaults to current working directory.",
                },
                "graph_path": {"type": "string", "description": "Graph JSON path. Auto-detected if omitted."},
                "probe": {"type": "boolean", "description": "Run lightweight python -m/import probes. Default: false."},
                "view": {"type": "string", "enum": ["status", "atlas"], "default": "status"},
            },
        },
    },
    {
        "name": "query_relations",
        "description": (
            "Indexed exact one-hop caller/callee lookup with no planner or packet expansion. "
            "Defaults to a tuple-oriented micro IR for model-facing latency and token cost; "
            "use detailed only for human debugging. Separately reports saved-graph truncation, "
            "call-topology coverage, and freshness. Pass sync=git to fuse a Git-delta refresh."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Exact node id, symbol label, or path::symbol."},
                "direction": {"type": "string", "enum": ["callers", "callees"]},
                "limit": {"type": "integer", "minimum": 0, "default": 20},
                "include_tests": {"type": "boolean", "default": False, "description": "Include test callers/callees."},
                "include_external": {
                    "type": "boolean",
                    "description": "Include external/builtin nodes. Default: false.",
                },
                "format": {"type": "string", "enum": ["micro", "detailed"], "default": "micro"},
                "sync": {
                    "type": "string",
                    "enum": ["none", "git"],
                    "default": "none",
                    "description": "Fuse a Git-delta refresh before lookup; default none preserves the latency floor.",
                },
                "graph_path": {"type": "string", "description": "Path to graph; auto-detected if omitted."},
            },
            "required": ["target", "direction"],
        },
    },
    {
        "name": "validate_packet",
        "description": (
            "Mechanically validate a graphgraph packet (lowlevel, sql, semantic_arrow, gg, or "
            "raw graph JSON). To validate a saved native graph instead, omit `packet` and "
            "supply its explicit `graph_path`. Empty arguments fail closed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "packet": {
                    "type": "string",
                    "description": "Rendered packet or raw graph JSON text. Omit to validate the saved graph file instead.",
                },
                "graph_path": {
                    "type": "string",
                    "description": "Explicit path to a saved native graphgraph graph when no packet is supplied.",
                },
            },
        },
    },
    {
        "name": "source_snippets",
        "description": (
            "Render bounded source excerpts for selected graph node IDs, labels, or paths. "
            "Use this after query_context when exact code lines are needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {
                    "type": "string",
                    "description": "Path to native graphgraph graph; auto-detected if omitted.",
                },
                "node_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Node ids (the `id` field search_nodes returns), labels, or paths. Preferred: chains directly from search_nodes.",
                },
                "starts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alias for node_ids (node ids, labels, or paths).",
                },
                "context_lines": {"type": "integer", "description": "Lines before/after symbol line. Default: 4."},
                "max_lines": {"type": "integer", "description": "Maximum lines per excerpt. Default: 40."},
            },
            "required": [],
        },
    },
    *GRAPH_MANAGEMENT_TOOLS,
    {
        "name": "search_nodes",
        "description": (
            "Search nodes in a graph by label, path, or kind. Returns the matching node's exact file "
            "(`path`) and 1-based source `line` directly -- no follow-up call needed just to locate it; "
            "use source_snippets afterward only when you need the surrounding code, not just where it is. "
            "Use this to find the right anchor node IDs before calling final_packet. "
            "The response also includes `top_score_gap_ratio` (top match's score / runner-up's score) "
            "and a provisional `ambiguous` flag: a large gap means the top match is a confident single "
            "answer (safe to use directly, comparable to grepping an exact known symbol); a small/no gap "
            "means multiple candidates are genuinely close and the result list should be treated as "
            "several plausible options, not one answer."
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
        "name": "select_symbols",
        "description": (
            "Answer a whole-graph set predicate in ONE call instead of N anchored lookups -- "
            "e.g. 'which symbols in this crate have no production caller?'. "
            "Use this for dead-code sweeps, island detection, and any question whose answer is a "
            "set, a count, or a yes/no rather than a subgraph. "
            "`mode=count` returns just an integer and `mode=exists` just a boolean, neither of "
            "which materializes node payloads, so prefer them when you do not need the list. "
            "Distinguishes production callers from test-only callers, which is the split that "
            "makes 'unused' meaningful. "
            "IMPORTANT: the response carries `caller_evidence_complete`; when it is false, "
            "zero-caller counts are an UPPER BOUND on dead code (unresolved member calls emit no "
            "calls edge), so do not publish them as proof that a symbol is unused."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "predicate": {
                    "type": "string",
                    "description": (
                        "Filter clauses joined by 'and'. Supported: production_callers/callers "
                        "with = != > >= < <= ('callers > 5' finds hubs), kind=K, "
                        "path|crate contains S, path|crate != S (cross-crate consumer checks), "
                        "label contains S, label in [a, b, c] for batch lookup of many symbols "
                        "in one call, include_tests=BOOL. Example: "
                        "'production_callers = 0 and crate contains locus-engine and include_tests = false'."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["select", "count", "exists"],
                    "description": "select lists symbols; count returns an integer; exists returns a boolean. Default: select.",
                },
                "graph_path": {"type": "string", "description": "Path to graph; auto-detected if omitted."},
                "limit": {"type": "integer", "description": "Max symbols listed in select mode. Default: 200."},
            },
            "required": ["predicate"],
        },
    },
    *DESCRIPTION_TOOLS,
]

TOOLS.extend(PLATFORM_TOOLS)
TOOLS = compact_tool_contracts(TOOLS)

RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "plan_context",
        "final_packet",
        "full_graph",
        "query",
        "query_context",
        "query_relations",
        "project_status",
        "validate_packet",
        "source_snippets",
        "search_nodes",
        "select_symbols",
    }
)


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


_TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _validate_required_args(name: str, args: dict[str, Any]) -> None:
    """Fail missing required args at the MCP boundary with an actionable message.

    Several handlers did a bare ``args["x"]``, so omitting a required arg leaked
    a cryptic ``-32000: 'x'`` (an unhandled KeyError) that told the caller
    neither what was wrong nor what to pass. This validates every tool's
    declared ``required`` list once, naming each missing arg and enumerating its
    allowed values when the schema constrains them.
    """
    tool = _TOOLS_BY_NAME.get(name)
    if not tool:
        return
    schema = tool.get("inputSchema", {})
    props = schema.get("properties", {})
    missing = []
    for arg in schema.get("required", []):
        value = args.get(arg)
        if value is None or value == "" or value == [] or value == {}:
            spec = props.get(arg, {})
            enum = spec.get("enum")
            if enum:
                hint = f" (one of: {', '.join(map(str, enum))})"
            elif spec.get("description"):
                hint = f" -- {spec['description']}"
            else:
                hint = ""
            missing.append(f"'{arg}'{hint}")
    if missing:
        raise ValueError(f"{name} requires {', '.join(missing)}.")


def handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments") or {}
    _validate_required_args(str(name), args)
    if name == "plan_context":
        plan = plan_context(str(args["query_class"]), str(args.get("query", "")))
        return content(_json(plan.__dict__))
    if name == "final_packet":
        return content(build_final_packet(args))
    if name == "full_graph":
        return content(build_full_graph(args))
    if name == "query":
        return content(handle_unified_query(args))
    if name == "query_context":
        return content(build_query_context(args))
    if name == "query_relations":
        return content(handle_query_relations(args))
    if name == "project_status":
        return content(handle_project_status(args))
    if name == "validate_packet":
        packet = args.get("packet")
        if packet:
            result = validate_any(str(packet))
        elif args.get("graph_path"):
            result = validate_graph_file(Path(args["graph_path"]))
        else:
            raise ValueError(
                "validate_packet requires a non-empty 'packet' or an explicit 'graph_path'."
            )
        return content(
            _json(
                {
                    "ok": result.ok,
                    "format": result.format,
                    "node_count": result.node_count,
                    "edge_count": result.edge_count,
                    "errors": list(result.errors),
                }
            )
        )
    if name == "source_snippets":
        return content(handle_source_snippets(args))
    if name == "build_graph":
        return content(handle_build_graph(args))
    if name == "update_graph_files":
        return content(handle_update_graph_files(args))
    if name == "remove_graph_files":
        return content(handle_remove_graph_files(args))
    if name == "search_nodes":
        return content(handle_search_nodes(args))
    if name == "select_symbols":
        return content(handle_select_symbols(args))
    if name == "export_graph":
        return content(handle_export_graph(args))
    if name in DESCRIPTION_TOOL_NAMES:
        return content(handle_description_tool(str(name), args))
    if name in PLATFORM_TOOL_NAMES:
        return content(handle_platform_tool(str(name), args))
    raise ValueError(f"unknown tool: {name}")


def build_final_packet(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    policies_path_str = args.get("policies_path")
    policies_path = Path(policies_path_str) if policies_path_str else None
    return render_final_packet(
        starts=[str(item) for item in args["starts"]],
        query_class=str(args["query_class"]),
        query_text=str(args.get("query", "")),
        graph_path=graph_path,
        policies_path=policies_path,
        paths=tuple(str(item) for item in args.get("paths", [])),
        tags=tuple(str(item) for item in args.get("tags", [])),
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else None,
        cache_namespace="mcp_final",
        packet=str(args["packet"]) if args.get("packet") else None,
    )


def build_full_graph(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    max_tokens = int(args["max_tokens"]) if args.get("max_tokens") is not None else 20_000
    return render_full_graph(
        graph_path,
        packet=str(args["packet"]) if args.get("packet") else "gg",
        max_tokens=max_tokens if max_tokens else None,
    )


def build_query_context(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    changed_paths = _unique_strings(args.get("changed_paths") or [])
    deleted_paths = _unique_strings(args.get("deleted_paths") or [])
    sync_git = str(args.get("sync") or "none") == "git"
    rendered, _status = CompilerDriver().compile(DriverRequest(
        query=str(args["query"]),
        query_class=str(args.get("query_class") or "auto"),
        directory=Path(str(args.get("directory") or ".")),
        graph_path=graph_path,
        packet=str(args["packet"]) if args.get("packet") else None,
        hops=int(args["hops"]) if args.get("hops") is not None else None,
        anchor_limit=int(args["anchor_limit"]) if args.get("anchor_limit") is not None else None,
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else None,
        scopes=tuple(str(scope) for scope in args.get("scopes") or []),
        scope_mode=str(args.get("scope_mode") or "strict"),
        show_anchors=True,
        changed_paths=tuple(changed_paths),
        deleted_paths=tuple(deleted_paths),
        sync_git=sync_git,
        json_output=True,
        json_details=True,
        cache_namespace="mcp_query",
        scan_max_nodes=(
            int(args["scan_max_nodes"])
            if args.get("scan_max_nodes") is not None
            else DEFAULT_SCAN_MAX_NODES
        ),
        depth=str(args["depth"]) if args.get("depth") else None,
        frontend=str(args["frontend"]) if args.get("frontend") else None,
        docs=bool(args["docs"]) if "docs" in args else None,
        history=bool(args["history"]) if "history" in args else None,
        source_mode=str(args.get("source_mode") or "auto"),
        memory_scopes=tuple(str(scope) for scope in args.get("memory_scopes") or ("project", "session")),
        include_snippets=bool(args.get("include_snippets")),
        snippet_limit=int(args["snippet_limit"]) if args.get("snippet_limit") is not None else 3,
        snippet_context_lines=(
            int(args["snippet_context_lines"]) if args.get("snippet_context_lines") is not None else 2
        ),
        snippet_max_lines=(int(args["snippet_max_lines"]) if args.get("snippet_max_lines") is not None else 24),
    ))
    if (
        str(args.get("format") or "compact") == "detailed"
        or bool(args.get("show_anchors"))
        or bool(args.get("include_snippets"))
    ):
        # The shared context module pretty-prints CLI diagnostics. MCP results
        # are machine-only, so forwarding that whitespace inflated detailed
        # envelopes by roughly 45% (9.6k -> 6.6k characters on the critical
        # C# fixture) without adding one bit of proof. Preserve the complete
        # detailed schema while using the transport's canonical compact JSON.
        return _json(json.loads(rendered))
    payload = json.loads(rendered)
    actionable = payload.get("actionable", {}) or {}
    workflow = payload.get("workflow", {}) or {}
    freshness = payload.get("freshness", {}) or workflow.get("freshness", {}) or {}
    tests = actionable.get("tests", {}) or {}
    proof: dict[str, object] = {
        "status": actionable.get("status", "unknown"),
        "missing": actionable.get("missing_evidence", []),
        "fresh": freshness.get("fresh", freshness.get("repository_fresh")),
        "validation": (workflow.get("packet_validation", {}) or {}).get("ok"),
        "cache": (workflow.get("cache", {}) or {}).get("state", ""),
    }
    if tests.get("commands") or tests.get("direct") or tests.get("transitive"):
        proof["tests"] = tests
    if actionable.get("subsystem_map"):
        proof["subsystem_map"] = actionable["subsystem_map"]
    if payload.get("source_snippets"):
        proof["source_snippets"] = payload["source_snippets"]
    return _json(
        {
            "packet": payload.get("packet", ""),
            "control": payload.get("control", ""),
            "proof": proof,
        }
    )


def _unique_strings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def handle_source_snippets(args: dict[str, Any]) -> str:
    # Compose with search_nodes, which returns `id`: accept `node_ids` as the
    # primary name and keep `starts` as an alias, so the two tools chain without
    # the caller having to rename the field. Validate this before resolving the
    # graph path so a missing-id call returns the actionable message, not an
    # unrelated "no graph found" error.
    raw_starts = args.get("node_ids") or args.get("starts")
    if not raw_starts:
        raise ValueError(
            "source_snippets requires 'node_ids' (the ids search_nodes returns) or "
            "'starts' (node ids, labels, or paths)."
        )
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    return render_source_snippets(
        starts=[str(item) for item in raw_starts],
        graph_path=graph_path,
        context_lines=int(args["context_lines"]) if args.get("context_lines") is not None else 4,
        max_lines=int(args["max_lines"]) if args.get("max_lines") is not None else 40,
    )


def handle_project_atlas(args: dict[str, Any]) -> str:
    report = build_project_atlas(
        directory=Path(str(args.get("directory") or ".")),
        graph_path=Path(str(args["graph_path"])) if args.get("graph_path") else None,
        max_subsystems=int(args["max_subsystems"]) if args.get("max_subsystems") is not None else None,
        representatives_per_subsystem=int(args.get("representatives") or 1),
        max_couplings=int(args["max_couplings"]) if args.get("max_couplings") is not None else None,
        evidence_budget_chars=int(args.get("evidence_budget_chars") or 8000),
    )
    return _json(report)


def handle_project_status(args: dict[str, Any]) -> str:
    if str(args.get("view") or "status") == "atlas":
        return handle_project_atlas(args)
    directory = Path(str(args.get("directory") or "."))
    graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else None
    report = build_project_status(
        directory=directory,
        graph_path=graph_path,
        run_probes=bool(args.get("probe")),
    )
    return _json(report)


def handle_unified_query(args: dict[str, Any]) -> str:
    response = execute_query(
        str(args["query"]),
        directory=Path(str(args.get("directory") or ".")),
        graph_path=Path(str(args["graph_path"])) if args.get("graph_path") else None,
        mode=str(args.get("mode") or "auto"),
        result_mode=str(args.get("result_mode") or "select"),
        target=str(args.get("target") or ""),
        direction=str(args.get("direction") or ""),
        predicate=str(args.get("predicate") or ""),
        sync=str(args.get("sync") or "none"),
        limit=int(args["limit"]) if args.get("limit") is not None else 20,
        include_tests=bool(args.get("include_tests", False)),
        include_external=bool(args.get("include_external", False)),
        query_class=str(args.get("query_class") or "auto"),
        packet=str(args["packet"]) if args.get("packet") else None,
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else None,
        scopes=tuple(str(item) for item in args.get("scopes", ())),
        scope_mode=str(args.get("scope_mode") or "strict"),
        source_mode=str(args.get("source_mode") or "auto"),
    )
    return _json(response)


def handle_select_symbols(args: dict[str, Any]) -> str:
    from ..retrieval.predicates import parse_criteria, select_symbols

    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    graph = load_any(graph_path)

    mode = str(args.get("mode") or "select")
    limit = int(args["limit"]) if args.get("limit") is not None else 200
    try:
        criteria = parse_criteria(str(args["predicate"]), limit=limit)
    except ValueError as exc:
        return _json({"error": str(exc)})

    result = select_symbols(graph, criteria, mode=mode)  # type: ignore[arg-type]
    payload: dict[str, Any] = {
        "mode": result.mode,
        "total": result.total,
        "criteria": result.criteria_detail,
        "caller_evidence_complete": result.caller_evidence_complete,
        "caller_evidence": result.caller_evidence,
    }
    if mode == "exists":
        payload["exists"] = result.exists
    if mode == "select":
        payload["truncated"] = result.truncated
        payload["symbols"] = result.symbols
    return _json(payload)


def handle_query_relations(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    started = time.perf_counter()
    sync_git = str(args.get("sync") or "none") == "git"
    refresh_summary = None
    freshness = "unchecked"
    if sync_git:
        source_root = source_root_for_saved_graph(graph_path)
        status = refresh_saved_graph(
            directory=source_root,
            output_path=graph_path,
            sync_git=True,
        )
        graph = status.graph
        checked = inspect_saved_graph_freshness(
            directory=source_root,
            output_path=graph_path,
        )
        freshness = "fresh" if checked["fresh"] else "incompatible" if not checked["extractor_compatible"] else "stale"
        refresh_summary = {
            "updated": len(status.changed_paths),
            "removed": len(status.deleted_paths),
            "write": status.built,
            "fresh": freshness == "fresh",
        }
    else:
        graph = None
    query = query_relations if graph is not None else query_saved_relations
    result = query(
        graph if graph is not None else graph_path,
        str(args["target"]),
        direction=str(args["direction"]),  # type: ignore[arg-type]
        limit=int(args["limit"]) if args.get("limit") is not None else 20,
        include_tests=bool(args.get("include_tests", False)),
        include_external=bool(args.get("include_external", False)),
        details=str(args.get("format") or "micro") == "detailed",
        freshness=freshness,
    )
    if refresh_summary is not None and result.get("status") == "ok":
        result["refresh"] = refresh_summary
    if result.get("status") == "ok":
        result["milliseconds"] = round((time.perf_counter() - started) * 1000, 3)
    payload = encode_relation_micro(result) if str(args.get("format") or "micro") == "micro" else result
    if result.get("status") == "ok" and isinstance(payload.get("r"), dict):
        payload["r"]["ms"] = result["milliseconds"]
    return _json(payload)


def handle_search_nodes(args: dict[str, Any]) -> str:
    graph_path_str = args.get("graph_path")
    graph_path = Path(graph_path_str) if graph_path_str else find_graph_path()
    graph = load_any(graph_path)

    q = str(args["query"]).lower()
    limit = int(args["limit"]) if args.get("limit") is not None else 20

    matches = search_nodes(graph, q, limit=limit)

    # Confidence signal: ratio of the top match's score to the runner-up's.
    # A large gap means one dominant, high-confidence anchor (empirically,
    # ratio >= ~1.8 on exact-symbol-style queries against this project);
    # a ratio near 1.0 means multiple candidates are genuinely tied and the
    # caller should treat the list as several options, not a single answer.
    # The 1.3 cutoff below is a provisional heuristic from a small sample,
    # not a calibrated threshold -- treat the raw ratio as the real signal.
    top_score_gap_ratio = None
    ambiguous = False
    if len(matches) >= 2:
        if matches[1].score > 0:
            top_score_gap_ratio = matches[0].score / matches[1].score
            ambiguous = top_score_gap_ratio < 1.3
        else:
            ambiguous = False  # runner-up scored zero -- top match isn't contested

    return _json(
        {
            "matches": [
                {
                    "id": match.node.id,
                    "label": match.node.label,
                    "kind": match.node.kind,
                    "path": match.node.path,
                    "line": match.node.line,
                    "score": match.score,
                    "reasons": list(match.reasons),
                    "summary": match.node.summary,
                }
                for match in matches
            ],
            "total": len(matches),
            "top_score_gap_ratio": top_score_gap_ratio,
            "ambiguous": ambiguous,
        }
    )


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = dispatch(json.loads(line))
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
