"""CLI orchestration for GraphGraph retrieval and packet rendering."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..io import (
    find_graph_path,
    find_policies_path,
    load_any,
    project_root_for_graph,
)
from ..packets import render_packet
from ..packets.validation import validate_any
from ..planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph
from ..retrieval import apply_shape_budget
from ..runtime.cache import TopologicalKVCache, compute_cache_key
from ..services import (
    FullGraphTooLargeError,
    render_final_packet,
    render_full_graph,
    render_query_context,
    render_source_snippets,
    render_stable_skeleton,
)
from ..services.context import resolve_start_nodes
from ..services.freshness import (
    inspect_saved_graph_freshness,
    scope_freshness,
    source_root_for_saved_graph,
)
from ..services.native_context import render_native_context
from ..services.project_status import graph_shape
from .output import emit_json


def cmd_render(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    starts = resolve_start_nodes(graph, args.starts)
    plan = plan_context(args.query_class, max_nodes=args.max_nodes)
    if args.max_nodes is None:
        plan = apply_shape_budget(graph, plan, getattr(args, "query", ""))
    nodes, edges = graph.expand(
        starts,
        hops=plan.hops,
        max_nodes=plan.node_budget,
        direction=plan.direction,
    )
    plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, nodes, edges))
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        args.starts,
        args.query_class,
        plan.hops,
        f"{plan.packet}|render|{plan.planner_version}|{plan.node_budget}|{plan.direction}",
    )
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    packet = render_packet(graph, nodes, edges, plan.packet)
    cache.set(
        graph_path,
        cache_key,
        packet,
        node_ids=nodes,
        paths=[
            graph.nodes[node_id].path
            for node_id in nodes
            if node_id in graph.nodes and graph.nodes[node_id].path
        ],
    )
    print(packet)


def cmd_final(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    policies_path = Path(args.policies) if args.policies else find_policies_path()

    if getattr(args, "stable_skeleton", False):
        max_nodes = getattr(args, "max_nodes", 100) or 100
        print(
            render_stable_skeleton(
                graph_path,
                max_nodes=max_nodes,
                packet=getattr(args, "packet", "gg") or "gg",
            )
        )
        return

    if getattr(args, "full_graph", False):
        max_tokens = getattr(args, "full_graph_max_tokens", 20_000)
        try:
            print(
                render_full_graph(
                    graph_path,
                    packet=getattr(args, "packet", "gg") or "gg",
                    max_tokens=max_tokens if max_tokens else None,
                )
            )
        except FullGraphTooLargeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.starts:
        print(
            "Error: --starts is required unless --stable-skeleton or --full-graph is specified.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.query_class:
        print(
            "Error: --query-class is required unless --stable-skeleton or --full-graph is specified.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        render_final_packet(
            starts=args.starts,
            query_class=args.query_class,
            query_text=args.query,
            graph_path=graph_path,
            policies_path=policies_path,
            paths=tuple(args.path),
            tags=tuple(args.tag),
            max_nodes=args.max_nodes,
            cache_namespace="cli_final",
            packet=getattr(args, "packet", None),
        )
    )


def cmd_query(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    freshness = scope_freshness(
        inspect_saved_graph_freshness(
            directory=source_root_for_saved_graph(graph_path),
            output_path=graph_path,
        ),
        tuple(args.scope),
    )
    if not freshness["fresh"]:
        incompatible = not freshness.get("extractor_compatible", True)
        compatibility = " extractor cache is incompatible;" if incompatible else ""
        remedy = (
            "`scan --no-incremental`"
            if incompatible
            else "`context --sync git`"
        )
        print(
            f"GraphGraph WARNING:{compatibility} graph is stale for "
            f"{freshness['changed_count']} changed and "
            f"{freshness['deleted_count']} deleted path(s); use {remedy}.",
            file=sys.stderr,
        )
    show_stats = getattr(args, "show_stats", False)
    as_json = getattr(args, "json", False)
    output = render_query_context(
        query=args.query,
        query_class=args.query_class,
        graph_path=graph_path,
        packet=args.packet,
        hops=args.hops,
        anchor_limit=args.anchor_limit,
        max_nodes=args.max_nodes,
        scopes=tuple(args.scope),
        scope_mode=args.scope_mode,
        show_anchors=args.show_anchors or show_stats or as_json,
        json_anchors=show_stats or as_json,
        cache_namespace="cli_query",
        source_mode=args.source_mode,
        memory_scopes=tuple(args.memory_scope) or ("project", "session"),
        response_metadata={"workflow": {"freshness": freshness}},
    )
    if show_stats or as_json:
        payload = json.loads(output)
        if not as_json:
            output = str(payload.get("packet", ""))
        shape = graph_shape(load_any(graph_path))
        print(
            (
                f"GraphGraph query: {graph_path} "
                f"nodes={shape['nodes']} edges={shape['edges']} "
                f"source={shape['source_nodes']} docs={shape['doc_nodes']} "
                f"other={shape['other_nodes']}"
            ),
            file=sys.stderr,
        )
        control = str(payload.get("control", ""))
        if control:
            print(f"GraphGraph control: {control}", file=sys.stderr)
    if as_json:
        emit_json(payload, getattr(args, "pretty", False))
        return
    print(output)


def cmd_snippets(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    print(
        render_source_snippets(
            starts=list(args.starts),
            graph_path=graph_path,
            context_lines=args.context_lines,
            max_lines=args.max_lines,
        )
    )


def cmd_context(args: argparse.Namespace) -> None:
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = tuple(
        skip_dirs + [item for item in exclude_dirs if item not in skip_dirs]
    )
    include_dirs: list[str] = list(getattr(args, "include", None) or [])
    graph_path = Path(args.graph) if args.graph else None
    directory = (
        Path(args.directory)
        if args.directory
        else project_root_for_graph(graph_path)
        if graph_path is not None
        else Path(".")
    )
    output, status = render_native_context(
        query=args.query,
        query_class=args.query_class,
        directory=directory,
        graph_path=graph_path,
        rebuild=args.rebuild,
        max_nodes=args.max_nodes,
        scan_max_nodes=args.scan_max_nodes,
        packet=args.packet,
        anchor_limit=args.anchor_limit,
        scopes=tuple(args.scope),
        scope_mode=args.scope_mode,
        skip_dirs=all_skip,
        include_dirs=tuple(include_dirs),
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        history=args.history,
        generic_mentions=args.generic_mentions,
        incremental=args.incremental,
        show_anchors=args.show_anchors,
        changed_paths=tuple(args.changed),
        deleted_paths=tuple(args.deleted),
        sync_git=args.sync == "git",
        json_output=args.json,
        json_details=args.details,
        source_mode=args.source_mode,
        memory_scopes=tuple(args.memory_scope) or ("project", "session"),
    )
    if args.show_stats:
        shape = graph_shape(status.graph)
        action = (
            "refreshed"
            if status.changed_paths or status.deleted_paths
            else "built"
            if status.built
            else "loaded"
        )
        print(
            (
                f"GraphGraph context {action}: {status.path} "
                f"nodes={shape['nodes']} edges={shape['edges']} "
                f"source={shape['source_nodes']} docs={shape['doc_nodes']} "
                f"other={shape['other_nodes']}"
            ),
            file=sys.stderr,
        )
        if status.changed_paths or status.deleted_paths:
            print(
                f"GraphGraph sync changed={len(status.changed_paths)} "
                f"deleted={len(status.deleted_paths)}",
                file=sys.stderr,
            )
    if args.validate and not args.json:
        validation = validate_any(output)
        print(
            f"Packet structural validation: {'PASS' if validation.ok else 'FAIL'} "
            f"{validation.format} nodes={validation.node_count} edges={validation.edge_count}",
            file=sys.stderr,
        )
    print(output)
