# Benchmark utilities for graphgraph
"""Utilities to benchmark symbol extraction performance and token usage.

The goal is to provide empirical data on:
* Runtime (seconds) of `extract_symbols` for a given set of files.
* Number of nodes and edges created.
* Approximate token count (using the built‑in `graphgraph` packet size estimator).

These helpers are used by the test suite (see `tests/test_benchmark.py`).
"""

import time
from pathlib import Path
from typing import List, Tuple

from graphgraph.scanner.ast import extract_symbols

from ..graph.core import Graph


def run_extraction(files: List[Tuple[Path, str, str, str]], max_symbols: int = 5000) -> Tuple[Graph, float]:
    """Run symbol extraction on *files* and return the resulting ``Graph`` and elapsed time.

    Parameters
    ----------
    files: List[Tuple[Path, str, str, str]]
        Each tuple is ``(path, rel_posix, file_node_id, text)`` as required by
        :func:`extract_symbols`.
    max_symbols: int, optional
        Upper bound for total symbols to extract. Mirrors the default in the
        library but can be tuned for benchmarking.
    """
    start = time.perf_counter()
    symbol_nodes, symbol_edges = extract_symbols(files, max_total_symbols=max_symbols)
    elapsed = time.perf_counter() - start
    # Build a temporary graph to hold the symbols only (no existing graph merged).
    g = Graph()
    for n in symbol_nodes.values():
        g.add_node(n)
    for e in symbol_edges:
        g.add_edge(e)
    return g, elapsed

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
