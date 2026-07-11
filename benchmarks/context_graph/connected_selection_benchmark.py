from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from .real_project_answerability_limit import REAL_GRAPHS, make_tasks
except ImportError:
    from real_project_answerability_limit import REAL_GRAPHS, make_tasks  # type: ignore[no-redef]

from graphgraph.io import load_any  # noqa: E402
from graphgraph.planning import compute_subgraph_stats, plan_context  # noqa: E402
from graphgraph.retrieval.selection import (  # noqa: E402
    connected_greedy_context_partition,
    packet_node_costs,
    tree_knapsack_context_partition,
)

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
REPORT_JSON = OUT / "connected_selection.json"
REPORT_MD = OUT / "connected_selection.md"


def main() -> None:
    rows = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        for task in make_tasks(graph):
            plan = plan_context(task.query_class)
            if plan.node_budget is None:
                continue
            candidate_cap = min(len(graph.nodes), max(160, plan.node_budget * 2))
            candidates, edges = graph.expand(
                list(task.starts),
                hops=plan.hops,
                max_nodes=candidate_cap,
                direction=plan.direction,
            )
            if len(candidates) <= plan.node_budget:
                continue
            values = bfs_values(task.starts, candidates, edges)
            stats = compute_subgraph_stats(graph, candidates, edges)
            observed_tokens = stats.estimated_tokens_by_packet[plan.packet]
            token_budget = max(
                plan.node_budget,
                round(observed_tokens * plan.node_budget / len(candidates)),
            )

            started = time.perf_counter()
            dp_nodes = tree_knapsack_context_partition(
                graph,
                task.starts,
                candidates,
                values,
                token_budget,
                edges=edges,
                packet=plan.packet,
                max_nodes=plan.node_budget,
                include_orphans=False,
            )
            dp_ms = (time.perf_counter() - started) * 1_000

            started = time.perf_counter()
            greedy_nodes = connected_greedy_context_partition(
                graph,
                task.starts,
                candidates,
                values,
                token_budget,
                edges=edges,
                packet=plan.packet,
                max_nodes=plan.node_budget,
                include_orphans=False,
            )
            greedy_ms = (time.perf_counter() - started) * 1_000

            costs = packet_node_costs(
                graph,
                candidates,
                edges,
                packet=plan.packet,
                token_budget=token_budget,
                max_nodes=plan.node_budget,
            )
            dp_value = sum(values.get(node_id, 0.0) for node_id in dp_nodes)
            greedy_value = sum(values.get(node_id, 0.0) for node_id in greedy_nodes)
            rows.append(
                {
                    "project": graph_path.stem,
                    "query_class": task.query_class,
                    "candidates": len(candidates),
                    "token_budget": token_budget,
                    "dp_nodes": len(dp_nodes),
                    "greedy_nodes": len(greedy_nodes),
                    "dp_value": dp_value,
                    "greedy_value": greedy_value,
                    "utility_ratio": greedy_value / dp_value if dp_value else 1.0,
                    "dp_cost": sum(costs[node_id] for node_id in dp_nodes),
                    "greedy_cost": sum(costs[node_id] for node_id in greedy_nodes),
                    "dp_ms": dp_ms,
                    "greedy_ms": greedy_ms,
                    "dp_connected": connected(task.starts, dp_nodes, edges),
                    "greedy_connected": connected(task.starts, greedy_nodes, edges),
                }
            )

    report = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def bfs_values(starts, candidates, edges) -> dict[str, float]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
        adjacency.setdefault(edge.target, []).append(edge.source)
    values = {start: 1.0 for start in starts if start in candidates}
    queue = deque(values)
    while queue:
        node_id = queue.popleft()
        for neighbor in adjacency.get(node_id, ()):
            if neighbor not in candidates or neighbor in values:
                continue
            values[neighbor] = values[node_id] * 0.85
            queue.append(neighbor)
    return values


def connected(starts, selected, edges) -> bool:
    if not selected:
        return False
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        if edge.source in selected and edge.target in selected:
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)
    frontier = {start for start in starts if start in selected}
    visited = set(frontier)
    while frontier:
        frontier = {
            neighbor
            for node_id in frontier
            for neighbor in adjacency.get(node_id, ())
            if neighbor not in visited
        }
        visited.update(frontier)
    return visited == selected


def summarize(rows) -> dict[str, object]:
    if not rows:
        return {"cases": 0}
    dp_ms = sum(row["dp_ms"] for row in rows)
    greedy_ms = sum(row["greedy_ms"] for row in rows)
    by_class: dict[str, list] = defaultdict(list)
    for row in rows:
        by_class[row["query_class"]].append(row)
    class_summary = {
        query_class: {
            "cases": len(items),
            "mean_utility_ratio": statistics.mean(item["utility_ratio"] for item in items),
            "minimum_utility_ratio": min(item["utility_ratio"] for item in items),
            "speedup": sum(item["dp_ms"] for item in items) / max(1e-9, sum(item["greedy_ms"] for item in items)),
        }
        for query_class, items in sorted(by_class.items())
    }
    return {
        "cases": len(rows),
        "mean_utility_ratio": statistics.mean(row["utility_ratio"] for row in rows),
        "minimum_utility_ratio": min(row["utility_ratio"] for row in rows),
        "dp_total_ms": dp_ms,
        "greedy_total_ms": greedy_ms,
        "speedup": dp_ms / greedy_ms if greedy_ms else 0.0,
        "dp_connectivity_failures": sum(not row["dp_connected"] for row in rows),
        "greedy_connectivity_failures": sum(not row["greedy_connected"] for row in rows),
        "greedy_budget_violations": sum(row["greedy_cost"] > row["token_budget"] + 1e-9 for row in rows),
        "by_class": class_summary,
        "rows": rows,
    }


def render_markdown(report: dict[str, object]) -> str:
    if not report.get("cases"):
        return "# Connected Selection Benchmark\n\nNo over-budget candidate neighborhoods found.\n"
    lines = [
            "# Connected Selection Benchmark",
            "",
            "Bucketed tree-knapsack DP is compared with a connected greedy",
            "value-per-token frontier on the same real-project neighborhoods.",
            "",
            f"- Cases: `{report['cases']}`",
            f"- Mean greedy/DP utility: `{report['mean_utility_ratio']:.4f}`",
            f"- Minimum greedy/DP utility: `{report['minimum_utility_ratio']:.4f}`",
            f"- DP total: `{report['dp_total_ms']:.3f}ms`",
            f"- Greedy total: `{report['greedy_total_ms']:.3f}ms`",
            f"- Greedy speedup: `{report['speedup']:.2f}x`",
            f"- DP connectivity failures: `{report['dp_connectivity_failures']}`",
            f"- Greedy connectivity failures: `{report['greedy_connectivity_failures']}`",
            f"- Greedy budget violations: `{report['greedy_budget_violations']}`",
            "",
            "| Query class | Cases | Mean utility ratio | Minimum utility ratio | Speedup |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    for query_class, row in report["by_class"].items():
        lines.append(
            f"| {query_class} | {row['cases']} | {row['mean_utility_ratio']:.4f} | "
            f"{row['minimum_utility_ratio']:.4f} | {row['speedup']:.2f}x |"
        )
    lines.extend(
        [
            "",
            "Promotion requires zero connectivity/budget failures and a utility",
            "floor high enough to justify replacing the DP's stronger optimum.",
            "The measured hybrid keeps DP for multi-hop paths and uses greedy",
            "for other classes, where the observed utility floor exceeds 1.0.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
