"""Schemas and handlers for advanced GraphGraph platform MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import find_graph_path, load_any
from ..packets import packet_format_schema
from ..planning import query_class_schema
from ..platform import (
    GraphProgram,
    MemoryStore,
    build_change_packet,
    compiler_pass_schema,
    create_graph_runtime,
    graph_as_of,
    repair_context_json,
)
from .machine_contract import compact_json

PLATFORM_TOOLS: list[dict[str, Any]] = [
    {
        "name": "compile_context",
        "description": "Compile a query through GraphGraph's LLM-native graph IR, optional evidence/inference/hierarchy passes, budgeted retrieval, compact packet rendering, and validation receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "graph_path": {"type": "string"},
                "query_class": query_class_schema(include_auto=True, default="auto"),
                "packet": packet_format_schema(default="gg"),
                "passes": compiler_pass_schema(),
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
                "store_path": {
                    "type": "string",
                    "default": ".graphgraph/memory.json",
                },
                "scopes": {"type": "array", "items": {"type": "string"}},
                "kind": {"type": "string", "default": "fact"},
                "related_nodes": {"type": "array", "items": {"type": "string"}},
                "graph_path": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["operation"],
        },
    },
    {
        "name": "graph_at_time",
        "description": "Materialize an ISO-timestamped graph only with complete validity windows; otherwise refuse explicitly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string"},
                "graph_path": {"type": "string"},
            },
            "required": ["timestamp"],
        },
    },
]

PLATFORM_TOOL_NAMES = frozenset(tool["name"] for tool in PLATFORM_TOOLS)


def handle_platform_tool(name: str, args: dict[str, Any]) -> str:
    """Execute one advanced platform tool and return its existing text payload."""
    if name == "compile_context":
        graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else find_graph_path()
        runtime = create_graph_runtime(graph_path)
        result = runtime.compile(
            GraphProgram(
                query=str(args["query"]),
                query_class=str(args.get("query_class") or "auto"),
                packet=str(args.get("packet") or "gg"),
                passes=tuple(str(value) for value in args.get("passes") or []),
                scopes=tuple(str(value) for value in args.get("scopes") or []),
                max_nodes=(int(args["max_nodes"]) if args.get("max_nodes") is not None else None),
            )
        )
        return result.envelope()
    if name == "repair_context":
        graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else find_graph_path()
        return repair_context_json(
            load_any(graph_path),
            str(args["issue"]),
            max_nodes=(int(args["max_nodes"]) if args.get("max_nodes") is not None else 30),
            hops=int(args["hops"]) if args.get("hops") is not None else 2,
        )
    if name == "graph_change":
        packet = build_change_packet(
            load_any(Path(str(args["before_path"]))),
            load_any(Path(str(args["after_path"]))),
            impact_hops=(int(args["impact_hops"]) if args.get("impact_hops") is not None else 2),
        )
        return packet.to_json()
    if name == "memory_context":
        store = MemoryStore(Path(str(args.get("store_path") or ".graphgraph/memory.json")))
        operation = str(args["operation"])
        scopes = tuple(str(value) for value in args.get("scopes") or [])
        if operation == "add":
            if not args.get("text"):
                raise ValueError("memory_context add requires text")
            try:
                graph_path = (
                    Path(str(args["graph_path"]))
                    if args.get("graph_path")
                    else find_graph_path()
                )
                memory_graph = load_any(graph_path)
            except FileNotFoundError:
                memory_graph = None
            record = store.remember(
                str(args["text"]),
                scope=scopes[0] if scopes else "project",
                kind=str(args.get("kind") or "fact"),
                related_nodes=tuple(str(value) for value in args.get("related_nodes") or []),
                graph=memory_graph,
                anchor_limit=8,
            )
            data: object = record.__dict__
        elif operation == "query":
            if not args.get("text"):
                raise ValueError("memory_context query requires text")
            data = [
                record.__dict__
                for record in store.search(
                    str(args["text"]),
                    scopes=scopes,
                    limit=(int(args["limit"]) if args.get("limit") is not None else 10),
                )
            ]
        elif operation == "list":
            data = [record.__dict__ for record in store.read(scopes=scopes)]
        else:
            raise ValueError(f"unknown memory operation: {operation}")
        return compact_json(data)
    if name == "graph_at_time":
        graph_path = Path(str(args["graph_path"])) if args.get("graph_path") else find_graph_path()
        graph = graph_as_of(load_any(graph_path), str(args["timestamp"]))
        return compact_json(
            {
                "as_of": str(args["timestamp"]),
                "status": graph.metadata.get("temporal_status", "unknown"),
                "reason": graph.metadata.get("temporal_reason", ""),
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "active_nodes": sum(node.active for node in graph.nodes.values()),
                "active_edges": sum(edge.active for edge in graph.edges),
            },
        )
    raise ValueError(f"unknown platform tool: {name}")
