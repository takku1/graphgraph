from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    kind: str = "unknown"
    path: str = ""
    summary: str = ""
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    type: str
    weight: float = 1.0


@dataclass(frozen=True)
class Policy:
    id: str
    kind: str
    priority: str
    applies_to: tuple[str, ...]
    task_tags: tuple[str, ...]
    compact: str
    content: str = ""


@dataclass(frozen=True)
class Query:
    text: str
    query_class: str
    paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def outgoing(self) -> dict[str, list[Edge]]:
        out: dict[str, list[Edge]] = {}
        for edge in self.edges:
            out.setdefault(edge.source, []).append(edge)
        return out

    def incoming(self) -> dict[str, list[Edge]]:
        inc: dict[str, list[Edge]] = {}
        for edge in self.edges:
            inc.setdefault(edge.target, []).append(edge)
        return inc

    def expand(self, starts: list[str], hops: int, max_nodes: int | None = None) -> tuple[set[str], list[Edge]]:
        outgoing = self.outgoing()
        incoming = self.incoming()
        node_ids = set(starts)
        edge_list: list[Edge] = []
        frontier = set(starts)
        seen_edges: set[tuple[str, str, str]] = set()

        if max_nodes is not None and len(node_ids) > max_nodes:
            node_ids = set(starts[:max_nodes])
            return node_ids, []

        for _ in range(hops):
            next_candidates: set[str] = set()
            layer_edges: list[Edge] = []
            for node_id in frontier:
                for edge in outgoing.get(node_id, []) + incoming.get(node_id, []):
                    key = (edge.source, edge.target, edge.type)
                    if key not in seen_edges:
                        layer_edges.append(edge)
                    if edge.source not in node_ids:
                        next_candidates.add(edge.source)
                    if edge.target not in node_ids:
                        next_candidates.add(edge.target)

            if not next_candidates:
                # Still add remaining layer edges where both source and target are inside node_ids
                for edge in layer_edges:
                    key = (edge.source, edge.target, edge.type)
                    if key not in seen_edges and edge.source in node_ids and edge.target in node_ids:
                        seen_edges.add(key)
                        edge_list.append(edge)
                break

            if max_nodes is not None and len(node_ids) + len(next_candidates) > max_nodes:
                allowed_count = max_nodes - len(node_ids)
                if allowed_count <= 0:
                    break
                candidate_scores = {}
                for edge in layer_edges:
                    if edge.source in node_ids and edge.target in next_candidates:
                        candidate_scores[edge.target] = max(candidate_scores.get(edge.target, 0.0), edge.weight)
                    elif edge.target in node_ids and edge.source in next_candidates:
                        candidate_scores[edge.source] = max(candidate_scores.get(edge.source, 0.0), edge.weight)
                
                sorted_candidates = sorted(next_candidates, key=lambda n: candidate_scores.get(n, 0.0), reverse=True)
                next_frontier = set(sorted_candidates[:allowed_count])
            else:
                next_frontier = next_candidates

            for edge in layer_edges:
                key = (edge.source, edge.target, edge.type)
                if key not in seen_edges:
                    is_src_ok = edge.source in node_ids or edge.source in next_frontier
                    is_tgt_ok = edge.target in node_ids or edge.target in next_frontier
                    if is_src_ok and is_tgt_ok:
                        seen_edges.add(key)
                        edge_list.append(edge)

            node_ids |= next_frontier
            frontier = next_frontier
            if max_nodes is not None and len(node_ids) >= max_nodes:
                break

        return node_ids, edge_list
