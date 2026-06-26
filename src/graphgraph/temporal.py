from __future__ import annotations

from datetime import datetime

from .core import Edge, Graph, Node


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def active_at_node(node: Node, when: str) -> bool:
    if not node.active:
        return False
    t = _parse_time(when)
    if t is None:
        return node.active
    created = _parse_time(node.created_at)
    updated = _parse_time(node.updated_at)
    if created and created > t:
        return False
    if updated and updated > t and not node.created_at:
        return False
    return True


def active_at_edge(edge: Edge, when: str) -> bool:
    if not edge.active:
        return False
    t = _parse_time(when)
    if t is None:
        return edge.active
    start = _parse_time(edge.valid_from)
    end = _parse_time(edge.valid_to)
    if start and start > t:
        return False
    if end and end <= t:
        return False
    return True


def graph_at(graph: Graph, when: str) -> Graph:
    nodes = {nid: node for nid, node in graph.nodes.items() if active_at_node(node, when)}
    edges = [
        edge
        for edge in graph.edges
        if edge.source in nodes and edge.target in nodes and active_at_edge(edge, when)
    ]
    return Graph(nodes=nodes, edges=edges, metadata=dict(graph.metadata))
