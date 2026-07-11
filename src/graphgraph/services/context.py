from __future__ import annotations

import json
from pathlib import Path

from ..graph.core import Graph, Query
from ..io import find_graph_path, find_lessons_path, find_policies_path, load_any, load_policies
from ..packets import render_packet
from ..packets.validation import validate_packet
from ..planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph
from ..planning.policies import render_policy_packet, select_policies
from ..retrieval import apply_shape_budget, expand_context, retrieve_context
from ..runtime.cache import TopologicalKVCache, compute_cache_key

_GRAPH_CACHE: dict[Path, tuple[int, int, Graph]] = {}
_GRAPH_CACHE_LIMIT = 4


def render_stable_skeleton(graph_path: Path | None = None, max_nodes: int = 100, packet: str = "gg_max") -> str:
    resolved_graph_path = graph_path or find_graph_path()
    graph = _load_graph_cached(resolved_graph_path)
    pr = graph.pagerank()
    top_nodes = sorted(pr, key=pr.get, reverse=True)[:max_nodes]
    top_set = set(top_nodes)
    skeleton_edges = [edge for edge in graph.edges if edge.active and edge.source in top_set and edge.target in top_set]
    return render_packet(graph, top_set, skeleton_edges, packet)


class FullGraphTooLargeError(ValueError):
    """Raised by render_full_graph when the estimated token cost exceeds max_tokens."""

    def __init__(self, estimated_tokens: int, max_tokens: int, node_count: int, edge_count: int):
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens
        self.node_count = node_count
        self.edge_count = edge_count
        super().__init__(
            f"Full-graph packet is ~{estimated_tokens} tokens ({node_count} nodes, {edge_count} edges), "
            f"over the {max_tokens}-token guard. Pass max_tokens=None (or a higher value) to render anyway, "
            "or use a scoped query instead -- see docs/retrieval-confidence-routing.md for when a full "
            "dump is actually the right tool vs. a targeted query."
        )


def render_full_graph(
    graph_path: Path | None = None,
    packet: str = "gg_max",
    max_tokens: int | None = 20_000,
) -> str:
    """Render every active node/edge in the graph as one packet -- no query, no budget.

    This is deliberately not the default path. query/context/final exist
    precisely so a caller never has to pay for the whole graph to answer one
    question (see docs/retrieval-confidence-routing.md) -- this function is
    the explicit "I actually want everything" escape hatch for cases like
    full-corpus offline analysis or exporting a complete snapshot.

    Raises FullGraphTooLargeError if the estimated token cost exceeds
    max_tokens (a cheap regex-based proxy, the same one eval.py uses,
    not tiktoken -- good enough to catch "this is about to be 190,000
    tokens" without adding a dependency). Pass max_tokens=None to disable
    the guard entirely.
    """
    resolved_graph_path = graph_path or find_graph_path()
    graph = _load_graph_cached(resolved_graph_path)
    all_nodes = {node_id for node_id, node in graph.nodes.items() if node.active}
    all_edges = [edge for edge in graph.edges if edge.active]
    rendered = render_packet(graph, all_nodes, all_edges, packet)
    if max_tokens is not None:
        from ..eval import estimate_tokens

        estimated = estimate_tokens(rendered)
        if estimated > max_tokens:
            raise FullGraphTooLargeError(estimated, max_tokens, len(all_nodes), len(all_edges))
    return rendered


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

    plan = plan_context(query_class, query_text, max_nodes=max_nodes, packet=packet)
    lessons_path = find_lessons_path()
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        starts,
        query_class,
        plan.hops,
        (
            f"request_v2|{resolved_graph_path.resolve()}|{packet or 'auto'}|{plan.packet}|"
            f"{cache_namespace}|{plan.planner_version}|{query_text}|{paths}|{tags}|"
            f"{plan.node_budget}|{plan.direction}|{tuple(starts)}|{_session_signature()}|"
            f"{_file_signature(resolved_policies_path)}|{_file_signature(lessons_path)}"
        ),
    )
    cached_packet = cache.get(resolved_graph_path, cache_key)
    if cached_packet:
        return cached_packet

    graph = _load_graph_cached(resolved_graph_path)
    if max_nodes is None:
        plan = apply_shape_budget(graph, plan, query_text)
    resolved_starts = resolve_start_nodes(graph, starts)
    if not resolved_starts:
        # Build a helpful diagnostic: search the graph for candidates
        from ..findnodes import suggest_node_ids
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
    policies = load_policies(resolved_policies_path) if resolved_policies_path else []
    query = Query(text=query_text, query_class=query_class, paths=paths, tags=tags)

    # 5. Read lessons/reflections if available
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
) -> str:
    resolved_graph_path = graph_path or find_graph_path()
    plan = plan_context(
        query_class,
        query,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        hops=hops,
        packet=packet,
    )
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(
        [query],
        query_class,
        plan.hops,
        (
            f"request_v2|{resolved_graph_path.resolve()}|{cache_namespace}|{plan.planner_version}|"
            f"{anchor_limit}|{max_nodes}|{plan.node_budget}|{plan.direction}|{scopes}|"
            f"{packet or 'auto'}|{plan.packet}|{show_anchors}|{json_anchors}|{_session_signature()}"
        ),
    )
    cached_packet = cache.get(resolved_graph_path, cache_key)
    if cached_packet:
        return cached_packet

    graph = _load_graph_cached(resolved_graph_path)
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

    if packet is None:
        plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, result.nodes, result.edges))

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
                        "line": match.node.line,
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
            location = f"{node.path}:{node.line}" if node.line else node.path
            out_lines.append(f"- {node.id} {node.label} [{node.kind}] {location} score={match.score:g}")
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


def _session_signature() -> tuple[tuple[str, int, int, int], ...]:
    from ..retrieval.git_utils import get_git_modified_files

    signature = []
    for path, change_count in get_git_modified_files().items():
        source_path = Path(path)
        try:
            stat = source_path.stat()
            signature.append((path, change_count, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, change_count, 0, 0))
    return tuple(sorted(signature))


def _file_signature(path: Path | None) -> tuple[str, int, int] | None:
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def _load_graph_cached(path: Path) -> Graph:
    resolved = path.resolve()
    stat = resolved.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    cached = _GRAPH_CACHE.get(resolved)
    if cached is not None and cached[:2] == fingerprint:
        return cached[2]
    graph = load_any(resolved)
    _GRAPH_CACHE[resolved] = (*fingerprint, graph)
    while len(_GRAPH_CACHE) > _GRAPH_CACHE_LIMIT:
        _GRAPH_CACHE.pop(next(iter(_GRAPH_CACHE)))
    return graph
