"""Schemas and handlers for GraphGraph's MCP introspection tools."""

from __future__ import annotations

import json
from typing import Any

from ..graph.ontology import DEFAULT_RELATIONS
from ..graph.traversal import POLICIES, traversal_policy
from ..packet_targets import TARGET_TABLE
from ..planning import query_class_schema
from ..scanner.frontends import available_frontends

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


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def handle_description_tool(name: str, args: dict[str, Any]) -> str:
    """Return the compact payload for one introspection tool."""
    if name == "describe_formats":
        return _json(FORMAT_TABLE)
    if name == "describe_ontology":
        family = args.get("family")
        rows = [
            {
                "name": relation_name,
                "family": spec.family,
                "direction": spec.direction,
                "strength": spec.strength,
                "traversable": spec.traversable,
                "weak": spec.weak,
                "description": spec.description,
            }
            for relation_name, spec in DEFAULT_RELATIONS.items()
            if not family or spec.family == family
        ]
        return _json(rows)
    if name == "describe_frontends":
        return _json([cap.__dict__ for cap in available_frontends()])
    if name == "describe_traversal":
        if args.get("query_class"):
            return _json(traversal_policy(str(args["query_class"])).__dict__)
        return _json(
            {query_class: policy.__dict__ for query_class, policy in POLICIES.items()}
        )
    raise ValueError(f"unknown description tool: {name}")
