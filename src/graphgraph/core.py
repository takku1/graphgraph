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
        # Weak edge types contribute less to candidate scores so they don't crowd out structural edges.
        _TYPE_MULT: dict[str, float] = {"references": 0.5, "links": 0.6, "includes": 0.7}

        outgoing = self.outgoing()
        incoming = self.incoming()

        included: set[str] = {s for s in starts if s in self.nodes}
        seen_edges: set[tuple[str, str, str]] = set()
        edge_list: list[Edge] = []
        frontier = set(included)

        for _ in range(hops):
            new_edges: list[Edge] = []
            scores: dict[str, float] = {}

            for nid in frontier:
                for edge in outgoing.get(nid, []) + incoming.get(nid, []):
                    ekey = (edge.source, edge.target, edge.type)
                    if ekey not in seen_edges:
                        new_edges.append(edge)
                        seen_edges.add(ekey)
                    neighbor = edge.target if edge.source == nid else edge.source
                    if neighbor not in included and neighbor in self.nodes:
                        mult = _TYPE_MULT.get(edge.type, 1.0)
                        scores[neighbor] = scores.get(neighbor, 0.0) + edge.weight * mult

            if not scores:
                for edge in new_edges:
                    if edge.source in included and edge.target in included:
                        edge_list.append(edge)
                break

            # Rank candidates by cumulative weighted score (sum, not max), apply budget.
            ranked = sorted(scores, key=scores.__getitem__, reverse=True)
            if max_nodes is not None:
                available = max_nodes - len(included)
                if available <= 0:
                    break
                ranked = ranked[:available]

            next_set = set(ranked)
            all_included = included | next_set

            for edge in new_edges:
                if edge.source in all_included and edge.target in all_included:
                    edge_list.append(edge)

            included = all_included
            frontier = next_set

            if max_nodes is not None and len(included) >= max_nodes:
                break

        return included, edge_list
