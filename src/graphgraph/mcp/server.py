from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..graph.ontology import DEFAULT_RELATIONS
from ..graph.traversal import POLICIES, traversal_policy
from ..io import find_graph_path, load_any, save_gg, save_validated_graph, validate_graph_file
from ..packets.validation import validate_any
from ..planning import plan_context
from ..platform import (
    CpgEvidenceProvider,
    EvidenceStore,
    GraphProgram,
    GraphRuntime,
    MemoryStore,
    QuerySourcePlanner,
    StructuralEvidenceProvider,
    build_change_packet,
    build_repair_context,
    graph_as_of,
)
from ..retrieval import search_nodes
from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..scanner.frontends import available_frontends
from ..services import render_final_packet, render_full_graph, render_query_context, render_source_snippets
from ..services.native import (
    build_project_status,
    graph_shape,
    inspect_saved_graph_freshness,
    refresh_receipt,
    refresh_saved_graph,
    remove_paths_validated_graph,
    scan_validated_graph,
    scope_freshness,
    update_paths_validated_graph,
)

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
                "query_class": {"type": "string", "description": "one of: direct_lookup, reverse_lookup, multi_hop_path, blast_radius, affected_tests, subsystem_summary, doc_summary, negative_query, recent_changes, spreading_activation (unknown falls back to a conservative default)"},
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
                "query_class": {"type": "string", "description": "one of: direct_lookup, reverse_lookup, multi_hop_path, blast_radius, affected_tests, subsystem_summary, doc_summary, negative_query, recent_changes, spreading_activation (unknown falls back to a conservative default)"},
                "starts": {"type": "array", "items": {"type": "string"}, "description": "Anchor node IDs."},
                "paths": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "max_nodes": {"type": "integer", "description": "Expanded node budget. Default: dynamic by query class and graph shape."},
                "packet": {
                    "type": "string",
                    "description": "Override packet format (e.g. lowlevel, sql, hybrid, semantic_arrow, gg, gg_hybrid, gg_lex, gg_lex_hybrid, svo, doc_summary).",
                },
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
                "graph_path": {"type": "string", "description": "Path to native graphgraph graph; auto-detected if omitted."},
                "query": {"type": "string"},
                "query_class": {"type": "string", "description": "Optional override. Default: auto. Choices: direct_lookup, reverse_lookup, multi_hop_path, blast_radius, subsystem_summary, doc_summary, negative_query, recent_changes."},
                "packet": {"type": "string", "description": "Optional packet override."},
                "hops": {"type": "integer", "description": "Override traversal radius. Default: measured by query class."},
                "anchor_limit": {"type": "integer", "description": "Max anchor nodes before expansion. Default: adaptive by query class."},
                "max_nodes": {"type": "integer", "description": "Expanded node budget. Default: dynamic by query class and graph shape."},
                "scopes": {"type": "array", "items": {"type": "string"}, "description": "Optional scope/path prefixes to constrain retrieval."},
                "scope_mode": {"type": "string", "enum": ["strict", "expand"], "description": "strict keeps all results in scope; expand permits structurally connected boundary crossings. Default: strict."},
                "show_anchors": {"type": "boolean", "description": "Include ranked anchors before packet."},
                "include_snippets": {"type": "boolean", "description": "Fuse bounded exact source windows for selected anchors into this response, avoiding a second source_snippets call. Default: false."},
                "snippet_limit": {"type": "integer", "minimum": 0, "description": "Maximum selected anchors with fused source windows. Default: 3."},
                "snippet_context_lines": {"type": "integer", "minimum": 0, "description": "Lines before/after each fused symbol. Default: 2."},
                "snippet_max_lines": {"type": "integer", "minimum": 1, "description": "Maximum lines per fused source excerpt. Default: 24."},
                "source_mode": {"type": "string", "enum": ["auto", "off", "all"], "description": "Auxiliary source planner mode. Default: auto."},
                "memory_scopes": {"type": "array", "items": {"type": "string"}, "description": "Memory scopes eligible for query-time projection. Default: project and session."},
                "changed_paths": {"type": "array", "items": {"type": "string"}, "description": "Optional edited/created files to re-extract before querying. Cost scales with supplied paths, not repository size."},
                "deleted_paths": {"type": "array", "items": {"type": "string"}, "description": "Optional deleted/renamed-away files to remove in the same graph splice before querying."},
                "directory": {"type": "string", "description": "Project root for changed/deleted paths. Defaults to current working directory."},
                "scan_max_nodes": {"type": "integer", "description": f"Max symbols for the changed-file batch. Default: {DEFAULT_SCAN_MAX_NODES}."},
                "depth": {"type": "string", "enum": ["files", "symbols"], "description": "Refresh extraction depth. Defaults to the saved graph's scan depth."},
                "frontend": {"type": "string", "enum": ["auto", "regex", "tree_sitter"], "description": "Refresh frontend. Defaults to the saved graph's frontend."},
                "docs": {"type": "boolean", "description": "Refresh document sections/concepts. Defaults to the saved graph setting."},
                "history": {"type": "boolean", "description": "Refresh bug-fix history. Defaults to the saved graph setting."},
                "sync": {"type": "string", "enum": ["none", "git"], "description": "Optional work-loop sync before querying. 'git' hashes only Git-changed candidates against the manifest and refreshes stale paths. Default: none."},
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
                "directory": {"type": "string", "description": "Project root directory. Defaults to current working directory."},
                "graph_path": {"type": "string", "description": "Graph JSON path. Auto-detected if omitted."},
                "probe": {"type": "boolean", "description": "Run lightweight python -m/import probes. Default: false."},
            },
        },
    },
    {
        "name": "validate_packet",
        "description": (
            "Mechanically validate a graphgraph packet (lowlevel, sql, semantic_arrow, gg, or "
            "raw graph JSON). Omit `packet` to instead validate the saved native graph file "
            "(auto-detected, or `graph_path` if given) -- mirrors `graphgraph validate`'s "
            "auto-detect behavior."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "packet": {"type": "string", "description": "Rendered packet or raw graph JSON text. Omit to validate the saved graph file instead."},
                "graph_path": {"type": "string", "description": "Path to native graphgraph graph; auto-detected if omitted and packet is also omitted."},
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
                "graph_path": {"type": "string", "description": "Path to native graphgraph graph; auto-detected if omitted."},
                "node_ids": {"type": "array", "items": {"type": "string"}, "description": "Node ids (the `id` field search_nodes returns), labels, or paths. Preferred: chains directly from search_nodes."},
                "starts": {"type": "array", "items": {"type": "string"}, "description": "Alias for node_ids (node ids, labels, or paths)."},
                "context_lines": {"type": "integer", "description": "Lines before/after symbol line. Default: 4."},
                "max_lines": {"type": "integer", "description": "Maximum lines per excerpt. Default: 40."},
            },
            "required": [],
        },
    },
    {
        "name": "build_graph",
        "description": (
            "Scan a directory (or ingest an existing graph JSON) and save a normalized graph "
            "to .graphgraph/graph.gg. Works on any codebase or documentation tree. "
            "Detects import/dependency edges for Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby; "
            "link edges for Markdown, RST, and HTML. "
            "Optionally enable generic_mentions to extract weak 'references' edges from any text file. "
            "Built-in exclusions: repos/, references/, references_temp/, vendor/, node_modules/, .venv, etc. "
            "Use skip_dirs or exclude_dirs to add project-specific exclusions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory to scan. Defaults to current working directory."},
                "input_graph": {"type": "string", "description": "Path to an existing graph JSON (e.g. graphify output) to ingest instead of scanning."},
                "output_path": {"type": "string", "description": "Where to save the graph. Defaults to .graphgraph/graph.gg."},
                "max_nodes": {"type": "integer", "description": f"Max file/node count during directory scan. Default: {DEFAULT_SCAN_MAX_NODES}."},
                "generic_mentions": {"type": "boolean", "description": "Also add weak 'references' edges for any file that mentions another file's name. Useful for docs-heavy repos. Default: false."},
                "skip_dirs": {"type": "array", "items": {"type": "string"}, "description": "Extra directory names to exclude (beyond built-ins). E.g. ['spikes', 'test-inputs']."},
                "exclude_dirs": {"type": "array", "items": {"type": "string"}, "description": "Alias for skip_dirs — extra directory names to exclude. Merged with skip_dirs if both supplied."},
                "include_dirs": {"type": "array", "items": {"type": "string"}, "description": "Directory names to keep even though a default skip rule would drop them. E.g. ['build', 'out']."},
                "depth": {"type": "string", "enum": ["files", "symbols"], "description": "'files' (default): one node per file. 'symbols': adds native function/class/struct nodes with call/reference edges."},
                "frontend": {"type": "string", "enum": ["auto", "regex", "tree_sitter"], "description": "Symbol extraction frontend for depth=symbols. auto prefers Tree-sitter when available."},
                "docs": {"type": "boolean", "description": "Extract document sections and concept nodes from Markdown/RST/HTML/text."},
                "history": {"type": "boolean", "description": "Link qualifying bug-fix commits (git log, regex-classified) to the files they touched via a 'fixes' edge. Opt-in; requires a git repo. Default: false."},
                "incremental": {"type": "boolean", "description": "Enable hash-based incremental scanning. Defaults to true."},
            },
        },
    },
    {
        "name": "update_graph_files",
        "description": (
            "Re-extract exactly the given files and splice the result into the existing graph. "
            "Unlike build_graph, this never walks the directory tree or hashes any file you didn't "
            "name -- every other tracked file is trusted as unchanged and restored from the manifest. "
            "Use this after editing a known set of files in an edit/test/measure loop: cost scales "
            "with len(paths), not repo size (e.g. ~2s vs ~15s on a 40k-node graph in practice). "
            "Requires a prior build_graph/scan run at output_path. A path that no longer exists on "
            "disk is treated as a removal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "File(s) that changed, relative to directory or absolute."},
                "directory": {"type": "string", "description": "Directory root. Defaults to current working directory."},
                "output_path": {"type": "string", "description": "Existing graph path to update. Defaults to .graphgraph/graph.gg."},
                "max_nodes": {"type": "integer", "description": f"Max symbols per file batch. Default: {DEFAULT_SCAN_MAX_NODES}."},
                "depth": {"type": "string", "enum": ["files", "symbols"], "description": "Default: symbols."},
                "frontend": {"type": "string", "enum": ["auto", "regex", "tree_sitter"]},
                "docs": {"type": "boolean", "description": "Extract document sections/concepts for doc files among paths."},
                "history": {"type": "boolean"},
            },
            "required": ["paths"],
        },
    },
    {
        "name": "remove_graph_files",
        "description": (
            "Drop the given files (deleted/renamed away) from the existing graph -- their nodes and "
            "edges are removed, everything else is restored verbatim. No re-extraction, no directory "
            "walk. Requires a prior build_graph/scan run at output_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "File(s) that no longer exist, relative to directory or absolute."},
                "directory": {"type": "string", "description": "Directory root. Defaults to current working directory."},
                "output_path": {"type": "string", "description": "Existing graph path to update. Defaults to .graphgraph/graph.gg."},
                "max_nodes": {"type": "integer"},
                "depth": {"type": "string", "enum": ["files", "symbols"]},
                "frontend": {"type": "string", "enum": ["auto", "regex", "tree_sitter"]},
                "docs": {"type": "boolean"},
                "history": {"type": "boolean"},
            },
            "required": ["paths"],
        },
    },
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
        "name": "export_graph",
        "description": (
            "Export the current graph to the native binary .gg format — "
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
                "query_class": {"type": "string", "description": "one of: direct_lookup, reverse_lookup, multi_hop_path, blast_radius, affected_tests, subsystem_summary, doc_summary, negative_query, recent_changes, spreading_activation (unknown falls back to a conservative default)"},
            },
        },
    },
]

TOOLS.extend([
    {
        "name": "compile_context",
        "description": "Compile a query through GraphGraph's LLM-native graph IR, optional evidence/inference/hierarchy passes, budgeted retrieval, compact packet rendering, and validation receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "graph_path": {"type": "string"},
                "query_class": {"type": "string", "default": "auto"},
                "packet": {"type": "string", "default": "gg"},
                "passes": {"type": "array", "items": {"type": "string", "enum": ["evidence", "inference", "hierarchy"]}},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "max_nodes": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "repair_context",
        "description": "Compile an issue, error, or stack trace into bounded code/test/config repair context with grounding receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue": {"type": "string"},
                "graph_path": {"type": "string"},
                "max_nodes": {"type": "integer", "default": 30},
                "hops": {"type": "integer", "default": 2},
            },
            "required": ["issue"],
        },
    },
    {
        "name": "graph_change",
        "description": "Compile before/after graph snapshots into structural changes, blast radius, breaking changes, and a stable cursor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "before_path": {"type": "string"},
                "after_path": {"type": "string"},
                "impact_hops": {"type": "integer", "default": 2},
            },
            "required": ["before_path", "after_path"],
        },
    },
    {
        "name": "memory_context",
        "description": "Add, query, or list scoped local agent/project memory records that can be projected into GraphGraph IR.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["add", "query", "list"]},
                "text": {"type": "string"},
                "store_path": {"type": "string", "default": ".graphgraph/memory.json"},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "kind": {"type": "string", "default": "fact"},
                "related_nodes": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["operation"],
        },
    },
    {
        "name": "graph_at_time",
        "description": "Materialize an ISO-timestamped graph view using native validity windows and return its compact status.",
        "inputSchema": {
            "type": "object",
            "properties": {"timestamp": {"type": "string"}, "graph_path": {"type": "string"}},
            "required": ["timestamp"],
        },
    },
])


FORMAT_TABLE = [
    {"format": "gg", "schema_tokens": 20, "relative_tokens": "1.00x", "description": "Measured token floor for non-empty structural graph packets, including 1-hop and 2-hop queries."},
    {"format": "svo", "schema_tokens": 0, "relative_tokens": "~1.1x", "description": "Self-describing SVO triples. Zero schema overhead — LLMs read cold. Best for small 1-hop queries."},
    {"format": "lowlevel", "schema_tokens": 20, "relative_tokens": "1.03x", "description": "XML-tagged adjacency. Slightly more tokens than gg."},
    {"format": "sql", "schema_tokens": 10, "relative_tokens": "1.38x+", "description": "Table row layout. Useful as an interpretability fallback if a model fails compact graph reasoning."},
    {"format": "semantic_arrow", "schema_tokens": 15, "relative_tokens": "1.49x", "description": "Subject-verb-object arrows with @nodes/@edges preamble. Token winner only for zero-edge packets in current real-project tests."},
    {"format": "gg_hybrid", "schema_tokens": 20, "relative_tokens": "~1.6x", "description": "gg + inline node kind/summary. Use only when grounded prose is required."},
    {"format": "doc_summary", "schema_tokens": 2, "relative_tokens": "~0.6x", "description": "Grounded section/file notes with no topology. Best for README/docs/install/usage questions."},
    {"format": "hybrid", "schema_tokens": 5, "relative_tokens": "~2.3x", "description": "Markdown bullet lists. Readable but high token overhead."},
    {"format": "json", "schema_tokens": 0, "relative_tokens": "3.9-6.7x", "description": "Raw JSON. Never use as LLM wire format."},
    {"format": ".gg file", "schema_tokens": 0, "relative_tokens": "binary", "description": "Native full-fidelity binary storage format. Decode it before rendering an LLM packet."},
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
        return content(json.dumps(plan.__dict__))
    if name == "final_packet":
        return content(build_final_packet(args))
    if name == "full_graph":
        return content(build_full_graph(args))
    if name == "query_context":
        return content(build_query_context(args))
    if name == "project_status":
        return content(handle_project_status(args))
    if name == "validate_packet":
        packet = args.get("packet")
        if packet:
            result = validate_any(str(packet))
        else:
            graph_path = Path(args["graph_path"]) if args.get("graph_path") else find_graph_path()
            result = validate_graph_file(graph_path)
        return content(json.dumps({
            "ok": result.ok,
            "format": result.format,
            "node_count": result.node_count,
            "edge_count": result.edge_count,
            "errors": list(result.errors),
        }))
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
    if name == "compile_context":
        graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else find_graph_path()
        runtime = GraphRuntime(
            load_any(graph_path),
            (StructuralEvidenceProvider(), CpgEvidenceProvider()),
            evidence_store=EvidenceStore(graph_path.parent / "evidence.db"),
            source_planner=QuerySourcePlanner(graph_path.parent, graph_path=graph_path),
        )
        result = runtime.compile(GraphProgram(
            query=str(args["query"]),
            query_class=str(args.get("query_class") or "auto"),
            packet=str(args.get("packet") or "gg"),
            passes=tuple(str(value) for value in args.get("passes") or []),
            scopes=tuple(str(value) for value in args.get("scopes") or []),
            max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else None,
        ))
        return content(result.envelope())
    if name == "repair_context":
        graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else find_graph_path()
        data = build_repair_context(
            load_any(graph_path),
            str(args["issue"]),
            max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else 30,
            hops=int(args["hops"]) if args.get("hops") is not None else 2,
        )
        return content(json.dumps(data, indent=2, ensure_ascii=False))
    if name == "graph_change":
        packet = build_change_packet(
            load_any(Path(str(args["before_path"]))),
            load_any(Path(str(args["after_path"]))),
            impact_hops=int(args["impact_hops"]) if args.get("impact_hops") is not None else 2,
        )
        return content(packet.to_json())
    if name == "memory_context":
        store = MemoryStore(Path(str(args.get("store_path") or ".graphgraph/memory.json")))
        operation = str(args["operation"])
        scopes = tuple(str(value) for value in args.get("scopes") or [])
        if operation == "add":
            if not args.get("text"):
                raise ValueError("memory_context add requires text")
            record = store.remember(
                str(args["text"]),
                scope=scopes[0] if scopes else "project",
                kind=str(args.get("kind") or "fact"),
                related_nodes=tuple(str(value) for value in args.get("related_nodes") or []),
            )
            data: object = record.__dict__
        elif operation == "query":
            if not args.get("text"):
                raise ValueError("memory_context query requires text")
            data = [record.__dict__ for record in store.search(
                str(args["text"]),
                scopes=scopes,
                limit=int(args["limit"]) if args.get("limit") is not None else 10,
            )]
        elif operation == "list":
            data = [record.__dict__ for record in store.read(scopes=scopes)]
        else:
            raise ValueError(f"unknown memory operation: {operation}")
        return content(json.dumps(data, indent=2, ensure_ascii=False))
    if name == "graph_at_time":
        graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else find_graph_path()
        graph = graph_as_of(load_any(graph_path), str(args["timestamp"]))
        return content(json.dumps({
            "as_of": str(args["timestamp"]),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "active_nodes": sum(node.active for node in graph.nodes.values()),
            "active_edges": sum(edge.active for edge in graph.edges),
        }, indent=2))
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
    refreshed_graph = None
    refresh_metadata = None
    sync_git = str(args.get("sync") or "none") == "git"
    if changed_paths or deleted_paths or sync_git:
        status = refresh_saved_graph(
            directory=Path(str(args.get("directory") or ".")),
            output_path=graph_path,
            changed_paths=changed_paths,
            deleted_paths=deleted_paths,
            sync_git=sync_git,
            max_nodes=int(args["scan_max_nodes"])
            if args.get("scan_max_nodes") is not None
            else DEFAULT_SCAN_MAX_NODES,
            depth=str(args["depth"]) if args.get("depth") else None,
            frontend=str(args["frontend"]) if args.get("frontend") else None,
            docs=bool(args["docs"]) if "docs" in args else None,
            history=bool(args["history"]) if "history" in args else None,
        )
        if status.built:
            refreshed_graph = status.graph
        refresh_metadata = refresh_receipt(
            status,
            mode="git" if sync_git else "explicit",
            requested_changed_paths=tuple(changed_paths),
            requested_deleted_paths=tuple(deleted_paths),
        )
        anchor_paths = tuple(dict.fromkeys((*changed_paths, *status.changed_paths)))
    else:
        anchor_paths = ()
    freshness = (
        {"fresh": True, "changed_count": 0, "deleted_count": 0, "changed_paths": [], "deleted_paths": []}
        if sync_git
        else inspect_saved_graph_freshness(
            directory=Path(str(args.get("directory") or ".")),
            output_path=graph_path,
        )
    )
    metadata: dict[str, object] = {
        "freshness": scope_freshness(
            freshness,
            tuple(dict.fromkeys((*changed_paths, *deleted_paths))),
        )
    }
    if refresh_metadata is not None:
        metadata["refresh"] = refresh_metadata
    return render_query_context(
        query=str(args["query"]),
        query_class=str(args.get("query_class") or "auto"),
        graph_path=graph_path,
        packet=str(args["packet"]) if args.get("packet") else None,
        hops=int(args["hops"]) if args.get("hops") is not None else None,
        anchor_limit=int(args["anchor_limit"]) if args.get("anchor_limit") is not None else None,
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else None,
        scopes=tuple(str(scope) for scope in args.get("scopes") or []),
        scope_mode=str(args.get("scope_mode") or "strict"),
        show_anchors=bool(args.get("show_anchors")),
        cache_namespace="mcp_query",
        json_anchors=True,
        graph=refreshed_graph,
        response_metadata=metadata,
        source_mode=str(args.get("source_mode") or "auto"),
        memory_scopes=tuple(str(scope) for scope in args.get("memory_scopes") or ("project", "session")),
        anchor_paths=anchor_paths,
        include_snippets=bool(args.get("include_snippets")),
        snippet_limit=int(args["snippet_limit"]) if args.get("snippet_limit") is not None else 3,
        snippet_context_lines=(
            int(args["snippet_context_lines"])
            if args.get("snippet_context_lines") is not None
            else 2
        ),
        snippet_max_lines=(
            int(args["snippet_max_lines"])
            if args.get("snippet_max_lines") is not None
            else 24
        ),
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


def handle_project_status(args: dict[str, Any]) -> str:
    directory = Path(str(args.get("directory") or "."))
    graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else None
    report = build_project_status(
        directory=directory,
        graph_path=graph_path,
        run_probes=bool(args.get("probe")),
    )
    return json.dumps(report, indent=2, ensure_ascii=False)


def handle_build_graph(args: dict[str, Any]) -> str:
    input_graph_str = args.get("input_graph")
    output_path_str = args.get("output_path") or ".graphgraph/graph.gg"
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if input_graph_str:
        graph = load_any(Path(input_graph_str), normalize_external_refs=True)
        validation = save_validated_graph(graph, output_path)
        return json.dumps({
            "action": "ingested",
            "source": input_graph_str,
            "output": str(output_path),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "validation": {"ok": validation.ok, "format": validation.format},
        })

    directory = Path(args.get("directory") or ".")
    max_nodes = int(args["max_nodes"]) if args.get("max_nodes") is not None else DEFAULT_SCAN_MAX_NODES
    generic_mentions = bool(args.get("generic_mentions", False))
    skip_dirs = [str(d) for d in args.get("skip_dirs") or []]
    exclude_dirs = [str(d) for d in args.get("exclude_dirs") or []]
    include_dirs = [str(d) for d in args.get("include_dirs") or []]
    # Merge exclude_dirs into skip_dirs (exclude_dirs is an intuitive alias)
    all_skip = skip_dirs + [d for d in exclude_dirs if d not in skip_dirs]
    depth = str(args.get("depth") or "files")
    frontend = str(args.get("frontend") or "auto")
    docs = bool(args.get("docs", False))
    history = bool(args.get("history", False))
    incremental = bool(args.get("incremental", True))

    status = scan_validated_graph(
        directory=directory,
        output_path=output_path,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=tuple(all_skip),
        include_dirs=tuple(include_dirs),
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        incremental=incremental,
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None
    result = {
        "action": "scanned",
        "directory": str(directory.resolve()),
        "output": str(output_path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "frontend": graph.metadata.get("frontend", "files"),
        "phase_profile": {
            "docs_ms": float(graph.metadata.get("docs_profile_ms", "0")),
            # `docs_files` counts documents parsed into heading/paragraph
            # sections; `doc_nodes` counts doc-kind nodes that actually landed
            # (markdown/rst/etc. ingested as file nodes). Reporting both keeps
            # the receipt honest: on repos where docs fall back to file-level
            # (no section parser), docs_files is 0 while doc_nodes is not -- the
            # docs are present, they just weren't parsed into prose.
            "docs_files": int(graph.metadata.get("docs_profile_files", "0")),
            "doc_nodes": graph_shape(graph)["doc_nodes"],
            "docs_slowest": json.loads(graph.metadata.get("docs_profile_slowest", "[]")),
            "docs_truncated": int(graph.metadata.get("docs_truncated_count", "0")),
            "docs_truncated_files": [
                path for path in graph.metadata.get("docs_truncated_files", "").split(",") if path
            ],
            "source_concepts_ms": float(graph.metadata.get("source_concepts_profile_ms", "0")),
            "source_concept_candidates": int(graph.metadata.get("source_concepts_candidates", "0")),
            "source_concept_links": int(graph.metadata.get("source_concepts_links", "0")),
        },
        "exclusions": {
            "explicit_dirs": all_skip,
            "force_included_dirs": include_dirs,
            "ignore_files": [
                path for path in graph.metadata.get("ignore_rule_files", "").split(",") if path
            ],
            "ignored_files": int(graph.metadata.get("ignored_by_rules", "0")),
            "ignored_dirs": int(graph.metadata.get("ignore_pruned_dir_count", "0")),
            "ignored_dir_sample": [
                path for path in graph.metadata.get("ignore_pruned_dirs", "").split(",") if path
            ],
            "default_pruned_dirs": int(graph.metadata.get("default_pruned_dir_count", "0")),
        },
        "repaired": status.repaired,
        "validation": {"ok": validation.ok, "format": validation.format},
    }
    # Surface truncation to MCP-only callers too -- they never see the CLI's
    # printed warnings, so an incomplete graph would otherwise look identical
    # to a complete one from this response alone.
    if graph.metadata.get("files_truncated") == "true":
        result["files_truncated"] = True
        result["files_total_matched"] = graph.metadata.get("files_total_matched")
    if graph.metadata.get("symbols_truncated") == "true":
        result["symbols_truncated"] = True
        result["symbols_cap"] = graph.metadata.get("symbols_cap")
    return json.dumps(result)


def _require_paths(args: dict[str, Any], tool: str) -> list[str]:
    """Validate the required ``paths`` arg with an actionable message.

    A bare ``args["paths"]`` surfaced as a cryptic MCP ``-32000: 'paths'`` when
    a caller omitted it. The schema marks ``paths`` required, but the server
    should still fail with a message that says what to pass, not just the key
    name -- consistent with the tool's honest, actionable-error contract.
    """
    raw = args.get("paths")
    if not raw:
        raise ValueError(
            f"{tool} requires 'paths': a non-empty list of file paths "
            "(repo-relative or absolute) to operate on."
        )
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{tool} 'paths' must be a list of file paths, got {type(raw).__name__}.")
    return [str(p) for p in raw]


def handle_update_graph_files(args: dict[str, Any]) -> str:
    directory = Path(args.get("directory") or ".")
    output_path = Path(args.get("output_path") or ".graphgraph/graph.gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paths = _require_paths(args, "update_graph_files")

    status = update_paths_validated_graph(
        directory=directory,
        output_path=output_path,
        paths=paths,
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else DEFAULT_SCAN_MAX_NODES,
        depth=str(args.get("depth") or "symbols"),
        frontend=str(args.get("frontend") or "auto"),
        docs=bool(args.get("docs", False)),
        history=bool(args.get("history", False)),
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None
    result = {
        "action": "updated",
        "paths": paths,
        "output": str(output_path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "repaired": status.repaired,
        "validation": {"ok": validation.ok, "format": validation.format},
    }
    if graph.metadata.get("symbols_truncated") == "true":
        result["symbols_truncated"] = True
        result["symbols_cap"] = graph.metadata.get("symbols_cap")
    return json.dumps(result)


def handle_remove_graph_files(args: dict[str, Any]) -> str:
    directory = Path(args.get("directory") or ".")
    output_path = Path(args.get("output_path") or ".graphgraph/graph.gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paths = _require_paths(args, "remove_graph_files")

    status = remove_paths_validated_graph(
        directory=directory,
        output_path=output_path,
        paths=paths,
        max_nodes=int(args["max_nodes"]) if args.get("max_nodes") is not None else DEFAULT_SCAN_MAX_NODES,
        depth=str(args.get("depth") or "symbols"),
        frontend=str(args.get("frontend") or "auto"),
        docs=bool(args.get("docs", False)),
        history=bool(args.get("history", False)),
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None
    return json.dumps({
        "action": "removed",
        "paths": paths,
        "output": str(output_path),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "repaired": status.repaired,
        "validation": {"ok": validation.ok, "format": validation.format},
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

    return json.dumps({
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
