from __future__ import annotations

import json
from pathlib import Path

from ..cache import TopologicalKVCache, compute_cache_key
from ..core import Graph, Query
from ..io import find_graph_path, find_lessons_path, find_policies_path, load_any, load_policies
from ..packets import render_packet
from ..planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph
from ..policies import render_policy_packet, select_policies
from ..retrieval import apply_shape_budget, expand_context, retrieve_context
from ..validate import validate_packet


def render_stable_skeleton(graph_path: Path | None = None, max_nodes: int = 100, packet: str = "gg_max") -> str:
    resolved_graph_path = graph_path or find_graph_path()
    graph = load_any(resolved_graph_path)
    pr = graph.pagerank()
    top_nodes = sorted(pr, key=pr.get, reverse=True)[:max_nodes]
    top_set = set(top_nodes)
    skeleton_edges = [edge for edge in graph.edges if edge.active and edge.source in top_set and edge.target in top_set]
    return render_packet(graph, top_set, skeleton_edges, packet)


def render_final_packet(
    *,
    starts: list[str],
    query_class: str,
    query_text: str = "",
    graph_path: Path | None = None,
    policies_path: Path | None = None,
    paths: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    max_nodes: int | None = None,
    cache_namespace: str = "final",
    packet: str | None = None,
) -> str:
    resolved_graph_path = graph_path or find_graph_path()
    resolved_policies_path = policies_path if policies_path is not None else find_policies_path()

    graph = load_any(resolved_graph_path)
    plan = plan_context(query_class, query_text, max_nodes=max_nodes, packet=packet)
    if max_nodes is None:
        plan = apply_shape_budget(graph, plan, query_text)
    policies = load_policies(resolved_policies_path) if resolved_policies_path else []
    query = Query(text=query_text, query_class=query_class, paths=paths, tags=tags)

    resolved_starts = resolve_start_nodes(graph, starts)
    if not resolved_starts:
        # Build a helpful diagnostic: search the graph for candidates
        from .._findnodes import suggest_node_ids
        suggestions = suggest_node_ids(graph, starts, limit=6)
        hint = ""
        if suggestions:
            hint = "  Closest matches in graph:\n" + "\n".join(
                f"    {m.node.id}  ({m.node.label}, {m.node.kind}, {m.node.path})"
                for m in suggestions
            )
        raise ValueError(
            f"No graph nodes matched the requested starts: {starts!r}\n"
            f"{hint}\n"
            "  Options:\n"
            "   1. Use 'search_nodes' tool to find the right node IDs first.\n"
            "   2. Use 'query_context' tool with a natural-language query — no node IDs needed.\n"
            "   3. Re-scan if the file was recently added: graphgraph scan --depth symbols --docs"
        )
    nodes, edges = expand_context(graph, tuple(resolved_starts), plan)

    plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, nodes, edges))

    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        resolved_starts,
        query_class,
        plan.hops,
        (
            f"{plan.packet}|{cache_namespace}|{plan.planner_version}|{query_text}|"
            f"{paths}|{tags}|{plan.node_budget}|{plan.direction}|{tuple(starts)}"
        ),
    )
    cached_packet = cache.get(resolved_graph_path, cache_key)
    if cached_packet:
        return cached_packet

    # 5. Read lessons/reflections if available
    lessons_path = find_lessons_path()
    lessons_packet = ""
    if lessons_path:
        try:
            lessons_packet = lessons_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    selected = select_policies(policies, query)
    policy_packet = render_policy_packet(selected, compact=True)
    graph_packet = render_packet(graph, nodes, edges, plan.packet)
    _raise_if_invalid(graph_packet)

    out_lines: list[str] = []
    if plan.packet and "gg_lex" in plan.packet:
        out_lines.append(
            "NOTE: You are receiving a structurally pruned codebase context subgraph indexed using lexical namespace tags (gg_lex).\n"
            "The 8-character abbreviations (e.g. authserv) represent unique file/symbol nodes. Edges list call dependencies.\n"
            "Treat this as your ground-truth architectural map to answer coding queries."
        )
    if lessons_packet:
        out_lines.extend(["LESSONS / PAST SESSION REFLECTIONS:", lessons_packet, ""])
    if policy_packet:
        out_lines.extend(["CONSTRAINTS:", policy_packet, "\nGRAPH:"])
    else:
        out_lines.append("GRAPH:")
    out_lines.append(graph_packet)
    final_output = "\n".join(out_lines)
    cache.set(
        resolved_graph_path,
        cache_key,
        final_output,
        node_ids=nodes,
        paths=_node_paths(graph, nodes),
    )
    return final_output


def resolve_start_nodes(graph: Graph, starts: list[str]) -> list[str]:
    """Resolve user-facing start handles to graph node IDs.

    ``Graph.expand()`` intentionally accepts only node IDs.  CLI/MCP callers
    often know labels or paths, so this helper accepts:

    1. Exact node IDs
    2. Exact normalised path matches
    3. Exact label matches
    4. Case-folded path matches
    5. Case-folded label matches
    6. Case-folded basename matches
    7. **Partial path suffix matches** – e.g. ``"featherwaight/cli.py"`` or
       ``"src/featherwaight"`` will match nodes whose path *ends with* that
       suffix (case-folded, forward-slash normalised).

    Ambiguous labels/paths resolve to all matching active nodes in stable
    graph order.
    """
    resolved: list[str] = []
    seen: set[str] = set()
    by_path = {
        node.path.replace("\\", "/").strip("/"): node_id
        for node_id, node in graph.nodes.items()
        if node.path and node.active
    }
    by_label: dict[str, list[str]] = {}
    by_folded_path = {_start_key(path): node_id for path, node_id in by_path.items()}
    by_folded_basename: dict[str, list[str]] = {}
    by_folded_label: dict[str, list[str]] = {}

    for node_id, node in graph.nodes.items():
        if not node.active:
            continue
        by_label.setdefault(node.label, []).append(node_id)
        by_folded_label.setdefault(_start_key(node.label), []).append(node_id)
        if node.path:
            basename = _start_key(node.path.replace("\\", "/").rsplit("/", 1)[-1])
            by_folded_basename.setdefault(basename, []).append(node_id)

    def add(node_id: str) -> None:
        if node_id not in seen:
            seen.add(node_id)
            resolved.append(node_id)

    for raw in starts:
        start = raw.strip()
        if not start:
            continue
        norm_path = start.replace("\\", "/").strip("/")
        folded = _start_key(norm_path)
        if start in graph.nodes and graph.nodes[start].active:
            add(start)
            continue
        if norm_path in by_path:
            add(by_path[norm_path])
            continue
        if start in by_label:
            for node_id in by_label[start]:
                add(node_id)
            continue
        if folded in by_folded_path:
            add(by_folded_path[folded])
            continue
        if folded in by_folded_label:
            for node_id in by_folded_label[folded]:
                add(node_id)
            continue
        if folded in by_folded_basename:
            for node_id in by_folded_basename[folded]:
                add(node_id)
            continue
        # Fallback: partial path-suffix match (e.g. "featherwaight/cli.py" or "src/featherwaight")
        for path, node_id in by_folded_path.items():
            if path.endswith(folded) or folded.endswith(path.rsplit("/", 1)[-1]):
                add(node_id)

    return resolved


def _start_key(value: str) -> str:
    key = value.strip().casefold()
    if key.endswith("()"):
        key = key[:-2]
    return key


def render_query_context(
    *,
    query: str,
    query_class: str = "blast_radius",
    graph_path: Path | None = None,
    packet: str | None = None,
    hops: int | None = None,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
    show_anchors: bool = False,
    cache_namespace: str = "query",
    json_anchors: bool = False,
    web_search: bool = False,
) -> str:
    resolved_graph_path = graph_path or find_graph_path()
    graph = load_any(resolved_graph_path)
    plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops)
    if max_nodes is None:
        plan = apply_shape_budget(graph, plan, query)
    result = retrieve_context(
        graph,
        query,
        query_class,
        hops=plan.hops,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        scopes=scopes,
    )
    if not result.starts:
        if json_anchors:
            return json.dumps({"anchors": [], "packet": "", "message": "No matching graph anchors found for query."})
        return "No matching graph anchors found for query."

    if web_search:
        try:
            from ..retrieval.web import search_web
            from ..core import Node, Edge
            web_results = search_web(query, limit=3)
            for idx, res in enumerate(web_results):
                web_id = f"web_search__{idx}"
                temp_node = Node(
                    id=web_id,
                    label=res["title"],
                    kind="concept",
                    path=f"web:{idx}",
                    summary=res["snippet"][:200],
                    source=res["url"],
                    facts=[f"URL: {res['url']}", f"Snippet: {res['snippet']}"],
                    active=True
                )
                graph.nodes[web_id] = temp_node
                result.nodes.add(web_id)
                if result.starts:
                    temp_edge = Edge(
                        source=web_id,
                        target=result.starts[0],
                        type="discusses",
                        confidence=0.9,
                        provenance="web_search"
                    )
                    graph.edges.append(temp_edge)
                    result.edges.append(temp_edge)
        except Exception:
            pass

    if packet is None:
        plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, result.nodes, result.edges))
    else:
        plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops, packet=packet)
        if max_nodes is None:
            plan = apply_shape_budget(graph, plan, query)

    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        [query],
        query_class,
        plan.hops,
        (
            f"{cache_namespace}|{plan.planner_version}|{anchor_limit}|{max_nodes}|"
            f"{plan.node_budget}|{plan.direction}|{scopes}|{plan.packet}|{show_anchors}|{json_anchors}|{web_search}"
        ),
    )
    cached_packet = cache.get(resolved_graph_path, cache_key)
    if cached_packet:
        return cached_packet

    graph_packet = render_packet(graph, result.nodes, result.edges, plan.packet)
    _raise_if_invalid(graph_packet)

    if json_anchors and show_anchors:
        limit = anchor_limit if anchor_limit is not None else len(result.starts)
        response = json.dumps(
            {
                "anchors": [
                    {
                        "id": match.node.id,
                        "label": match.node.label,
                        "kind": match.node.kind,
                        "path": match.node.path,
                        "score": match.score,
                        "reasons": list(match.reasons),
                    }
                    for match in result.matches[:limit]
                ],
                "packet": graph_packet,
            },
            indent=2,
        )
    elif show_anchors:
        limit = anchor_limit if anchor_limit is not None else len(result.starts)
        out_lines = ["ANCHORS:"]
        for match in result.matches[:limit]:
            node = match.node
            out_lines.append(f"- {node.id} {node.label} [{node.kind}] {node.path} score={match.score:g}")
        out_lines.extend(["\nGRAPH:", graph_packet])
        response = "\n".join(out_lines)
    else:
        response = graph_packet

    cache.set(
        resolved_graph_path,
        cache_key,
        response,
        node_ids=result.nodes,
        paths=_node_paths(graph, result.nodes),
    )
    return response


def _raise_if_invalid(packet: str) -> None:
    validation = validate_packet(packet)
    if not validation.ok:
        raise ValueError("generated graph packet failed validation: " + "; ".join(validation.errors))


def _node_paths(graph: Graph, node_ids: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            node.path
            for node_id in node_ids
            if (node := graph.nodes.get(node_id)) is not None and node.path
        )
    )
