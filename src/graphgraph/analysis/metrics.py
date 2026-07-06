from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..graph.core import Graph


@dataclass(frozen=True)
class GraphSummary:
    nodes: int
    edges: int
    node_kinds: dict[str, int]
    edge_types: dict[str, int]
    metadata: dict[str, str]


@dataclass(frozen=True)
class GraphComparison:
    left: GraphSummary
    right: GraphSummary
    shared_node_paths: int
    shared_edge_keys: int
    left_only_edge_keys: int
    right_only_edge_keys: int
    shared_normalized_edges: int


def summarize_graph(graph: Graph) -> GraphSummary:
    return GraphSummary(
        nodes=len(graph.nodes),
        edges=len(graph.edges),
        node_kinds=dict(Counter(node.kind for node in graph.nodes.values())),
        edge_types=dict(Counter(edge.type for edge in graph.edges)),
        metadata=dict(graph.metadata),
    )


def edge_keys(graph: Graph) -> set[tuple[str, str, str]]:
    return {(edge.source, edge.target, edge.type) for edge in graph.edges}


def node_paths(graph: Graph) -> set[str]:
    return {node.path for node in graph.nodes.values() if node.path}


def normalized_edge_keys(graph: Graph) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        src = graph.nodes.get(edge.source)
        tgt = graph.nodes.get(edge.target)
        src_key = (src.path or src.label) if src else edge.source
        tgt_key = (tgt.path or tgt.label) if tgt else edge.target
        keys.add((src_key, tgt_key, edge.type))
    return keys


def compare_graphs(left: Graph, right: Graph) -> GraphComparison:
    left_edges = edge_keys(left)
    right_edges = edge_keys(right)
    left_norm = normalized_edge_keys(left)
    right_norm = normalized_edge_keys(right)
    return GraphComparison(
        left=summarize_graph(left),
        right=summarize_graph(right),
        shared_node_paths=len(node_paths(left) & node_paths(right)),
        shared_edge_keys=len(left_edges & right_edges),
        left_only_edge_keys=len(left_edges - right_edges),
        right_only_edge_keys=len(right_edges - left_edges),
        shared_normalized_edges=len(left_norm & right_norm),
    )
