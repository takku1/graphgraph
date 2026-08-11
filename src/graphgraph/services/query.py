"""One read-only query facade over GraphGraph's specialized operators."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..io import find_graph_path, load_any
from ..planning.query_compiler import QueryOperator, QueryPlan, compile_query


def _plan_payload(plan: QueryPlan) -> dict[str, object]:
    payload = asdict(plan)
    payload["operator"] = plan.operator.value
    payload["fallback"] = plan.fallback.value if plan.fallback else None
    return payload


def _resolve_graph(directory: Path, graph_path: Path | None) -> Path | None:
    if graph_path is not None:
        return graph_path if graph_path.exists() else None
    try:
        return find_graph_path(directory)
    except (FileNotFoundError, RuntimeError):
        return None


def _needs_index(
    query_text: str,
    directory: Path,
    graph_path: Path | None,
    plan: QueryPlan,
) -> dict[str, object]:
    output = graph_path or directory / ".graphgraph" / "graph.gg"
    return {
        "status": "needs_index",
        "query": query_text,
        "operator": plan.operator.value,
        "plan": _plan_payload(plan),
        "result": None,
        "action": {
            "operator": "build_graph",
            "arguments": {
                "directory": str(directory),
                "output_path": str(output),
            },
            "requires_explicit_execution": True,
        },
        "receipt": {
            "mutating": False,
            "graph_path": str(output),
            "reason": "no native graph exists; query never indexes implicitly",
        },
    }


def _selection_payload(result: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": result.mode,
        "total": result.total,
        "criteria": result.criteria_detail,
        "caller_evidence_complete": result.caller_evidence_complete,
        "caller_evidence": result.caller_evidence,
    }
    if result.mode == "exists":
        payload["exists"] = result.exists
    if result.mode == "select":
        payload["truncated"] = result.truncated
        payload["symbols"] = result.symbols
    return payload


def _search_payload(matches: list[object]) -> dict[str, object]:
    gap = None
    ambiguous = False
    if len(matches) >= 2 and matches[1].score > 0:
        gap = matches[0].score / matches[1].score
        ambiguous = gap < 1.3
    return {
        "matches": [
            {
                "id": match.node.id,
                "label": match.node.label,
                "kind": match.node.kind,
                "path": match.node.path,
                "line": match.node.line,
                "score": match.score,
                "reasons": list(match.reasons),
            }
            for match in matches
        ],
        "top_score_gap_ratio": gap,
        "ambiguous": ambiguous,
    }


def execute_query(
    query_text: str,
    *,
    directory: Path = Path("."),
    graph_path: Path | None = None,
    mode: str = "auto",
    result_mode: str = "select",
    target: str = "",
    direction: str = "",
    predicate: str = "",
    sync: str = "none",
    limit: int = 20,
    include_tests: bool = False,
    include_external: bool = False,
    query_class: str = "auto",
    packet: str | None = None,
    hops: int | None = None,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    source_mode: str = "auto",
    memory_scopes: tuple[str, ...] = ("project", "session"),
    representation: str = "flat",
    representation_budget: int | None = None,
    cache_namespace: str = "unified_query",
    include_context_freshness: bool = False,
) -> dict[str, object]:
    """Compile and execute one safe query without inferring mutations."""
    started = time.perf_counter()
    directory = directory.resolve()
    plan = compile_query(
        query_text,
        mode=mode,
        result_mode=result_mode,
        target=target,
        direction=direction,
        predicate=predicate,
    )
    resolved_graph = _resolve_graph(directory, graph_path)
    if resolved_graph is None:
        return _needs_index(query_text, directory, graph_path, plan)

    graph = None
    resident_status = None
    refresh: dict[str, object] | None = None
    freshness_detail: dict[str, object] | None = None
    freshness = "unchecked"
    if sync == "git":
        from .freshness import inspect_saved_graph_freshness, scope_freshness, source_root_for_saved_graph
        from .lifecycle import refresh_saved_graph

        source_root = source_root_for_saved_graph(resolved_graph)
        status = refresh_saved_graph(
            directory=source_root,
            output_path=resolved_graph,
            sync_git=True,
        )
        graph = status.graph
        resident_status = status
        freshness_detail = scope_freshness(
            inspect_saved_graph_freshness(
                directory=source_root,
                output_path=resolved_graph,
            ),
            scopes,
        )
        freshness = (
            "fresh"
            if freshness_detail["fresh"]
            else "incompatible"
            if not freshness_detail["extractor_compatible"]
            else "stale"
        )
        refresh = {
            "updated": len(status.changed_paths),
            "removed": len(status.deleted_paths),
            "write": status.built,
            "fresh": freshness == "fresh",
        }
    operator = plan.operator
    result: Any
    if operator is QueryOperator.RELATIONS:
        from ..retrieval.relations import encode_relation_micro, query_relations, query_saved_relations

        query = query_relations if graph is not None else query_saved_relations
        relation = query(
            graph if graph is not None else resolved_graph,
            str(plan.arguments["target"]),
            direction=str(plan.arguments["direction"]),  # type: ignore[arg-type]
            limit=limit,
            include_tests=include_tests,
            include_external=include_external,
            freshness=freshness,
        )
        if relation.get("status") != "ok" and plan.fallback is QueryOperator.CONTEXT:
            operator = QueryOperator.CONTEXT
        else:
            result = encode_relation_micro(relation)
    if operator is QueryOperator.CONTEXT and include_context_freshness and freshness_detail is None:
        from .freshness import inspect_saved_graph_freshness, scope_freshness, source_root_for_saved_graph

        freshness_detail = scope_freshness(
            inspect_saved_graph_freshness(
                directory=source_root_for_saved_graph(resolved_graph),
                output_path=resolved_graph,
            ),
            scopes,
        )
        freshness = (
            "fresh"
            if freshness_detail["fresh"]
            else "incompatible"
            if not freshness_detail["extractor_compatible"]
            else "stale"
        )
    if graph is None and operator is not QueryOperator.RELATIONS:
        graph = load_any(resolved_graph)
    if operator is QueryOperator.SELECT:
        from ..retrieval.predicates import parse_criteria, select_symbols

        criteria = parse_criteria(str(plan.arguments["predicate"]), limit=max(0, limit))
        selected = select_symbols(
            graph,
            criteria,
            mode=str(plan.arguments.get("mode") or result_mode),  # type: ignore[arg-type]
        )
        result = _selection_payload(selected)
    elif operator is QueryOperator.SEARCH:
        from ..retrieval.search import search_nodes

        result = _search_payload(
            search_nodes(graph, str(plan.arguments["query"]), limit=max(0, limit))
        )
    elif operator is QueryOperator.STATUS:
        from .project_status import build_project_status

        result = build_project_status(directory=directory, graph_path=resolved_graph)
    elif operator is QueryOperator.CONTEXT:
        from .compiler_driver import CompilerDriver, DriverRequest

        rendered, _status = CompilerDriver().compile(DriverRequest(
            query=query_text,
            query_class=query_class,
            directory=directory,
            graph_path=resolved_graph,
            resident_status=resident_status,
            packet=packet,
            hops=hops,
            anchor_limit=anchor_limit,
            max_nodes=max_nodes,
            scopes=scopes,
            scope_mode=scope_mode,
            show_anchors=True,
            json_output=True,
            json_details=True,
            cache_namespace=cache_namespace,
            sync_git=sync == "git",
            source_mode=source_mode,
            memory_scopes=memory_scopes,
            representation=representation,
            representation_budget=representation_budget,
        ))
        result = json.loads(rendered)

    execution_receipt: dict[str, object] = {
        "mutating": False,
        "graph_path": str(resolved_graph),
        "freshness": freshness,
        "refresh": refresh,
        "milliseconds": round((time.perf_counter() - started) * 1000, 3),
    }
    if freshness_detail is not None:
        execution_receipt["freshness_detail"] = freshness_detail
    return {
        "status": "ok",
        "query": query_text,
        "operator": operator.value,
        "plan": _plan_payload(plan),
        "result": result,
        "receipt": execution_receipt,
    }


def query(query_text: str, **kwargs: object) -> dict[str, object]:
    """Public Python API for :func:`execute_query`."""
    return execute_query(query_text, **kwargs)  # type: ignore[arg-type]


__all__ = ["execute_query", "query"]
