from __future__ import annotations

import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.io import load_any  # noqa: E402
from graphgraph.retrieval import search_nodes  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out" / "live"
REPORT_JSON = OUT / "search_hot_path.json"
REPORT_MD = OUT / "search_hot_path.md"
GRAPH_PATH = OUT / "live_graph_shape.graph.json"

QUERIES = (
    "planner packet selection edge threshold",
    "scanner imports relative package",
    "doc code pairing benchmark coverage gaps",
    "model reasoning benchmark live scoring",
)


def time_search(graph, *, rounds: int) -> float:
    start = time.perf_counter()
    for _ in range(rounds):
        for query in QUERIES:
            search_nodes(graph, query, limit=10)
    return time.perf_counter() - start


def main() -> None:
    if not GRAPH_PATH.exists():
        raise SystemExit("missing live graph; run benchmarks/context_graph/live_graph_shape.py first")
    OUT.mkdir(parents=True, exist_ok=True)
    graph = load_any(GRAPH_PATH)
    cold_seconds = time_search(graph, rounds=1)
    cached_seconds = time_search(graph, rounds=5)
    report = {
        "graph": str(GRAPH_PATH),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "queries": len(QUERIES),
        "cold_round_seconds": round(cold_seconds, 4),
        "cached_rounds": 5,
        "cached_total_seconds": round(cached_seconds, 4),
        "cached_seconds_per_query": round(cached_seconds / (5 * len(QUERIES)), 5),
        "pagerank_cache_present": graph._pagerank_cache is not None,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def render_markdown(report: dict[str, object]) -> str:
    return "\n".join([
        "# Search Hot Path",
        "",
        f"- Graph: `{report['graph']}`",
        f"- Nodes: `{report['nodes']}`",
        f"- Edges: `{report['edges']}`",
        f"- Queries/round: `{report['queries']}`",
        f"- Cold round seconds: `{report['cold_round_seconds']}`",
        f"- Cached rounds: `{report['cached_rounds']}`",
        f"- Cached total seconds: `{report['cached_total_seconds']}`",
        f"- Cached seconds/query: `{report['cached_seconds_per_query']}`",
        f"- PageRank cache present: `{report['pagerank_cache_present']}`",
        "",
        "## Read",
        "",
        "- This measures repeated lexical search against one loaded graph.",
        "- It is intended to catch regressions in centrality/search hot paths.",
    ]) + "\n"


if __name__ == "__main__":
    main()
