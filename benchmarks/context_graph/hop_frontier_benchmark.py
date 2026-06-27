from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out"
REAL_GRAPHS = OUT / "real_projects" / "graphs"
RESULTS_CSV = OUT / "real_projects" / "hop_frontier.csv"
SUMMARY_MD = OUT / "real_projects" / "hop_frontier.md"

MAX_HOPS = 5
MAX_NODES = 160
PACKET = "gg_max"
MIN_MARGINAL_EDGES_PER_100_TOKENS = 1.0


def run() -> list[dict[str, object]]:
    if not REAL_GRAPHS.exists():
        return []

    rows: list[dict[str, object]] = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        active_nodes = [nid for nid, node in graph.nodes.items() if node.active]
        if not active_nodes:
            continue
        degree = graph.degree()
        starts = {
            "hub": max(active_nodes, key=lambda nid: degree.get(nid, 0)),
            "leaf": min(active_nodes, key=lambda nid: degree.get(nid, 0)),
        }
        for start_kind, start in starts.items():
            prior_nodes = 0
            prior_edges = 0
            prior_tokens = 0
            for hops in range(0, MAX_HOPS + 1):
                nodes, edges = graph.expand([start], hops=hops, max_nodes=MAX_NODES)
                packet = render_packet(graph, nodes, edges, PACKET)
                tokens = estimate_tokens(packet)
                new_nodes = len(nodes) - prior_nodes
                new_edges = len(edges) - prior_edges
                new_tokens = tokens - prior_tokens
                marginal_edges_per_100_tokens = (new_edges / new_tokens * 100.0) if new_tokens > 0 else 0.0
                rows.append(
                    {
                        "project": graph_path.stem,
                        "start_kind": start_kind,
                        "start": start,
                        "hops": hops,
                        "nodes": len(nodes),
                        "edges": len(edges),
                        "tokens": tokens,
                        "new_nodes": new_nodes,
                        "new_edges": new_edges,
                        "new_tokens": new_tokens,
                        "marginal_edges_per_100_tokens": round(marginal_edges_per_100_tokens, 4),
                        "tokens_per_edge": round(tokens / max(1, len(edges)), 4),
                        "tokens_per_node_edge": round(tokens / max(1, len(nodes) + len(edges)), 4),
                    }
                )
                prior_nodes = len(nodes)
                prior_edges = len(edges)
                prior_tokens = tokens
    return rows


def write(rows: list[dict[str, object]]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "project",
        "start_kind",
        "start",
        "hops",
        "nodes",
        "edges",
        "tokens",
        "new_nodes",
        "new_edges",
        "new_tokens",
        "marginal_edges_per_100_tokens",
        "tokens_per_edge",
        "tokens_per_node_edge",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    by_hop: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        by_hop.setdefault(int(row["hops"]), []).append(row)

    knees = knee_rows(rows)
    lines = [
        "# Hop Frontier Benchmark",
        "",
        f"Packet: `{PACKET}`",
        f"Max nodes per expansion: `{MAX_NODES}`",
        "",
        "This measures nth-hop expansion on saved real-project graphs. It does not claim answer recall; it measures the topology/token frontier.",
        "",
        "## Hop Averages",
        "",
        "| Hops | Avg nodes | Avg edges | Avg tokens | New edges | New tokens | Marginal edges / 100 tokens | Tokens / (nodes+edges) |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for hops, items in sorted(by_hop.items()):
        lines.append(
            f"| {hops} | {avg(items, 'nodes'):.1f} | {avg(items, 'edges'):.1f} | "
            f"{avg(items, 'tokens'):.1f} | {avg(items, 'new_edges'):.1f} | "
            f"{avg(items, 'new_tokens'):.1f} | {avg(items, 'marginal_edges_per_100_tokens'):.3f} | "
            f"{avg(items, 'tokens_per_node_edge'):.3f} |"
        )

    lines.extend([
        "",
        "## Suggested Hop Knees",
        "",
        f"Knee rule: first hop where marginal edges per 100 tokens falls below `{MIN_MARGINAL_EDGES_PER_100_TOKENS}`.",
        "",
        "| Project | Start kind | Suggested max hop | Reason |",
        "| --- | --- | ---: | --- |",
    ])
    for row in knees:
        lines.append(f"| {row['project']} | {row['start_kind']} | {row['suggested_hop']} | {row['reason']} |")

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- Hop depth should be an activation cutoff, not a constant.",
        "- Current real-project slices usually hit the node budget by hop 2 or 3 from hubs; later hops mostly increase tokens by saturating the packet.",
        "- Leaf starts often need 1 extra hop before useful structure appears.",
        "- The next production step is a traversal planner that expands until marginal activation or marginal edge gain falls below token cost.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def knee_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((str(row["project"]), str(row["start_kind"])), []).append(row)

    out = []
    for (project, start_kind), items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda row: int(row["hops"]))
        suggested = int(ordered[-1]["hops"])
        reason = "kept gaining structure through max hop"
        for row in ordered[1:]:
            if float(row["marginal_edges_per_100_tokens"]) < MIN_MARGINAL_EDGES_PER_100_TOKENS:
                suggested = max(0, int(row["hops"]) - 1)
                reason = (
                    f"hop {row['hops']} marginal edge gain "
                    f"{float(row['marginal_edges_per_100_tokens']):.3f}/100 tokens"
                )
                break
        out.append(
            {
                "project": project,
                "start_kind": start_kind,
                "suggested_hop": suggested,
                "reason": reason,
            }
        )
    return out


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


def main() -> None:
    rows = run()
    if not rows:
        RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_CSV.write_text("", encoding="utf-8")
        SUMMARY_MD.write_text(
            "# Hop Frontier Benchmark\n\n"
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
