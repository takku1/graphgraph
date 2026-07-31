"""One-step native graph refresh, retrieval, and validation orchestration."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..packets.validation import validate_any
from ..surface import DEFAULT_SCAN_MAX_NODES
from .context import render_query_context
from .freshness import (
    inspect_saved_graph_freshness,
    refresh_receipt,
    scope_freshness,
    source_root_for_saved_graph,
)
from .lifecycle import GraphBuildStatus, ensure_native_graph, refresh_saved_graph


def render_native_context(
    *,
    query: str,
    query_class: str = "auto",
    directory: Path = Path("."),
    graph_path: Path | None = None,
    rebuild: bool = False,
    max_nodes: int | None = None,
    scan_max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    packet: str | None = None,
    anchor_limit: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
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
) -> tuple[str, GraphBuildStatus]:
    started = time.monotonic()
    if graph_path is not None and directory == Path("."):
        directory = source_root_for_saved_graph(graph_path)
    directory = directory.resolve()
    output_path = graph_path or directory / ".graphgraph" / "graph.gg"
    status = ensure_native_graph(
        directory=directory,
        output_path=output_path,
        rebuild=rebuild,
        max_nodes=scan_max_nodes,
        skip_dirs=skip_dirs,
        include_dirs=include_dirs,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        generic_mentions=generic_mentions,
        incremental=incremental,
        discover_existing=graph_path is None,
    )
    refresh_started = time.monotonic()
    if changed_paths or deleted_paths or sync_git:
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
    repository_freshness = (
        {
            "fresh": True,
            "changed_count": 0,
            "deleted_count": 0,
            "changed_paths": [],
            "deleted_paths": [],
        }
        if sync_git
        else inspect_saved_graph_freshness(
            directory=directory,
            output_path=status.path,
        )
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
    packet_text = render_query_context(
        query=query,
        query_class=query_class,
        graph_path=status.path,
        packet=packet,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        scopes=scopes,
        scope_mode=scope_mode,
        show_anchors=show_anchors or json_output,
        json_anchors=json_output,
        cache_namespace="cli_context",
        graph=status.graph if status.built else None,
        response_metadata=workflow_metadata,
        source_mode=source_mode,
        memory_scopes=memory_scopes,
        anchor_paths=requested_anchor_paths,
        representation=representation,
        representation_budget=representation_budget,
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


__all__ = ["render_native_context"]
