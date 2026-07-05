from __future__ import annotations

import json
import statistics
import subprocess
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


def time_subprocess_startup(args: list[str], *, rounds: int = 5) -> dict[str, float]:
    """Median/min wall time for a fresh subprocess, isolated from graph load.

    This is the "bare interpreter + import" cost: process spawn, importing the
    graphgraph package (and, for the CLI variant, argparse setup), with no
    graph file touched at all. It answers "how much of first-query latency is
    just starting the process" (hgihlevelideas.md roadmap item 2), separate
    from `time_search`'s in-process graph load + query cost above.
    """
    samples = []
    for _ in range(rounds):
        start = time.perf_counter()
        subprocess.run(args, check=True, capture_output=True)
        samples.append(time.perf_counter() - start)
    return {
        "rounds": rounds,
        "min_seconds": round(min(samples), 4),
        "median_seconds": round(statistics.median(samples), 4),
        "max_seconds": round(max(samples), 4),
    }


def main() -> None:
    if not GRAPH_PATH.exists():
        raise SystemExit("missing live graph; run benchmarks/context_graph/live_graph_shape.py first")
    OUT.mkdir(parents=True, exist_ok=True)

    import_startup = time_subprocess_startup([sys.executable, "-c", "import graphgraph"])
    cli_startup = time_subprocess_startup([sys.executable, "-m", "graphgraph", "--help"])

    load_start = time.perf_counter()
    graph = load_any(GRAPH_PATH)
    graph_load_seconds = time.perf_counter() - load_start

    cold_seconds = time_search(graph, rounds=1)
    cached_seconds = time_search(graph, rounds=5)
    report = {
        "graph": str(GRAPH_PATH),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "queries": len(QUERIES),
        "import_startup": import_startup,
        "cli_startup": cli_startup,
        "graph_load_seconds": round(graph_load_seconds, 4),
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
    import_startup = report["import_startup"]
    cli_startup = report["cli_startup"]
    return "\n".join([
        "# Search Hot Path",
        "",
        f"- Graph: `{report['graph']}`",
        f"- Nodes: `{report['nodes']}`",
        f"- Edges: `{report['edges']}`",
        f"- Queries/round: `{report['queries']}`",
        "",
        "## Startup cost (isolated from graph load/query, fresh subprocess each round)",
        "",
        f"- `import graphgraph` median: `{import_startup['median_seconds']}s` (min `{import_startup['min_seconds']}s`, {import_startup['rounds']} rounds)",
        f"- `graphgraph --help` (full CLI cold start) median: `{cli_startup['median_seconds']}s` (min `{cli_startup['min_seconds']}s`, {cli_startup['rounds']} rounds)",
        "",
        "## In-process graph load + search",
        "",
        f"- Graph load (this process, one read): `{report['graph_load_seconds']}s`",
        f"- Cold round seconds: `{report['cold_round_seconds']}`",
        f"- Cached rounds: `{report['cached_rounds']}`",
        f"- Cached total seconds: `{report['cached_total_seconds']}`",
        f"- Cached seconds/query: `{report['cached_seconds_per_query']}`",
        f"- PageRank cache present: `{report['pagerank_cache_present']}`",
        "",
        "## Read",
        "",
        "- This measures repeated lexical search against one loaded graph, plus the fixed",
        "  process-startup cost that precedes it in a real CLI invocation.",
        "- It is intended to catch regressions in centrality/search hot paths, and to show",
        "  how much of a single-shot CLI query's latency is unavoidable interpreter/import",
        "  overhead vs. graph load vs. actual search.",
    ]) + "\n"


if __name__ == "__main__":
    main()
