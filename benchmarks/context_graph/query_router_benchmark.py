from __future__ import annotations

import json
from time import perf_counter

from graphgraph.planning import route_query

CASES = (
    ("where is render_packet defined", "direct_lookup"),
    ("show the source definition for TopologicalKVCache", "direct_lookup"),
    ("what calls validate_packet and where is it tested", "reverse_lookup"),
    ("which types implement DiscoveryPipeline", "reverse_lookup"),
    ("trace request parsing through planning to packet rendering", "multi_hop_path"),
    ("find the path from scan_directory to save_validated_graph", "multi_hop_path"),
    ("what is the blast radius if Edge changes", "blast_radius"),
    ("what breaks if packet rendering changes", "blast_radius"),
    ("how does retrieval work", "subsystem_summary"),
    ("architecture of the scanner subsystem", "subsystem_summary"),
    ("README installation and usage guide", "doc_summary"),
    ("documentation for MCP setup", "doc_summary"),
    ("is legacy_cache unused and does it have no callers", "negative_query"),
    ("does MissingAdapter exist", "negative_query"),
    ("what changed recently in scanner", "recent_changes"),
    ("show recent commits touching retrieval", "recent_changes"),
)


def run(iterations: int = 100_000) -> dict[str, object]:
    rows = [
        {
            "query": query,
            "expected": expected,
            "actual": (route := route_query(query)).query_class,
            "pass": route.query_class == expected,
            "confidence": route.confidence,
            "margin": route.margin,
        }
        for query, expected in CASES
    ]
    started = perf_counter()
    for index in range(iterations):
        route_query(CASES[index % len(CASES)][0])
    elapsed = perf_counter() - started
    return {
        "cases": len(rows),
        "passed": sum(bool(row["pass"]) for row in rows),
        "iterations": iterations,
        "total_ms": elapsed * 1000.0,
        "microseconds_per_route": elapsed * 1_000_000.0 / iterations,
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
