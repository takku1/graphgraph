"""Edge orientation used when diffusing a query-conditioned field.

Personalized PageRank follows edge direction, so an entity receives influence
only along a directed path from a seed. On real project graphs that makes the
field a spotlight rather than a field: a large majority of entities -- docs,
concepts, leaf callees -- are directed sinks and never receive any mass.

The coupling is therefore a distinct modelling choice from the representation
built on top of the field, and it is exchanged as its own stage so the two can
be measured independently.
"""

from __future__ import annotations

from .core import Edge, Graph

EDGE_COUPLINGS: tuple[str, ...] = ("directed", "symmetric", "reverse")


def coupled_graph(graph: Graph, coupling: str = "directed") -> Graph:
    """Return the graph a field should diffuse over under ``coupling``.

    ``directed`` follows call/import direction and returns the input unchanged.
    ``reverse`` diffuses to dependents instead of dependencies. ``symmetric``
    treats an edge as coupling both endpoints, the orientation implied by
    reading a project as an undirected dependency neighbourhood.

    The input graph is never mutated, and edge payloads (weight, confidence,
    provenance) are preserved so traversal strength is unchanged. Only active
    edges are reoriented; inactive history stays out of the field.
    """
    if coupling not in EDGE_COUPLINGS:
        raise ValueError(f"unknown edge coupling {coupling!r}; expected one of {EDGE_COUPLINGS}")
    if coupling == "directed":
        return graph
    # Reorienting 34k edges costs ~67ms on a mid-size project and depends only
    # on (revision, coupling), so it is memoised on the source graph the same
    # way ranking caches are. Any mutation bumps the revision and invalidates.
    key = (graph.mutation_revision, coupling)
    cached = getattr(graph, "_coupled_graph_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    active = [edge for edge in graph.edges if edge.active]
    flipped = [
        Edge(edge.target, edge.source, edge.type, edge.weight, edge.confidence, edge.provenance)
        for edge in active
    ]
    edges = active + flipped if coupling == "symmetric" else flipped
    result = Graph(nodes=dict(graph.nodes), edges=edges)
    graph._coupled_graph_cache = (key, result)
    return result


__all__ = ["EDGE_COUPLINGS", "coupled_graph"]
