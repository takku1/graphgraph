"""Resident exact-query latency and session catalog (OW-AC-01)."""

from __future__ import annotations

import random
import statistics
import time
from pathlib import Path
from typing import Any, Sequence

from ..graph.core import Graph
from ..retrieval.relations import query_relations

# Interactive SLO for a warm MCP exact relation after the process is resident.
# Measured ~90 ms before freshness memoization; the gate is 3x that floor so a
# slower machine still fails only on a real regression, not noise.
SESSION_EXACT_P95_TARGET_MS = 250.0
REQUIRED_SESSION_TOOLS = (
    "query_relations",
    "query_context",
    "search_nodes",
    "project_status",
)


def quantile(samples: Sequence[float], q: float) -> float:
    """Nearest-rank sample quantile for ``q`` in (0, 1]."""

    if not samples:
        raise ValueError("quantile requires at least one sample")
    if not 0.0 < q <= 1.0:
        raise ValueError(f"quantile q must be in (0, 1], got {q}")
    ordered = sorted(samples)
    rank = max(1, int(round(q * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def session_tool_names() -> tuple[str, ...]:
    """Tool names an agent sees after ``initialize`` + ``tools/list``."""

    from ..mcp import dispatch

    hello = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    if hello is None or "result" not in hello:
        return ()
    listed = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    if listed is None:
        return ()
    tools = listed.get("result", {}).get("tools", ())
    return tuple(str(tool.get("name", "")) for tool in tools if isinstance(tool, dict))


def measure_kernel_exact_p95(graph: Graph, *, samples: int = 80, seed: int = 7) -> dict[str, Any]:
    candidates = [
        node_id
        for node_id, node in graph.nodes.items()
        if node.active and node.kind in {"function", "method"} and node.label
    ]
    if not candidates:
        return {
            "metric": "resident_exact_query_p95_ms",
            "value": None,
            "status": "unavailable",
            "reason": "no function/method nodes",
        }
    rng = random.Random(seed)
    sample = rng.sample(candidates, min(samples, len(candidates)))
    query_relations(graph, sample[0], direction="callers", limit=20)
    runs: list[float] = []
    for node_id in sample:
        started = time.perf_counter()
        query_relations(graph, node_id, direction="callers", limit=20)
        runs.append((time.perf_counter() - started) * 1000.0)
    p95 = quantile(runs, 0.95)
    return {
        "metric": "resident_kernel_exact_p95_ms",
        "value": round(p95, 4),
        "unit": "ms",
        "direction": "lower",
        "samples": len(runs),
        "min": round(min(runs), 4),
        "max": round(max(runs), 4),
        "median": round(statistics.median(runs), 4),
    }


def measure_session_exact_p95(
    graph_path: Path,
    *,
    samples: int = 40,
    seed: int = 7,
) -> dict[str, Any]:
    from ..io.core import load_any
    from ..mcp import dispatch

    graph = load_any(graph_path)
    candidates = [
        node_id
        for node_id, node in graph.nodes.items()
        if node.active and node.kind in {"function", "method"} and node.label
    ]
    if not candidates:
        return {
            "metric": "resident_exact_query_p95_ms",
            "value": None,
            "status": "unavailable",
            "reason": "no function/method nodes",
        }
    rng = random.Random(seed)
    sample = rng.sample(candidates, min(samples, len(candidates)))
    resolved = str(graph_path.resolve())

    def _call(node_id: str) -> None:
        dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "query_relations",
                    "arguments": {
                        "target": node_id,
                        "direction": "callers",
                        "limit": 20,
                        "graph_path": resolved,
                    },
                },
            }
        )

    session_tool_names()
    _call(sample[0])
    runs: list[float] = []
    for node_id in sample:
        started = time.perf_counter()
        _call(node_id)
        runs.append((time.perf_counter() - started) * 1000.0)
    p95 = quantile(runs, 0.95)
    return {
        "metric": "resident_exact_query_p95_ms",
        "value": round(p95, 4),
        "unit": "ms",
        "direction": "lower",
        "target": SESSION_EXACT_P95_TARGET_MS,
        "status": "success" if p95 <= SESSION_EXACT_P95_TARGET_MS else "fail",
        "samples": len(runs),
        "min": round(min(runs), 4),
        "max": round(max(runs), 4),
        "median": round(statistics.median(runs), 4),
        "query": "MCP tools/call query_relations callers on a known node id after initialize+tools/list",
    }
