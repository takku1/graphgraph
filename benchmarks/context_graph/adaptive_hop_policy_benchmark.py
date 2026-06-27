from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.core import Edge, Graph  # noqa: E402
from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out"
REAL_GRAPHS = OUT / "real_projects" / "graphs"
RESULTS_CSV = OUT / "real_projects" / "adaptive_hop_policy.csv"
SUMMARY_MD = OUT / "real_projects" / "adaptive_hop_policy.md"

MAX_HOPS = 5
MAX_NODES = 160
PACKET = "gg_max"
THRESHOLDS = (0.5, 1.0, 2.0, 5.0, 10.0)
FIXED_HOPS = {
    "direct_lookup": 1,
    "reverse_lookup": 1,
    "negative_query": 0,
    "subsystem_summary": 1,
    "blast_radius": 2,
    "multi_hop_path": 2,
}


@dataclass(frozen=True)
class Task:
    query_class: str
    start: str


def make_tasks(graph: Graph) -> list[Task]:
    active_nodes = [nid for nid, node in graph.nodes.items() if node.active]
    if not active_nodes:
        return []
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    degree = graph.degree()

    def first_with(index: dict[str, list[Edge]]) -> str:
        return max((nid for nid in active_nodes if index.get(nid)), key=lambda nid: len(index.get(nid, ())), default=active_nodes[0])

    hub = max(active_nodes, key=lambda nid: degree.get(nid, 0))
    sparse = min(active_nodes, key=lambda nid: degree.get(nid, 0))
    return [
        Task("direct_lookup", first_with(outgoing)),
        Task("reverse_lookup", first_with(incoming)),
        Task("negative_query", sparse),
        Task("subsystem_summary", hub),
        Task("blast_radius", hub),
        Task("multi_hop_path", first_with(outgoing)),
    ]


def expand_stats(graph: Graph, start: str, hops: int) -> dict[str, float]:
    nodes, edges = graph.expand([start], hops=hops, max_nodes=MAX_NODES)
    packet = render_packet(graph, nodes, edges, PACKET)
    return {
        "nodes": float(len(nodes)),
        "edges": float(len(edges)),
        "tokens": float(estimate_tokens(packet)),
    }


def choose_adaptive_hop(graph: Graph, task: Task, threshold: float, max_hops: int = MAX_HOPS) -> tuple[int, str]:
    if task.query_class == "negative_query":
        return 0, "negative_query stays at anchor-only evidence"

    previous = expand_stats(graph, task.start, 0)
    selected = 0
    for hops in range(1, max_hops + 1):
        current = expand_stats(graph, task.start, hops)
        new_edges = current["edges"] - previous["edges"]
        new_tokens = current["tokens"] - previous["tokens"]
        marginal = (new_edges / new_tokens * 100.0) if new_tokens > 0 else 0.0
        if marginal < threshold:
            return selected, f"hop {hops} marginal {marginal:.3f} edges/100 tokens < {threshold:g}"
        selected = hops
        previous = current
        if current["nodes"] >= MAX_NODES:
            return selected, "node budget saturated"
    return selected, f"kept gaining through max hop {max_hops}"


def run() -> list[dict[str, object]]:
    if not REAL_GRAPHS.exists():
        return []

    rows: list[dict[str, object]] = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        for task in make_tasks(graph):
            fixed_hops = FIXED_HOPS[task.query_class]
            fixed = expand_stats(graph, task.start, fixed_hops)
            for threshold in THRESHOLDS:
                for policy, max_hops in (("uncapped", MAX_HOPS), ("capped_to_fixed", fixed_hops)):
                    selected_hops, reason = choose_adaptive_hop(graph, task, threshold, max_hops=max_hops)
                    adaptive = expand_stats(graph, task.start, selected_hops)
                    rows.append(
                        {
                            "project": graph_path.stem,
                            "query_class": task.query_class,
                            "start": task.start,
                            "policy": policy,
                            "threshold": threshold,
                            "fixed_hops": fixed_hops,
                            "adaptive_hops": selected_hops,
                            "fixed_nodes": int(fixed["nodes"]),
                            "adaptive_nodes": int(adaptive["nodes"]),
                            "fixed_edges": int(fixed["edges"]),
                            "adaptive_edges": int(adaptive["edges"]),
                            "fixed_tokens": int(fixed["tokens"]),
                            "adaptive_tokens": int(adaptive["tokens"]),
                            "token_delta": int(adaptive["tokens"] - fixed["tokens"]),
                            "edge_delta": int(adaptive["edges"] - fixed["edges"]),
                            "node_delta": int(adaptive["nodes"] - fixed["nodes"]),
                            "reason": reason,
                        }
                    )
    return rows


def write(rows: list[dict[str, object]]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "project",
        "query_class",
        "start",
        "policy",
        "threshold",
        "fixed_hops",
        "adaptive_hops",
        "fixed_nodes",
        "adaptive_nodes",
        "fixed_edges",
        "adaptive_edges",
        "fixed_tokens",
        "adaptive_tokens",
        "token_delta",
        "edge_delta",
        "node_delta",
        "reason",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    by_policy_threshold: dict[tuple[str, float], list[dict[str, object]]] = {}
    for row in rows:
        by_policy_threshold.setdefault((str(row["policy"]), float(row["threshold"])), []).append(row)

    lines = [
        "# Adaptive Hop Policy Benchmark",
        "",
        f"Packet: `{PACKET}`",
        f"Max nodes per expansion: `{MAX_NODES}`",
        "",
        "This compares fixed query-class hop defaults against marginal-gain policies on saved real-project graphs.",
        "",
        "Adaptive rule: keep the next hop only when new edges per 100 new tokens stays above the threshold.",
        "",
        "Policies: `uncapped` may walk up to the benchmark max; `capped_to_fixed` can only stop early inside the current query-class hop budget.",
        "",
        "## Threshold Summary",
        "",
        "| Policy | Threshold | Avg fixed hops | Avg adaptive hops | Avg fixed tokens | Avg adaptive tokens | Token delta | Edge delta | Node delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (policy, threshold), items in sorted(by_policy_threshold.items()):
        lines.append(
            f"| {policy} | {threshold:g} | {avg(items, 'fixed_hops'):.2f} | {avg(items, 'adaptive_hops'):.2f} | "
            f"{avg(items, 'fixed_tokens'):.1f} | {avg(items, 'adaptive_tokens'):.1f} | "
            f"{avg(items, 'token_delta'):.1f} | {avg(items, 'edge_delta'):.1f} | {avg(items, 'node_delta'):.1f} |"
        )

    lines.extend([
        "",
        "## Query-Class Detail At Threshold 1.0",
        "",
        "| Policy | Query class | Avg fixed hops | Avg adaptive hops | Token delta | Edge delta | Node delta |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    threshold_one = [row for row in rows if float(row["threshold"]) == 1.0]
    by_query: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in threshold_one:
        by_query.setdefault((str(row["policy"]), str(row["query_class"])), []).append(row)
    for (policy, query_class), items in sorted(by_query.items()):
        lines.append(
            f"| {policy} | {query_class} | {avg(items, 'fixed_hops'):.2f} | {avg(items, 'adaptive_hops'):.2f} | "
            f"{avg(items, 'token_delta'):.1f} | {avg(items, 'edge_delta'):.1f} | {avg(items, 'node_delta'):.1f} |"
        )

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- Uncapped activation is allowed to prove whether nth-hop expansion is worth considering; if it grows tokens without labels, it is not a production default.",
        "- Capped activation is the safer candidate: it can only stop early inside existing query-class budgets.",
        "- A capped threshold that collapses blast/path below fixed 2-hop is too aggressive unless live answer scoring proves recall is preserved.",
        "- This benchmark measures topology/token tradeoff only; answer recall still requires task labels or live scoring.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


def main() -> None:
    rows = run()
    if not rows:
        RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_CSV.write_text("", encoding="utf-8")
        SUMMARY_MD.write_text(
            "# Adaptive Hop Policy Benchmark\n\n"
            "Skipped: no saved real-project graph files were found. "
            "Run `real_project_packet_balance.py` first.\n",
            encoding="utf-8",
        )
        print(SUMMARY_MD.read_text(encoding="utf-8"))
        return
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
