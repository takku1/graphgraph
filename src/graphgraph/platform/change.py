from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from ..graph.core import Graph


@dataclass(frozen=True)
class ChangePacket:
    added_nodes: tuple[str, ...]
    removed_nodes: tuple[str, ...]
    changed_nodes: tuple[str, ...]
    added_edges: tuple[str, ...]
    removed_edges: tuple[str, ...]
    impacted_nodes: tuple[str, ...]
    breaking_changes: tuple[str, ...]
    cursor: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class ContinuationReceipt:
    cursor: str
    created_at: str
    objective: str
    completed: tuple[str, ...]
    remaining: tuple[str, ...]
    changed_paths: tuple[str, ...]
    validation: tuple[str, ...]
    next_query: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def build_change_packet(before: Graph, after: Graph, *, impact_hops: int = 2) -> ChangePacket:
    before_nodes = {node_id: node for node_id, node in before.nodes.items() if node.active}
    after_nodes = {node_id: node for node_id, node in after.nodes.items() if node.active}
    added_nodes = sorted(after_nodes.keys() - before_nodes.keys())
    removed_nodes = sorted(before_nodes.keys() - after_nodes.keys())
    changed_nodes = sorted(
        node_id for node_id in before_nodes.keys() & after_nodes.keys()
        if before_nodes[node_id] != after_nodes[node_id]
    )
    before_edges = {_edge_key(edge) for edge in before.edges if edge.active}
    after_edges = {_edge_key(edge) for edge in after.edges if edge.active}
    added_edges = sorted(after_edges - before_edges)
    removed_edges = sorted(before_edges - after_edges)
    seeds = set(added_nodes + removed_nodes + changed_nodes)
    impacted = _impact(after, seeds, impact_hops) | _impact(before, seeds, impact_hops)
    breaking = []
    for node_id in removed_nodes:
        node = before_nodes[node_id]
        if node.kind in {"function", "method", "class", "interface", "struct", "module"}:
            breaking.append(f"removed {node.kind} {node.label} ({node.path})")
    for edge_key in removed_edges:
        if "|calls|" in edge_key or "|imports" in edge_key or "|implements|" in edge_key:
            breaking.append(f"removed relation {edge_key}")
    canonical = json.dumps({
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
    }, sort_keys=True, separators=(",", ":"))
    return ChangePacket(
        tuple(added_nodes),
        tuple(removed_nodes),
        tuple(changed_nodes),
        tuple(added_edges),
        tuple(removed_edges),
        tuple(sorted(impacted - seeds)),
        tuple(breaking),
        hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
    )


def build_continuation_receipt(
    *,
    objective: str,
    completed: tuple[str, ...] = (),
    remaining: tuple[str, ...] = (),
    changed_paths: tuple[str, ...] = (),
    validation: tuple[str, ...] = (),
    next_query: str = "",
    cursor: str = "",
) -> ContinuationReceipt:
    created_at = datetime.now(timezone.utc).isoformat()
    if not cursor:
        raw = json.dumps([objective, completed, remaining, changed_paths, validation], sort_keys=True)
        cursor = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return ContinuationReceipt(
        cursor, created_at, objective, completed, remaining, changed_paths, validation, next_query
    )


def _edge_key(edge) -> str:
    return f"{edge.source}|{edge.type}|{edge.target}"


def _impact(graph: Graph, seeds: set[str], hops: int) -> set[str]:
    seen = set(seeds)
    frontier = set(seeds)
    adjacency: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.active:
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)
    for _ in range(max(0, hops)):
        frontier = {target for source in frontier for target in adjacency.get(source, ())} - seen
        seen.update(frontier)
    return seen
