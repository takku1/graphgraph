"""Utilities to benchmark symbol extraction performance and token usage.

Provides an approximate token count for a graph, using the built-in
``graphgraph`` packet size estimator. Used by `tests/test_benchmark.py`, which
drives `extract_symbols` directly and asserts against this estimate.
"""

from ..graph.core import Graph


def estimate_token_size(graph: Graph) -> int:
    """Estimate the number of tokens required to transmit *graph*.

    The current implementation serialises the graph to JSON and counts the words.
    This is a rough proxy for LLM token usage.
    """
    import json
    payload = json.dumps({
        "nodes": [n.__dict__ for n in graph.nodes.values()],
        "edges": [e.__dict__ for e in graph.edges]
    })
    # Very naive tokenisation: split on whitespace and punctuation.
    return len(payload.split())
