from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.io import load_any  # noqa: E402
from graphgraph.retrieval import search_nodes  # noqa: E402

GRAPH_PATH = ROOT / ".graphgraph" / "graph.gg"
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "live"
REPORT_JSON = OUT / "local_ppr.json"
REPORT_MD = OUT / "local_ppr.md"
QUERIES = (
    "who calls render_packet",
    "scan_directory incremental manifest",
    "retrieval anchor scoring",
    "packet planner token budget",
    "blast radius traversal",
    "source snippets line metadata",
)


def timed_search(graph, query: str, mode: str) -> tuple[list[str], float]:
    started = time.perf_counter()
    matches = search_nodes(graph, query, limit=10, personalize=True, ppr_mode=mode)
    return [match.node.id for match in matches], (time.perf_counter() - started) * 1000.0


def main() -> None:
    graph = load_any(GRAPH_PATH)
    OUT.mkdir(parents=True, exist_ok=True)
    search_nodes(graph, QUERIES[0], limit=10, personalize=False)

    rows = []
    for query in QUERIES:
        exact, exact_ms = timed_search(graph, query, "exact")
        routed, routed_ms = timed_search(graph, query, "auto")
        overlap = len(set(exact) & set(routed)) / max(1, len(set(exact)))
        rows.append(
            {
                "query": query,
                "exact_top": exact[0] if exact else "",
                "routed_top": routed[0] if routed else "",
                "top1_equal": bool(exact and routed and exact[0] == routed[0]),
                "overlap_at_10": round(overlap, 4),
                "exact_ms": round(exact_ms, 3),
                "routed_ms": round(routed_ms, 3),
            }
        )

    report = {
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "queries": len(rows),
        "top1_agreement": sum(row["top1_equal"] for row in rows) / max(1, len(rows)),
        "mean_overlap_at_10": statistics.mean(row["overlap_at_10"] for row in rows),
        "mean_exact_ms": statistics.mean(row["exact_ms"] for row in rows),
        "mean_routed_ms": statistics.mean(row["routed_ms"] for row in rows),
        "rows": rows,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Local Personalized PageRank",
        "",
        f"- Graph: `{report['graph_nodes']}` nodes / `{report['graph_edges']}` edges",
        f"- Top-1 agreement: `{report['top1_agreement']:.1%}`",
        f"- Mean overlap@10: `{report['mean_overlap_at_10']:.1%}`",
        f"- Mean exact PPR search: `{report['mean_exact_ms']:.3f} ms`",
        f"- Mean confidence-routed search: `{report['mean_routed_ms']:.3f} ms`",
        "",
        "| Query | Top-1 same | Overlap@10 | Exact ms | Routed ms |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['query']} | {row['top1_equal']} | {row['overlap_at_10']:.3f} | "
            f"{row['exact_ms']:.3f} | {row['routed_ms']:.3f} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
