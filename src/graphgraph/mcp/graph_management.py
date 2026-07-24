"""MCP schemas and handlers for graph build, splice, removal, and export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..io import find_graph_path, load_any, save_gg, save_validated_graph
from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..services.lifecycle import (
    remove_paths_validated_graph,
    scan_validated_graph,
    update_paths_validated_graph,
)
from ..services.project_status import graph_shape
from .machine_contract import compact_json

GRAPH_MANAGEMENT_TOOLS: list[dict[str, Any]] = [
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
                "directory": {
                    "type": "string",
                    "description": "Directory to scan. Defaults to current working directory.",
                },
                "input_graph": {
                    "type": "string",
                    "description": "Path to an existing graph JSON (e.g. graphify output) to ingest instead of scanning.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Where to save the graph. Defaults to .graphgraph/graph.gg.",
                },
                "max_nodes": {
                    "type": "integer",
                    "description": f"Max file/node count during directory scan. Default: {DEFAULT_SCAN_MAX_NODES}.",
                },
                "generic_mentions": {
                    "type": "boolean",
                    "description": "Also add weak 'references' edges for any file that mentions another file's name. Useful for docs-heavy repos. Default: false.",
                },
                "skip_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra directory names to exclude (beyond built-ins). E.g. ['spikes', 'test-inputs'].",
                },
                "exclude_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alias for skip_dirs — extra directory names to exclude. Merged with skip_dirs if both supplied.",
                },
                "include_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Directory names to keep even though a default skip rule would drop them. E.g. ['build', 'out'].",
                },
                "depth": {
                    "type": "string",
                    "enum": ["files", "symbols"],
                    "description": "'files' (default): one node per file. 'symbols': adds native function/class/struct nodes with call/reference edges.",
                },
                "frontend": {
                    "type": "string",
                    "enum": ["auto", "regex", "tree_sitter"],
                    "description": "Symbol extraction frontend for depth=symbols. auto prefers Tree-sitter when available.",
                },
                "docs": {
                    "type": "boolean",
                    "description": "Extract document sections and concept nodes from Markdown/RST/HTML/text.",
                },
                "history": {
                    "type": "boolean",
                    "description": "Link qualifying bug-fix commits (git log, regex-classified) to the files they touched via a 'fixes' edge. Opt-in; requires a git repo. Default: false.",
                },
                "incremental": {
                    "type": "boolean",
                    "description": "Enable hash-based incremental scanning. Defaults to true.",
                },
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
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File(s) that changed, relative to directory or absolute.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory root. Defaults to current working directory.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Existing graph path to update. Defaults to .graphgraph/graph.gg.",
                },
                "max_nodes": {
                    "type": "integer",
                    "description": f"Max symbols per file batch. Default: {DEFAULT_SCAN_MAX_NODES}.",
                },
                "depth": {"type": "string", "enum": ["files", "symbols"], "description": "Default: symbols."},
                "frontend": {"type": "string", "enum": ["auto", "regex", "tree_sitter"]},
                "docs": {
                    "type": "boolean",
                    "description": "Extract document sections/concepts for doc files among paths.",
                },
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
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File(s) that no longer exist, relative to directory or absolute.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory root. Defaults to current working directory.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Existing graph path to update. Defaults to .graphgraph/graph.gg.",
                },
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
]

GRAPH_MANAGEMENT_TOOL_NAMES = frozenset(tool["name"] for tool in GRAPH_MANAGEMENT_TOOLS)


def handle_build_graph(args: dict[str, Any]) -> str:
    input_graph_str = args.get("input_graph")
    output_path = Path(args.get("output_path") or ".graphgraph/graph.gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if input_graph_str:
        graph = load_any(Path(input_graph_str), normalize_external_refs=True)
        validation = save_validated_graph(graph, output_path)
        return compact_json(
            {
                "action": "ingested",
                "source": input_graph_str,
                "output": str(output_path),
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "validation": {"ok": validation.ok, "format": validation.format},
            }
        )

    directory = Path(args.get("directory") or ".")
    max_nodes = int(args["max_nodes"]) if args.get("max_nodes") is not None else DEFAULT_SCAN_MAX_NODES
    skip_dirs = [str(value) for value in args.get("skip_dirs") or []]
    exclude_dirs = [str(value) for value in args.get("exclude_dirs") or []]
    all_skip = skip_dirs + [value for value in exclude_dirs if value not in skip_dirs]
    include_dirs = [str(value) for value in args.get("include_dirs") or []]
    status = scan_validated_graph(
        directory=directory,
        output_path=output_path,
        max_nodes=max_nodes,
        generic_mentions=bool(args.get("generic_mentions", False)),
        skip_dirs=tuple(all_skip),
        include_dirs=tuple(include_dirs),
        depth=str(args.get("depth") or "files"),
        frontend=str(args.get("frontend") or "auto"),
        docs=bool(args.get("docs", False)),
        history=bool(args.get("history", False)),
        incremental=bool(args.get("incremental", True)),
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
            "ignore_files": [path for path in graph.metadata.get("ignore_rule_files", "").split(",") if path],
            "ignored_files": int(graph.metadata.get("ignored_by_rules", "0")),
            "ignored_dirs": int(graph.metadata.get("ignore_pruned_dir_count", "0")),
            "ignored_dir_sample": [path for path in graph.metadata.get("ignore_pruned_dirs", "").split(",") if path],
            "default_pruned_dirs": int(graph.metadata.get("default_pruned_dir_count", "0")),
        },
        "repaired": status.repaired,
        "validation": {"ok": validation.ok, "format": validation.format},
    }
    if graph.metadata.get("files_truncated") == "true":
        result["files_truncated"] = True
        result["files_total_matched"] = graph.metadata.get("files_total_matched")
    if graph.metadata.get("symbols_truncated") == "true":
        result["symbols_truncated"] = True
        result["symbols_cap"] = graph.metadata.get("symbols_cap")
    return compact_json(result)


def _require_paths(args: dict[str, Any], tool: str) -> list[str]:
    raw = args.get("paths")
    if not raw:
        raise ValueError(
            f"{tool} requires 'paths': a non-empty list of file paths (repo-relative or absolute) to operate on."
        )
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{tool} 'paths' must be a list of file paths, got {type(raw).__name__}.")
    return [str(path) for path in raw]


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
    return compact_json(result)


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
    return compact_json(
        {
            "action": "removed",
            "paths": paths,
            "output": str(output_path),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "repaired": status.repaired,
            "validation": {"ok": validation.ok, "format": validation.format},
        }
    )


def handle_export_graph(args: dict[str, Any]) -> str:
    graph_path = Path(args["graph_path"]) if args.get("graph_path") else find_graph_path()
    graph = load_any(graph_path)
    output_path = Path(args["output_path"]) if args.get("output_path") else graph_path.with_suffix(".gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_gg(graph, output_path)
    return compact_json(
        {"output": str(output_path), "nodes": len(graph.nodes), "edges": len(graph.edges), "format": "gg"}
    )
