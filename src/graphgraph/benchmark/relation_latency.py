"""Packed exact-relation latency by graph-size stratum (OW-AC-08 / FAN-04)."""

from __future__ import annotations

import statistics
import time
from typing import Any

from ..graph.core import Edge, Graph, Node
from ..retrieval.relations import query_relations

STRATA: tuple[tuple[str, int], ...] = (
    ("small", 100),
    ("medium", 1_000),
    ("large", 5_000),
)


def synthetic_call_graph(size: int) -> Graph:
    """A directed call chain of ``size`` functions. Deterministic, no I/O."""

    nodes = {
        f"n{i}": Node(f"n{i}", f"fn_{i}", "function", path=f"m{i // 50}.py")
        for i in range(size)
    }
    edges = [Edge(f"n{i}", f"n{i + 1}", "calls") for i in range(size - 1)]
    return Graph(nodes=nodes, edges=edges)


def measure_stratum(size: int, *, samples: int = 40) -> dict[str, Any]:
    graph = synthetic_call_graph(size)
    targets = [f"n{i}" for i in range(0, size, max(1, size // samples))][:samples]
    query_relations(graph, targets[0], direction="callers", limit=20)
    runs: list[float] = []
    for target in targets:
        started = time.perf_counter()
        query_relations(graph, target, direction="callers", limit=20)
        runs.append((time.perf_counter() - started) * 1000.0)
    runs.sort()
    return {
        "nodes": size,
        "samples": len(runs),
        "p50_ms": round(runs[len(runs) // 2], 4),
        "p95_ms": round(runs[min(len(runs) - 1, int(len(runs) * 0.95))], 4),
        "mean_ms": round(statistics.fmean(runs), 4),
    }


def measure_relation_latency_strata(*, samples: int = 40) -> dict[str, Any]:
    strata = {name: measure_stratum(size, samples=samples) for name, size in STRATA}
    return {
        "metric": "packed_exact_relation_p95_ms",
        "direction": "lower",
        "strata": strata,
        "value": strata["medium"]["p95_ms"],
        "unit": "ms",
    }
