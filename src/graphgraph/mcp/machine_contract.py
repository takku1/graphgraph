"""Measurements for the recurring machine-facing MCP tool contract."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Iterable

MACHINE_TOOL_DESCRIPTIONS = {
    "plan_context": "ACT:plan retrieval by query_class; OUT:hops,packet,reason.",
    "final_packet": "ACT:render bounded graph packet; IN:starts=node IDs/paths; OUT:packet.",
    "full_graph": "ACT:render every active node/edge; USE:complete offline snapshot, not the default; SAFE:refuse above max_tokens.",
    "query_context": "ACT:retrieve from natural-language when node IDs are unknown; OUT:anchors,packet,receipts; MAY:refresh changed/deleted paths first.",
    "project_status": "ACT:report project graph status; OUT:validity,shape,freshness,packages,runtime probes.",
    "validate_packet": "ACT:validate packet or saved graph; OUT:ok,format,node_count,edge_count,errors.",
    "source_snippets": "ACT:read bounded source/code lines for node IDs,labels,or paths; USE:after retrieval when exact text is needed.",
    "build_graph": "ACT:scan/ingest and save graph; OUT:mutation+validation receipt; SAFE:built-in exclusions plus skip_dirs/exclude_dirs.",
    "update_graph_files": "ACT:re-extract exactly paths into saved graph; SAFE:requires prior build; missing paths mean removal; no tree walk.",
    "remove_graph_files": "ACT:drop removed paths from saved graph; SAFE:requires prior build; no extraction/tree walk.",
    "export_graph": "ACT:export native .gg; OUT:token-optimal self-describing graph.",
    "search_nodes": "ACT:find anchor IDs by label/path/kind; OUT:id,path,line,score,ambiguity; NEXT:final_packet or source_snippets.",
    "select_symbols": "ACT:set/count/exists over all symbols; SAFE:check caller_evidence_complete; false means zero-caller result is an upper bound.",
    "describe_formats": "ACT:list packet formats and token-cost data.",
    "describe_ontology": "ACT:list relation semantics,weights,and families.",
    "describe_frontends": "ACT:list extraction frontends and availability.",
    "describe_traversal": "ACT:list traversal policy by query_class.",
    "compile_context": "ACT:compile query through graph IR,retrieval,packet,and validation passes.",
    "repair_context": "ACT:turn issue/error/trace into bounded repair context; OUT:grounding receipt.",
    "graph_change": "ACT:compare before/after graphs; OUT:changes,blast radius,breaking changes,cursor.",
    "memory_context": "ACT:add/query/list scoped agent/project memory in graph IR.",
    "graph_at_time": "ACT:materialize graph at ISO timestamp using validity windows; OUT:compact status.",
}

MACHINE_CONTRACT_CHAR_CEILING = 9_850


def serialize_tool_contract(value: object) -> str:
    """Return the canonical representation used for context-cost gates."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def compact_json(value: object) -> str:
    """Serialize JSON-only MCP result text without presentation whitespace."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compact_tool_contracts(
    tools: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return schema-equivalent tools with dense routing text.

    Names, types, required fields, enums, and defaults carry machine semantics.
    Repeating prose on every property is recurring context cost, so tool-level
    contracts encode action/output/safety cues and property prose is removed.
    """

    compacted = deepcopy(list(tools))
    for tool in compacted:
        tool["description"] = MACHINE_TOOL_DESCRIPTIONS[tool["name"]]
        properties = tool.get("inputSchema", {}).get("properties", {})
        for spec in properties.values():
            spec.pop("description", None)
    return compacted


def tool_contract_size_receipt(tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Measure aggregate and per-tool characters plus a stable token proxy."""

    materialized = list(tools)
    aggregate_chars = len(serialize_tool_contract(materialized))
    return {
        "tools": len(materialized),
        "aggregate_chars": aggregate_chars,
        "proxy_tokens": (aggregate_chars + 3) // 4,
        "per_tool_chars": {tool["name"]: len(serialize_tool_contract(tool)) for tool in materialized},
    }


def tool_schema_snapshot(tools: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Extract routing-independent schema semantics for regression tests."""

    snapshot: dict[str, Any] = {}
    for tool in tools:
        schema = tool["inputSchema"]
        properties = schema.get("properties", {})
        snapshot[tool["name"]] = {
            "required": tuple(schema.get("required", ())),
            "enums": {name: tuple(spec["enum"]) for name, spec in properties.items() if "enum" in spec},
            "defaults": {name: spec["default"] for name, spec in properties.items() if "default" in spec},
        }
    return snapshot
