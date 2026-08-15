"""Compiler driver for project refresh, context compilation, and receipts."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..graph.core import Graph, Node
from ..io import find_graph_path, load_any_cached, remember_graph
from ..packets import estimate_tokens
from ..packets.validation import validate_any
from ..planning.routing import AUTOMATIC_ROUTE_MIN_CONFIDENCE
from ..platform.compiler import CompileOutcome, CompileRequest, ContextCompiler
from ..platform.source_planner import source_state_signature
from ..runtime.cache import (
    TopologicalKVCache,
    cache_file_for_graph,
    compute_cache_key,
    runtime_cache_fingerprint,
)
from ..surface import DEFAULT_SCAN_MAX_NODES
from .cache_identity import packet_dependency_paths, worktree_signature
from .control import GATE_ORDER, ControlReceipt, choose_next_action, render_control_ir
from .freshness import (
    inspect_saved_graph_freshness,
    refresh_receipt,
    scope_freshness,
    source_root_for_saved_graph,
)
from .lifecycle import GraphBuildStatus, ensure_native_graph, refresh_saved_graph
from .response_surface import clamp_response_to_packet_surface

QUERY_RESPONSE_CACHE_VERSION = "request_v19_affected_test_witness_attribution"

_DOCUMENT_EVIDENCE_KINDS = frozenset(
    {
        "concept",
        "section",
        "paragraph",
        "markdown",
        "rst",
        "html",
        "text",
    }
)


@dataclass(frozen=True)
class DriverRequest:
    """Complete project-compilation intent accepted by the compiler driver."""

    query: str
    query_class: str = "auto"
    directory: Path = Path(".")
    graph_path: Path | None = None
    resident_status: GraphBuildStatus | None = None
    rebuild: bool = False
    max_nodes: int | None = None
    scan_max_nodes: int = DEFAULT_SCAN_MAX_NODES
    packet: str | None = None
    hops: int | None = None
    anchor_limit: int | None = None
    scopes: tuple[str, ...] = ()
    scope_mode: str = "strict"
    skip_dirs: tuple[str, ...] = ()
    include_dirs: tuple[str, ...] = ()
    depth: str | None = "symbols"
    frontend: str | None = "auto"
    docs: bool | None = True
    history: bool | None = False
    generic_mentions: bool = False
    incremental: bool = True
    show_anchors: bool = False
    changed_paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()
    sync_git: bool = False
    json_output: bool = False
    json_details: bool = True
    source_mode: str = "auto"
    memory_scopes: tuple[str, ...] = ("project", "session")
    representation: str = "flat"
    representation_budget: int | None = None
    include_snippets: bool = False
    snippet_limit: int = 3
    snippet_context_lines: int = 2
    snippet_max_lines: int = 24
    cache_namespace: str = "cli_context"


class CompilerDriver:
    """Drive one complete project-context compilation through a single seam."""

    def compile(self, request: DriverRequest) -> tuple[str, GraphBuildStatus]:
        return _compile_project_context(**vars(request))


def _compile_project_context(
    *,
    query: str,
    query_class: str = "auto",
    directory: Path = Path("."),
    graph_path: Path | None = None,
    resident_status: GraphBuildStatus | None = None,
    rebuild: bool = False,
    max_nodes: int | None = None,
    scan_max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    packet: str | None = None,
    hops: int | None = None,
    anchor_limit: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    depth: str | None = "symbols",
    frontend: str | None = "auto",
    docs: bool | None = True,
    history: bool | None = False,
    generic_mentions: bool = False,
    incremental: bool = True,
    show_anchors: bool = False,
    changed_paths: tuple[str, ...] = (),
    deleted_paths: tuple[str, ...] = (),
    sync_git: bool = False,
    json_output: bool = False,
    json_details: bool = True,
    source_mode: str = "auto",
    memory_scopes: tuple[str, ...] = ("project", "session"),
    representation: str = "flat",
    representation_budget: int | None = None,
    include_snippets: bool = False,
    snippet_limit: int = 3,
    snippet_context_lines: int = 2,
    snippet_max_lines: int = 24,
    cache_namespace: str = "cli_context",
) -> tuple[str, GraphBuildStatus]:
    started = time.monotonic()
    if graph_path is not None and directory == Path("."):
        directory = source_root_for_saved_graph(graph_path)
    directory = directory.resolve()
    output_path = graph_path or directory / ".graphgraph" / "graph.gg"
    status = resident_status or ensure_native_graph(
        directory=directory,
        output_path=output_path,
        rebuild=rebuild,
        max_nodes=scan_max_nodes,
        skip_dirs=skip_dirs,
        include_dirs=include_dirs,
        depth=depth or "symbols",
        frontend=frontend or "auto",
        docs=True if docs is None else docs,
        history=False if history is None else history,
        generic_mentions=generic_mentions,
        incremental=incremental,
        discover_existing=graph_path is None,
    )
    refresh_started = time.monotonic()
    if resident_status is None and (changed_paths or deleted_paths or sync_git):
        status = refresh_saved_graph(
            directory=directory,
            output_path=status.path,
            changed_paths=list(changed_paths),
            deleted_paths=list(deleted_paths),
            sync_git=sync_git,
            max_nodes=scan_max_nodes,
            depth=depth,
            frontend=frontend,
            docs=docs,
            history=history,
        )
    refresh_ms = round((time.monotonic() - refresh_started) * 1000, 3)
    query_started = time.monotonic()
    requested_anchor_paths = tuple(
        dict.fromkeys((*changed_paths, *status.changed_paths))
    )
    repository_freshness = inspect_saved_graph_freshness(
        directory=directory,
        output_path=status.path,
    )
    workflow_metadata = {
        "workflow": {
            "refresh": refresh_receipt(
                status,
                mode=(
                    "git"
                    if sync_git
                    else "explicit"
                    if changed_paths or deleted_paths
                    else "none"
                ),
                requested_changed_paths=changed_paths,
                requested_deleted_paths=deleted_paths,
                attempted=bool(changed_paths or deleted_paths or sync_git),
                milliseconds=refresh_ms,
            ),
            "graph_validation": {
                "ok": bool(status.validation.ok) if status.validation else True,
                "format": (
                    status.validation.format
                    if status.validation
                    else "existing_valid_graph"
                ),
            },
            "freshness": scope_freshness(
                repository_freshness,
                tuple(dict.fromkeys((*changed_paths, *deleted_paths))),
            ),
        }
    }
    packet_text = _compile_response(
        query=query,
        query_class=query_class,
        graph_path=status.path,
        packet=packet,
        hops=hops,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        scopes=scopes,
        scope_mode=scope_mode,
        show_anchors=show_anchors or json_output,
        json_anchors=json_output,
        cache_namespace=cache_namespace,
        graph=status.graph if status.built else None,
        response_metadata=workflow_metadata,
        source_mode=source_mode,
        memory_scopes=memory_scopes,
        anchor_paths=requested_anchor_paths,
        representation=representation,
        representation_budget=representation_budget,
        include_snippets=include_snippets,
        snippet_limit=snippet_limit,
        snippet_context_lines=snippet_context_lines,
        snippet_max_lines=snippet_max_lines,
    )
    if json_output:
        payload = json.loads(packet_text)
        payload["workflow"]["query_milliseconds"] = round(
            (time.monotonic() - query_started) * 1000, 3
        )
        payload["workflow"]["total_milliseconds"] = round(
            (time.monotonic() - started) * 1000, 3
        )
        rendered_packet = str(payload.get("packet", ""))
        if rendered_packet:
            packet_validation = validate_any(rendered_packet)
            semantic_validation = payload.get("retrieval", {}).get(
                "semantic_validation",
                {"ok": True, "errors": []},
            )
            semantic_ok = bool(semantic_validation.get("ok", True))
            combined_ok = packet_validation.ok and semantic_ok
            payload["workflow"]["packet_validation"] = {
                "ok": combined_ok,
                "status": (
                    "semantic_fail"
                    if packet_validation.ok and not semantic_ok
                    else "packet_and_receipt_pass"
                    if combined_ok
                    else "structural_fail"
                ),
                "scope": "packet_and_receipt",
                "format": packet_validation.format,
                "nodes": packet_validation.node_count,
                "edges": packet_validation.edge_count,
                "errors": [
                    *packet_validation.errors,
                    *semantic_validation.get("errors", ()),
                ],
            }
        else:
            payload["workflow"]["packet_validation"] = {
                "ok": None,
                "status": "not_applicable",
                "scope": "packet_structure_only",
                "format": "none",
                "nodes": 0,
                "edges": 0,
                "errors": [],
            }
        if not json_details:
            payload = {
                "actionable": payload.get("actionable", {}),
                "control": payload.get("control", ""),
                "metrics": payload.get("metrics", {}),
                "query_class": payload.get("query_class", query_class),
                "routing": payload.get("routing", {}),
                "workflow": payload.get("workflow", {}),
                "details": {
                    "included": False,
                    "hint": (
                        "rerun with --json --details for packet, anchors, and "
                        "full provenance"
                    ),
                },
            }
        packet_text = json.dumps(payload, indent=2, ensure_ascii=False)
    return packet_text, status


def _compile_response(
    *,
    query: str,
    query_class: str = "auto",
    graph_path: Path | None = None,
    packet: str | None = None,
    hops: int | None = None,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    show_anchors: bool = False,
    cache_namespace: str = "query",
    json_anchors: bool = False,
    graph: Graph | None = None,
    response_metadata: dict[str, object] | None = None,
    source_mode: str = "auto",
    memory_scopes: tuple[str, ...] = ("project", "session"),
    anchor_paths: tuple[str, ...] = (),
    include_snippets: bool = False,
    snippet_limit: int = 3,
    snippet_context_lines: int = 2,
    snippet_max_lines: int = 24,
    representation: str = "flat",
    representation_budget: int | None = None,
) -> str:
    requested_query_class = query_class
    resolved_graph_path = graph_path or find_graph_path()
    from .freshness import source_root_for_saved_graph

    project_root = source_root_for_saved_graph(resolved_graph_path)
    source_signature = source_state_signature(project_root, graph_dir=resolved_graph_path.parent)
    request = CompileRequest(
        query=query,
        query_class=requested_query_class,
        packet=packet,
        scopes=scopes,
        max_nodes=max_nodes,
        hops=hops,
        anchor_limit=anchor_limit,
        scope_mode=scope_mode,
        anchor_paths=anchor_paths,
        representation=representation,
        representation_budget=representation_budget,
    )
    # Co-locate the packet cache with the graph it caches. Defaulting to
    # `.graphgraph/kv_cache.json` resolved it against the process CWD, so
    # querying another project's graph wrote entries into whichever
    # directory the command happened to run from -- polluting and evicting
    # that project's warm cache, and leaving `graphgraph cache --clear
    # --graph X` clearing a file that was never the one in use.
    cache = TopologicalKVCache(cache_file_for_graph(resolved_graph_path))
    cache_key = compute_cache_key(
        [query],
        requested_query_class,
        hops if hops is not None else -1,
        (
            f"{QUERY_RESPONSE_CACHE_VERSION}|{resolved_graph_path.resolve()}|"
            f"runtime={runtime_cache_fingerprint()}|"
            f"{cache_namespace}|{anchor_limit}|{max_nodes}|{scopes}|{scope_mode}|"
            f"{packet or 'auto'}|{show_anchors}|{json_anchors}|"
            f"{_cache_metadata_signature(response_metadata)}|"
            f"{source_mode}|{memory_scopes}|{source_signature}|"
            f"{worktree_signature(project_root)}"
            f"|{anchor_paths}|{include_snippets}|{snippet_limit}|"
            f"{snippet_context_lines}|{snippet_max_lines}"
            f"|{representation}|{representation_budget}"
        ),
    )
    # A caller-provided graph is the result of an in-process refresh. Query it
    # directly and bypass cache reads so the fused update/query operation can
    # neither re-parse the just-written graph nor return a pre-refresh packet.
    if graph is None:
        # Raw source windows must reflect the filesystem at call time. Do not
        # serve a whole-response packet cache entry when snippets are fused;
        # the graph itself still comes from the process-local load cache.
        if not include_snippets:
            cached_packet = cache.get(resolved_graph_path, cache_key)
            if cached_packet:
                return _with_cache_receipt(
                    cached_packet,
                    state="hit",
                    namespace=cache_namespace,
                    response_metadata=response_metadata,
                    json_response=json_anchors,
                )
        graph = load_any_cached(resolved_graph_path)
    else:
        remember_graph(resolved_graph_path, graph)

    compiled = ContextCompiler.open(
        resolved_graph_path,
        graph=graph,
        enable_evidence=False,
        source_mode=source_mode,
        memory_scopes=memory_scopes,
        changed_paths=anchor_paths,
    ).compile(request)
    graph = compiled.graph
    route = compiled.route
    query_class = route.query_class
    result = compiled.retrieval
    control, packet_metrics = _compiled_control_receipt(
        compiled,
        requested_query_class=requested_query_class,
        response_metadata=response_metadata,
    )
    if not result.starts:
        answerability = result.metadata.get("answerability", {})
        reason = str(answerability.get("reason", "no matching graph anchors"))
        message = f"GraphGraph abstained: {reason}."
        if json_anchors:
            payload: dict[str, object] = {
                "actionable": _actionable_receipt(
                    result,
                    response_metadata,
                    query_class=query_class,
                    graph=graph,
                ),
                "anchors": [],
                "packet": "",
                # Present even when abstaining, so a consumer can read one key
                # unconditionally instead of branching on whether a packet came
                # back. Empty packet, empty format.
                "packet_format": "",
                "control": control,
                "metrics": {"packet": packet_metrics},
                "query_class": query_class,
                "routing": {
                    "confidence": route.confidence,
                    "margin": route.margin,
                    "reasons": list(route.reasons),
                    "version": route.router_version,
                },
                "retrieval": result.metadata,
                "message": message,
            }
            if response_metadata:
                payload.update(response_metadata)
            return json.dumps(payload)
        return message

    graph_packet = compiled.packet
    _raise_if_compilation_invalid(compiled)
    answerability = result.metadata.get("answerability", {})
    partial_message = (
        f"GraphGraph partial result: {answerability.get('reason', 'receipt is incomplete')}."
        if answerability.get("abstained")
        else ""
    )

    if json_anchors and (show_anchors or include_snippets):
        limit = anchor_limit if anchor_limit is not None else len(result.starts)
        payload = {
            "actionable": _actionable_receipt(
                result,
                response_metadata,
                query_class=query_class,
                graph=graph,
            ),
            "anchors": [
                {
                    "id": match.node.id,
                    "label": match.node.label,
                    "kind": match.node.kind,
                    "path": match.node.path,
                    "line": match.node.line,
                    "score": match.score,
                    "reasons": list(match.reasons),
                }
                for match in result.matches[:limit]
            ],
            "query_class": query_class,
            "routing": {
                "confidence": route.confidence,
                "margin": route.margin,
                "reasons": list(route.reasons),
                "version": route.router_version,
            },
            "retrieval": result.metadata,
            "packet": graph_packet,
            # Top-level because consumers dispatch on it. The format is chosen
            # adaptively -- by query class, and then by whichever encoding
            # renders the selected subgraph in fewest tokens -- so the same
            # question can legitimately come back as `gg` or `svo` depending on
            # its answer's size. That is a deliberate token win, but it broke a
            # reader that had inferred one format from three sample runs and
            # then silently parsed nothing on the fourth. `gg`/`svo` announce
            # themselves with a `#` marker line; `semantic_arrow` and
            # `doc_summary` do not, so sniffing the text cannot be correct.
            # Pin `--packet` if a stable encoding matters more than the tokens.
            "packet_format": compiled.receipt.packet,
            "control": control,
            "metrics": {"packet": packet_metrics},
        }
        if partial_message:
            payload["message"] = partial_message
        if include_snippets:
            from .snippets import render_source_snippets

            snippet_ids = list(result.starts[: max(0, snippet_limit)])
            payload["source_snippets"] = (
                render_source_snippets(
                    starts=snippet_ids,
                    graph_path=resolved_graph_path,
                    context_lines=snippet_context_lines,
                    max_lines=snippet_max_lines,
                    graph=graph,
                )
                if snippet_ids
                else ""
            )
        if response_metadata:
            payload.update(response_metadata)
        workflow = payload.setdefault("workflow", {})
        if isinstance(workflow, dict):
            workflow["cache"] = {
                "state": "miss",
                "namespace": cache_namespace,
            }
        response = json.dumps(payload, indent=2)
        json_fallback = json.dumps(
            {
                "packet": graph_packet,
                "packet_format": compiled.receipt.packet,
                "workflow": {},
            },
            separators=(",", ":"),
        )
    elif show_anchors:
        limit = anchor_limit if anchor_limit is not None else len(result.starts)
        out_lines = [
            *([partial_message] if partial_message else []),
            f"ROUTE: {query_class} confidence={route.confidence:.3f} margin={route.margin:.3f} "
            f"reason={'; '.join(route.reasons)}",
            f"PLAN: {json.dumps(result.metadata, separators=(',', ':'), ensure_ascii=False)}",
            "ANCHORS:",
        ]
        for match in result.matches[:limit]:
            node = match.node
            location = f"{node.path}:{node.line}" if node.line else node.path
            out_lines.append(f"- {node.id} {node.label} [{node.kind}] {location} score={match.score:g}")
        out_lines.extend(["\nGRAPH:", graph_packet])
        response = "\n".join(out_lines)
        json_fallback = None
    else:
        response = f"{partial_message}\n\n{graph_packet}" if partial_message else graph_packet
        json_fallback = None

    response = clamp_response_to_packet_surface(response, graph_packet, fallback=json_fallback)
    if not include_snippets:
        cache.set(
            resolved_graph_path,
            cache_key,
            response,
            node_ids=result.nodes,
            paths=packet_dependency_paths(graph, result.nodes),
        )
    return response


def _cache_metadata_signature(
    response_metadata: dict[str, object] | None,
) -> object:
    """Keep only response state that can change answer/control correctness."""

    def stable(value: object) -> object:
        if isinstance(value, dict):
            return tuple(
                (key, stable(item))
                for key, item in sorted(value.items())
                if key not in {"milliseconds", "query_milliseconds", "total_milliseconds", "cache"}
            )
        if isinstance(value, (list, tuple)):
            return tuple(stable(item) for item in value)
        return value

    if not response_metadata:
        return ()
    workflow = response_metadata.get("workflow", {})
    if not isinstance(workflow, dict):
        return ()
    graph_validation = workflow.get("graph_validation", {})
    validation_ok = graph_validation.get("ok") if isinstance(graph_validation, dict) else None
    # Refresh/build telemetry describes how the already-hash-validated graph
    # was obtained. It must not split cache keys (`built=True` on call one,
    # `built=False` on call two). Freshness and graph validity can alter the
    # control gates, so they remain part of the key.
    return stable(
        {
            "freshness": workflow.get("freshness", {}),
            "graph_validation_ok": validation_ok,
        }
    )


def _with_cache_receipt(
    cached_response: str,
    *,
    state: str,
    namespace: str,
    response_metadata: dict[str, object] | None,
    json_response: bool,
) -> str:
    if not json_response:
        return cached_response
    try:
        payload = json.loads(cached_response)
    except json.JSONDecodeError:
        return cached_response
    if response_metadata:
        payload.update(response_metadata)
    workflow = payload.setdefault("workflow", {})
    if isinstance(workflow, dict):
        workflow["cache"] = {
            "state": state,
            "namespace": namespace,
        }
    return json.dumps(payload, indent=2)


def _compiled_control_receipt(
    compiled: object,
    *,
    requested_query_class: str,
    response_metadata: dict[str, object] | None,
) -> tuple[str, dict[str, int]]:
    """Compile rich receipts into one fixed-order LLM decision instruction."""
    result = compiled.retrieval
    answerability = result.metadata.get("answerability", {})
    state = str(answerability.get("status", "unknown"))
    packet = str(compiled.packet)
    packet_tokens = estimate_tokens(packet)
    packet_metrics = {
        "proxy_tokens": packet_tokens,
        "characters": len(packet),
    }
    freshness: bool | None = None
    if response_metadata:
        workflow = response_metadata.get("workflow", {})
        if isinstance(workflow, dict):
            freshness_receipt = workflow.get("freshness", {})
            if isinstance(freshness_receipt, dict):
                value = freshness_receipt.get(
                    "requested_scope_fresh",
                    freshness_receipt.get("fresh"),
                )
                if isinstance(value, bool):
                    freshness = value
    automatic_route = (requested_query_class or "auto").strip().lower() == "auto"
    route_ok = not automatic_route or float(compiled.route.confidence) >= AUTOMATIC_ROUTE_MIN_CONFIDENCE
    truncation = result.metadata.get("truncation", {})
    truncated = bool(truncation.get("truncated")) if isinstance(truncation, dict) else False
    # `semantic_validation` checks packet-receipt *consistency*, so with no
    # semantic retrieval (semantic_seeds == 0, no index) it passes vacuously.
    # Reporting that as `semantic:+` reads as "semantic support active" when the
    # answer was pure lexical -- a silent degradation. Show `?` (not applicable)
    # when semantic did not contribute; keep `-` (repair) for a real failure.
    sources = result.metadata.get("sources", {})
    semantic_seeds = int(sources.get("semantic_seeds", 0) or 0) if isinstance(sources, dict) else 0
    gates: dict[str, bool | None] = {
        "fresh": freshness,
        "route": route_ok,
        "anchor": bool(result.starts),
        "evidence": state == "answerable" and not truncated,
        "semantic": (False if compiled.receipt.semantic_validation == "fail" else True if semantic_seeds > 0 else None),
        "packet": (compiled.receipt.structural_validation == "pass" if packet else None),
    }
    receipt = ControlReceipt(
        operation=str(compiled.route.query_class),
        state=state,
        next_action=choose_next_action(state, gates),
        anchor=str(result.metadata.get("anchor_strategy", "none" if not result.starts else "ranked")),
        hops=int(compiled.plan.hops),
        direction=str(compiled.plan.direction),
        node_budget=compiled.plan.node_budget,
        nodes=len(result.nodes),
        edges=len(result.edges),
        packet=str(compiled.receipt.packet) if packet else "",
        packet_tokens=packet_tokens,
        gates=tuple((name, gates[name]) for name in GATE_ORDER),
    )
    return render_control_ir(receipt), packet_metrics


def _actionable_receipt(
    result: object,
    response_metadata: dict[str, object] | None,
    *,
    query_class: str,
    graph: Graph | None = None,
) -> dict[str, object]:
    metadata = getattr(result, "metadata", {})
    answerability = metadata.get("answerability", {})
    affected = metadata.get("affected_tests", {})
    facet_coverage = metadata.get("facet_coverage", {})
    structural_facet_coverage = metadata.get("structural_facet_coverage", {})
    freshness_ref: str | None = None
    if response_metadata:
        workflow = response_metadata.get("workflow", {})
        if isinstance(workflow, dict) and "freshness" in workflow:
            freshness_ref = "$.workflow.freshness"
        elif "freshness" in response_metadata:
            freshness_ref = "$.freshness"

    def compact_tests(role: str) -> list[dict[str, object]]:
        if not isinstance(affected, dict):
            return []
        return [
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "path": item.get("path"),
                "evidence_mode": item.get("evidence_mode"),
                "covers": [
                    covered.get("id")
                    for covered in item.get("covers", ())
                    if isinstance(covered, dict) and covered.get("id")
                ],
            }
            for item in affected.get(role, ())
            if isinstance(item, dict)
        ]

    def compact_runnable_units(role: str) -> list[dict[str, object]]:
        if not isinstance(affected, dict):
            return []
        return [
            {
                "id": item.get("id"),
                "path": item.get("path"),
                "role": item.get("role"),
                "selection_unit": item.get("selection_unit"),
                "command_index": item.get("command_index"),
                "member_count": item.get("member_count", 1),
                "evidence_mode": item.get("evidence_mode"),
            }
            for item in affected.get(role, ())
            if isinstance(item, dict)
        ]

    start_ids = set(getattr(result, "starts", ()))
    priority_ids: list[str] = []
    if query_class == "reverse_lookup":
        priority_ids.extend(
            edge.source
            for edge in getattr(result, "edges", ())
            if edge.target in start_ids
            and edge.source not in start_ids
            and edge.type
            in {
                "calls",
                "references",
                "imports_from",
                "tests",
                "implements",
            }
        )
    coverage_receipts = (
        (structural_facet_coverage, facet_coverage)
        if query_class not in {"doc_summary", "negative_query"}
        else (facet_coverage,)
    )
    for coverage in coverage_receipts:
        if not isinstance(coverage, dict):
            continue
        for facet in coverage.get("fulfilled", ()):
            if not isinstance(facet, dict):
                continue
            priority_ids.extend(str(node_id) for node_id in facet.get("evidence", ()) if node_id)
    document_status = metadata.get("document_status_evidence", {})
    if isinstance(document_status, dict):
        priority_ids[0:0] = [str(node_id) for node_id in document_status.get("evidence", ()) if node_id]
    priority_ids = list(dict.fromkeys(priority_ids))
    if query_class not in {"doc_summary", "negative_query"}:
        priority_ids.sort(key=lambda node_id: node_id in start_ids)
    priority_rank = {node_id: rank for rank, node_id in enumerate(priority_ids)}
    ranked_matches = sorted(
        enumerate(getattr(result, "matches", ())),
        key=lambda item: (
            0 if item[1].node.id in priority_rank else 1,
            priority_rank.get(item[1].node.id, item[0]),
            item[0],
        ),
    )
    evidence_nodes: list[Node] = []
    seen_evidence: set[str] = set()
    if graph is not None:
        for node_id in priority_ids:
            node = graph.nodes.get(node_id)
            if node is not None and node.id not in seen_evidence:
                seen_evidence.add(node.id)
                evidence_nodes.append(node)
    for _index, match in ranked_matches:
        if match.node.id not in seen_evidence:
            seen_evidence.add(match.node.id)
            evidence_nodes.append(match.node)
    evidence_points = [
        {
            "id": node.id,
            "label": node.label,
            "path": node.path,
            "line": node.line,
            "kind": node.kind,
        }
        for node in evidence_nodes[:5]
    ]
    change_points = (
        []
        if query_class in {"doc_summary", "negative_query"}
        else [point for point in evidence_points if str(point["kind"]) not in _DOCUMENT_EVIDENCE_KINDS]
    )
    evidence_role = (
        "document_status"
        if document_status
        else "documentation"
        if query_class == "doc_summary"
        else "absence_check"
        if query_class == "negative_query"
        else "structural_context"
    )

    receipt: dict[str, object] = {
        "status": answerability.get("status", "unknown"),
        "evidence_role": evidence_role,
        "evidence_points": evidence_points,
        "change_points": change_points,
        "implementation": {
            "authorized": False,
            "reason": "retrieval evidence does not authorize source changes",
            "documented_gap_policy": "a documented absence is evidence, not a work order",
        },
        "document_status": document_status,
        "missing_evidence": list(facet_coverage.get("unfulfilled", ())) if isinstance(facet_coverage, dict) else [],
        "tests": {
            "direct": compact_tests("direct"),
            "transitive": compact_tests("transitive"),
            "runnable_units": compact_runnable_units("runnable_units"),
            "candidate_units": compact_runnable_units("candidate_units"),
            "commands_by_role": affected.get("commands_by_role", {}) if isinstance(affected, dict) else {},
            "commands": list(affected.get("commands", ())) if isinstance(affected, dict) else [],
        },
        "freshness_ref": freshness_ref,
        "semantic_validation": metadata.get("semantic_validation", {}),
    }
    # The subsystem map is the actionable answer to a broad architecture query,
    # and it is far terser than the packet it summarizes. Surfacing it here --
    # not only in the verbose `retrieval` metadata -- keeps it in the compact
    # JSON payload, which drops everything except `actionable`.
    subsystem_map = metadata.get("subsystem_map")
    if subsystem_map:
        receipt["subsystem_map"] = subsystem_map
    return receipt


def _raise_if_compilation_invalid(compiled: CompileOutcome) -> None:
    if compiled.receipt.structural_validation == "fail":
        details = "; ".join(compiled.receipt.warnings) or "unknown packet validation error"
        raise ValueError("generated graph packet failed validation: " + details)




__all__ = ["CompilerDriver", "DriverRequest"]
