"""Schemas and handlers for GraphGraph's MCP introspection tools."""

from __future__ import annotations

from typing import Any

from ..graph.ontology import relation_records
from ..graph.traversal import policy_records
from ..packet_targets import TARGET_TABLE
from ..planning import query_class_schema
from ..scanner.frontends import available_frontends
from .machine_contract import compact_json

FORMAT_TABLE = list(TARGET_TABLE)

DESCRIPTION_TOOLS: list[dict[str, Any]] = [
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
                "family": {
                    "type": "string",
                    "description": "Optional relation family filter.",
                },
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
                "query_class": query_class_schema(),
            },
        },
    },
]

DESCRIPTION_TOOL_NAMES = frozenset(tool["name"] for tool in DESCRIPTION_TOOLS)


def handle_description_tool(name: str, args: dict[str, Any]) -> str:
    """Return the compact payload for one introspection tool."""
    if name == "describe_formats":
        return compact_json(FORMAT_TABLE)
    if name == "describe_ontology":
        family = args.get("family")
        return compact_json(relation_records(str(family) if family else None))
    if name == "describe_frontends":
        return compact_json([cap.__dict__ for cap in available_frontends()])
    if name == "describe_traversal":
        query_class = args.get("query_class")
        return compact_json(policy_records(str(query_class) if query_class else None))
    raise ValueError(f"unknown description tool: {name}")
