"""CLI commands for query planning, symbol selection, and graph profiling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..io import find_graph_path, load_any
from ..planning import plan_context, profile_graph_shape, recommend_node_budget
from ..retrieval.predicates import parse_criteria, select_symbols
from .output import emit_json


def cmd_plan(args: argparse.Namespace) -> None:
    plan = plan_context(args.query_class, getattr(args, "query", ""))
    print(
        f"{plan.hops}hop {plan.direction} {plan.packet} "
        f"n={plan.node_budget} anchors={plan.anchor_limit}: {plan.reason}"
    )


def cmd_select(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    try:
        criteria = parse_criteria(args.predicate, limit=args.limit)
    except ValueError as exc:
        raise SystemExit(f"graphgraph select: {exc}") from exc
    result = select_symbols(graph, criteria, mode=args.mode)

    if args.json:
        emit_json(
            {
                "mode": result.mode,
                "total": result.total,
                "exists": result.exists,
                "truncated": result.truncated,
                "criteria": result.criteria_detail,
                "caller_evidence": result.caller_evidence,
                "caller_evidence_complete": result.caller_evidence_complete,
                "symbols": result.symbols,
            },
            getattr(args, "pretty", False),
        )
        return

    if args.mode == "exists":
        print("yes" if result.exists else "no")
    elif args.mode == "count":
        print(result.total)
    else:
        for symbol in result.symbols:
            location = (
                f"{symbol['path']}:{symbol['line']}"
                if symbol["line"]
                else symbol["path"]
            )
            marker = " [test]" if symbol["is_test"] else ""
            print(
                f"{symbol['label']}  ({symbol['kind']}) {location}"
                f"  callers={symbol['callers']} "
                f"production={symbol['production_callers']}{marker}"
            )
        print(f"-- {result.total} match(es){', truncated' if result.truncated else ''}")

    print(f"-- where {result.criteria_detail}")
    if not result.caller_evidence_complete:
        print(f"-- CAVEAT: {result.caller_evidence}")


def cmd_profile(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    shape = profile_graph_shape(graph)
    query = getattr(args, "query", "")
    report = {
        "graph": str(graph_path),
        "shape": shape.__dict__,
        "frontend_quality": {
            "member_calls": {
                "resolved": int(graph.metadata.get("member_calls_resolved", "0")),
                "ambiguous": int(graph.metadata.get("member_calls_ambiguous", "0")),
                "unresolved": int(graph.metadata.get("member_calls_unresolved", "0")),
                "scope": graph.metadata.get(
                    "member_call_telemetry_scope", "unavailable"
                ),
            },
            "fallback_files": int(graph.metadata.get("frontend_fallback_count", "0")),
            "failed_files": int(graph.metadata.get("frontend_failure_count", "0")),
        },
        "budget_candidates": [
            recommend_node_budget(query_class, query, shape).__dict__
            for query_class in (
                "direct_lookup",
                "reverse_lookup",
                "multi_hop_path",
                "blast_radius",
                "subsystem_summary",
                "negative_query",
            )
        ],
    }
    print(json.dumps(report, indent=2))
