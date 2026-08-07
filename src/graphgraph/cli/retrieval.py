"""CLI orchestration for GraphGraph retrieval and packet rendering."""

from __future__ import annotations

import argparse
import json
import sys
import time
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
from ..retrieval import (
    apply_shape_budget,
    encode_relation_micro,
    packet_priority,
    query_relations,
    query_saved_relations,
)
from ..runtime.cache import (
    TopologicalKVCache,
    cache_file_for_graph,
    compute_cache_key,
    runtime_cache_fingerprint,
)
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
from ..services.lifecycle import refresh_saved_graph
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
    cache = TopologicalKVCache(cache_file_for_graph(graph_path))
    cache_key = compute_cache_key(
        starts,
        args.query_class,
        plan.hops,
        # A packet is derived from GraphGraph's own rendering code as well as
        # from the graph, and the entry's graph hash cannot see a renderer
        # change. Without the runtime fingerprint `render` keeps replaying a
        # packet built by superseded code for as long as the graph file stays
        # byte-identical.
        f"{plan.packet}|render|{plan.planner_version}|{plan.node_budget}|{plan.direction}|"
        f"runtime={runtime_cache_fingerprint()}",
    )
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    packet = render_packet(
        graph,
        nodes,
        edges,
        plan.packet,
        priority=packet_priority(tuple(starts), nodes, edges, args.query_class, graph=graph),
    )
    cache.set(
        graph_path,
        cache_key,
        packet,
        node_ids=nodes,
        paths=[graph.nodes[node_id].path for node_id in nodes if node_id in graph.nodes and graph.nodes[node_id].path],
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
            representation=args.representation,
            representation_budget=args.representation_budget,
        )
    )


def cmd_query(args: argparse.Namespace) -> None:
    from ..planning.query_compiler import QueryOperator, compile_query
    from ..services.query import execute_query

    directory = Path(getattr(args, "directory", None) or ".")
    explicit_graph = Path(args.graph) if args.graph else None
    operator_mode = getattr(args, "operator", "auto")
    # ``query --query-class ...`` predates the universal facade and promises
    # the full context envelope. Preserve that contract while allowing plain
    # ``query <anything>`` to choose a cheaper lossless expert operator.
    if operator_mode == "auto" and args.query_class != "auto":
        operator_mode = "context"
    compiled = compile_query(
        args.query,
        mode=operator_mode,
        result_mode=getattr(args, "result_mode", "select"),
        target=getattr(args, "target", ""),
        direction=getattr(args, "direction", "") or "",
        predicate=getattr(args, "predicate", ""),
    )
    try:
        graph_path = explicit_graph or find_graph_path(directory)
    except (FileNotFoundError, RuntimeError):
        response = execute_query(
            args.query,
            directory=directory,
            graph_path=explicit_graph,
            mode=operator_mode,
            result_mode=getattr(args, "result_mode", "select"),
            target=getattr(args, "target", ""),
            direction=getattr(args, "direction", "") or "",
            predicate=getattr(args, "predicate", ""),
        )
        emit_json(response, getattr(args, "pretty", False))
        return
    if compiled.operator is not QueryOperator.CONTEXT or getattr(args, "sync", "none") == "git":
        response = execute_query(
            args.query,
            directory=directory,
            graph_path=graph_path,
            mode=operator_mode,
            result_mode=getattr(args, "result_mode", "select"),
            target=getattr(args, "target", ""),
            direction=getattr(args, "direction", "") or "",
            predicate=getattr(args, "predicate", ""),
            sync=getattr(args, "sync", "none"),
            limit=max(0, getattr(args, "limit", 20)),
            query_class=args.query_class,
            packet=args.packet,
            hops=args.hops,
            anchor_limit=args.anchor_limit,
            max_nodes=args.max_nodes,
            scopes=tuple(args.scope),
            scope_mode=args.scope_mode,
            source_mode=args.source_mode,
        )
        if getattr(args, "json", False):
            emit_json(response, getattr(args, "pretty", False))
        else:
            result = response.get("result")
            if response.get("operator") == "context" and isinstance(result, dict):
                print(result.get("packet") or result.get("message") or "")
            else:
                print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        if getattr(args, "show_stats", False):
            receipt = response.get("receipt", {})
            elapsed = receipt.get("milliseconds") if isinstance(receipt, dict) else None
            print(
                f"GraphGraph query operator={response.get('operator')} "
                f"cost={compiled.cost_class} ms={elapsed}",
                file=sys.stderr,
            )
        return
    freshness = scope_freshness(
        inspect_saved_graph_freshness(
            directory=source_root_for_saved_graph(graph_path),
            output_path=graph_path,
        ),
        tuple(args.scope),
    )
    if not freshness["fresh"]:
        incompatible = not freshness.get("extractor_compatible", True)
        changed_count = freshness["changed_count"]
        deleted_count = freshness["deleted_count"]
        if incompatible and not changed_count and not deleted_count:
            # Staleness is purely a scanner-version mismatch (the graph was built
            # by a different extractor), not file edits. Saying "stale for 0
            # changed and 0 deleted" reads as a false alarm, so name the real
            # reason instead.
            message = (
                "GraphGraph WARNING: this graph was built by a different scanner "
                "version, so its extraction may be out of date (no files changed); "
                "rebuild with `scan --no-incremental`."
            )
        else:
            compatibility = " extractor cache is incompatible;" if incompatible else ""
            remedy = "`scan --no-incremental`" if incompatible else "`context --sync git`"
            message = (
                f"GraphGraph WARNING:{compatibility} graph is stale for "
                f"{changed_count} changed and {deleted_count} deleted path(s); use {remedy}."
            )
        print(message, file=sys.stderr)
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
        representation=args.representation,
        representation_budget=args.representation_budget,
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


def cmd_relations(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    started = time.perf_counter()
    sync_git = getattr(args, "sync", "none") == "git"
    refresh_summary = None
    freshness = "unchecked"
    if sync_git:
        source_root = source_root_for_saved_graph(graph_path)
        status = refresh_saved_graph(
            directory=source_root,
            output_path=graph_path,
            sync_git=True,
        )
        graph = status.graph
        checked = inspect_saved_graph_freshness(
            directory=source_root,
            output_path=graph_path,
        )
        freshness = "fresh" if checked["fresh"] else "incompatible" if not checked["extractor_compatible"] else "stale"
        refresh_summary = {
            "updated": len(status.changed_paths),
            "removed": len(status.deleted_paths),
            "write": status.built,
            "fresh": freshness == "fresh",
        }
    else:
        graph = None
    query = query_relations if graph is not None else query_saved_relations
    result = query(
        graph if graph is not None else graph_path,
        args.target,
        direction=args.direction,
        limit=args.limit,
        include_tests=args.include_tests,
        include_external=args.include_external,
        details=args.detailed,
        freshness=freshness,
    )
    if refresh_summary is not None and result.get("status") == "ok":
        result["refresh"] = refresh_summary
    if result.get("status") == "ok":
        result["milliseconds"] = round((time.perf_counter() - started) * 1000, 3)
    payload = result if args.detailed else encode_relation_micro(result)
    if result.get("status") == "ok" and isinstance(payload.get("r"), dict):
        payload["r"]["ms"] = result["milliseconds"]
    emit_json(payload, args.pretty)


def cmd_context(args: argparse.Namespace) -> None:
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = tuple(skip_dirs + [item for item in exclude_dirs if item not in skip_dirs])
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
        representation=args.representation,
        representation_budget=args.representation_budget,
    )
    if args.show_stats:
        shape = graph_shape(status.graph)
        action = "refreshed" if status.changed_paths or status.deleted_paths else "built" if status.built else "loaded"
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
                f"GraphGraph sync changed={len(status.changed_paths)} deleted={len(status.deleted_paths)}",
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
