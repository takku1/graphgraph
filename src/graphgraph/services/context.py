from __future__ import annotations

import json
from pathlib import Path

from ..graph.core import Graph, Query
from ..io import (
    find_graph_path,
    find_lessons_path,
    find_policies_path,
    load_any_cached,
    load_policies,
    project_root_for_graph,
)
from ..packets import render_packet
from ..packets.validation import validate_packet
from ..planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph
from ..planning.budgets import plan_terms
from ..planning.policies import render_policy_packet, select_policies
from ..representation import (
    HybridRepresentationConfig,
    accept_representation,
    compile_hybrid_representation,
)
from ..retrieval import apply_shape_budget, expand_context, packet_priority, retrieve_context  # noqa: F401
from ..runtime.cache import (
    TopologicalKVCache,
    cache_file_for_graph,
    compute_cache_key,
    runtime_cache_fingerprint,
)
from .cache_identity import file_signature, packet_dependency_paths, worktree_signature

FINAL_RESPONSE_CACHE_VERSION = "final_v8_registry_aware_facet_preflight"


def render_stable_skeleton(graph_path: Path | None = None, max_nodes: int = 100, packet: str = "gg") -> str:
    resolved_graph_path = graph_path or find_graph_path()
    graph = load_any_cached(resolved_graph_path)
    pr = graph.pagerank()
    # Ties are broken by node id, not by dict insertion order. This packet's
    # whole purpose is to be a byte-stable prompt-cache prefix, and PageRank
    # ties are common in flat graphs -- ordering them by insertion meant a
    # rescan that produced an equivalent graph in a different order could
    # reshuffle the skeleton, or swap which tied node survived the max_nodes
    # cut, breaking the cache prefix it exists to hold steady.
    top_nodes = sorted(pr, key=lambda node_id: (-pr[node_id], node_id))[:max_nodes]
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
    packet: str = "gg",
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
    graph = load_any_cached(resolved_graph_path)
    all_nodes = {node_id for node_id, node in graph.nodes.items() if node.active}
    all_edges = [edge for edge in graph.edges if edge.active]
    rendered = render_packet(graph, all_nodes, all_edges, packet)
    if max_tokens is not None:
        from ..packets import estimate_tokens

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
    representation: str = "flat",
    representation_budget: int | None = None,
) -> str:
    resolved_graph_path = graph_path or find_graph_path()
    project_root = project_root_for_graph(resolved_graph_path)
    resolved_policies_path = policies_path if policies_path is not None else find_policies_path(project_root)

    plan = plan_context(query_class, query_text, max_nodes=max_nodes, packet=packet)
    lessons_path = find_lessons_path(project_root)
    # Co-locate the packet cache with the graph it caches. Defaulting to
    # `.graphgraph/kv_cache.json` resolved it against the process CWD, so
    # querying another project's graph wrote entries into whichever
    # directory the command happened to run from -- polluting and evicting
    # that project's warm cache, and leaving `graphgraph cache --clear
    # --graph X` clearing a file that was never the one in use.
    cache = TopologicalKVCache(cache_file_for_graph(resolved_graph_path))
    cache_key = compute_cache_key(
        starts,
        query_class,
        plan.hops,
        (
            f"{FINAL_RESPONSE_CACHE_VERSION}|{resolved_graph_path.resolve()}|"
            f"runtime={runtime_cache_fingerprint()}|"
            f"{packet or 'auto'}|{plan.packet}|"
            f"{representation}|{representation_budget}|"
            f"{cache_namespace}|{plan.planner_version}|{query_text}|{paths}|{tags}|"
            f"{plan.node_budget}|{plan.direction}|{tuple(starts)}|"
            f"{worktree_signature(project_root)}|"
            f"{file_signature(resolved_policies_path)}|{file_signature(lessons_path)}"
        ),
    )
    cached_packet = cache.get(resolved_graph_path, cache_key)
    if cached_packet:
        return cached_packet

    graph = load_any_cached(resolved_graph_path)
    if max_nodes is None:
        plan = apply_shape_budget(graph, plan, query_text)
    resolved_starts = resolve_start_nodes(graph, starts)
    if not resolved_starts:
        # Build a helpful diagnostic: search the graph for candidates
        from ..retrieval.findnodes import suggest_node_ids

        suggestions = suggest_node_ids(graph, starts, limit=6)
        hint = ""
        if suggestions:
            hint = "  Closest matches in graph:\n" + "\n".join(
                f"    {m.node.id}  ({m.node.label}, {m.node.kind}, {m.node.path})" for m in suggestions
            )
        raise ValueError(
            f"No graph nodes matched the requested starts: {starts!r}\n"
            f"{hint}\n"
            "  Options:\n"
            "   1. Use 'search_nodes' tool to find the right node IDs first.\n"
            "   2. Use 'query_context' tool with a natural-language query — no node IDs needed.\n"
            "   3. Re-scan if the file was recently added: graphgraph scan --depth symbols --docs"
        )
    nodes, edges = expand_context(graph, tuple(resolved_starts), plan, query_terms=plan_terms(query_text))
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
    priority = packet_priority(tuple(resolved_starts), nodes, edges, query_class, graph=graph)
    graph_packet = render_packet(
        graph,
        nodes,
        edges,
        plan.packet,
        priority=priority,
    )
    representation_receipt: dict[str, object] = {}
    if representation == "hybrid":
        try:
            hybrid = compile_hybrid_representation(
                graph,
                {node_id: 1.0 for node_id in resolved_starts},
                packet_format=plan.packet,
                priority=priority,
                config=HybridRepresentationConfig(
                    token_budget=representation_budget or 4096,
                ),
            )
        except ValueError as exc:
            representation_receipt = {
                "policy": "hybrid",
                "status": "fallback_flat",
                "reason": str(exc),
                "token_budget": representation_budget or 4096,
            }
        else:
            hybrid_packet, representation_receipt = accept_representation(hybrid)
            if hybrid_packet is not None:
                graph_packet = hybrid_packet
    elif representation != "flat":
        raise ValueError(f"unknown representation policy: {representation}")
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
    if representation_receipt:
        out_lines.append(
            "REPRESENTATION:" + json.dumps(representation_receipt, separators=(",", ":"), ensure_ascii=False)
        )
    out_lines.append(graph_packet)
    final_output = "\n".join(out_lines)
    cache.set(
        resolved_graph_path,
        cache_key,
        final_output,
        node_ids=nodes,
        paths=packet_dependency_paths(graph, nodes),
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


def _raise_if_invalid(packet: str) -> None:
    validation = validate_packet(packet)
    if not validation.ok:
        raise ValueError("generated graph packet failed validation: " + "; ".join(validation.errors))
