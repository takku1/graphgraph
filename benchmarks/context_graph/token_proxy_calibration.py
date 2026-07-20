from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.analysis.eval import estimate_tokens  # noqa: E402
from graphgraph.graph.core import Edge, Graph  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import compute_subgraph_stats  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out"
REAL_GRAPHS = OUT / "real_projects" / "graphs"
RESULTS_CSV = OUT / "real_projects" / "token_proxy_calibration.csv"
SUMMARY_MD = OUT / "real_projects" / "token_proxy_calibration.md"

PACKETS = ("gg_max", "semantic_arrow", "sql", "lowlevel", "gg_max_hybrid")
HOPS = (0, 1, 2)
MAX_NODES = 120


@dataclass(frozen=True)
class Start:
    kind: str
    node_ids: tuple[str, ...]


def make_starts(graph: Graph) -> list[Start]:
    active_nodes = [nid for nid, node in graph.nodes.items() if node.active]
    if not active_nodes:
        return []
    degree = graph.degree()
    outgoing = graph.outgoing()
    incoming = graph.incoming()

    def first_with(index: dict[str, list[Edge]]) -> str:
        return max((nid for nid in active_nodes if index.get(nid)), key=lambda nid: len(index.get(nid, ())), default=active_nodes[0])

    sparse_nodes = sorted(active_nodes, key=lambda nid: (degree.get(nid, 0), nid))[:3]
    hub_nodes = sorted(active_nodes, key=lambda nid: (-degree.get(nid, 0), nid))[:3]
    return [
        Start("hub", (max(active_nodes, key=lambda nid: degree.get(nid, 0)),)),
        Start("leaf", (min(active_nodes, key=lambda nid: degree.get(nid, 0)),)),
        Start("outgoing", (first_with(outgoing),)),
        Start("incoming", (first_with(incoming),)),
        Start("leaf_bundle", tuple(sparse_nodes)),
        Start("hub_bundle", tuple(hub_nodes)),
    ]


def run() -> list[dict[str, object]]:
    if not REAL_GRAPHS.exists():
        return []

    rows: list[dict[str, object]] = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        for start in make_starts(graph):
            for hops in HOPS:
                nodes, edges = graph.expand(list(start.node_ids), hops=hops, max_nodes=MAX_NODES)
                stats = compute_subgraph_stats(graph, nodes, edges)
                actual_by_packet: dict[str, int] = {}
                proxy_by_packet: dict[str, int] = {}
                for packet in PACKETS:
                    rendered = render_packet(graph, nodes, edges, packet)
                    actual_by_packet[packet] = estimate_tokens(rendered)
                    proxy_by_packet[packet] = stats.estimated_tokens_by_packet[packet]

                actual_winner = min(PACKETS, key=lambda packet: (actual_by_packet[packet], packet))
                proxy_winner = min(PACKETS, key=lambda packet: (proxy_by_packet[packet], packet))
                actual_semantic_beats_gg = actual_by_packet["semantic_arrow"] <= actual_by_packet["gg_max"]
                proxy_semantic_beats_gg = proxy_by_packet["semantic_arrow"] <= proxy_by_packet["gg_max"]

                for packet in PACKETS:
                    actual = actual_by_packet[packet]
                    proxy = proxy_by_packet[packet]
                    rows.append(
                        {
                            "project": graph_path.stem,
                            "start_kind": start.kind,
                            "start": ";".join(start.node_ids),
                            "hops": hops,
                            "nodes": len(nodes),
                            "edges": len(edges),
                            "packet": packet,
                            "actual_tokens": actual,
                            "proxy_tokens": proxy,
                            "absolute_error": proxy - actual,
                            "relative_error_pct": ((proxy / actual) - 1.0) * 100.0 if actual else 0.0,
                            "actual_winner": actual_winner,
                            "proxy_winner": proxy_winner,
                            "winner_match": actual_winner == proxy_winner,
                            "semantic_vs_gg_match": actual_semantic_beats_gg == proxy_semantic_beats_gg,
                            "actual_semantic_beats_gg": actual_semantic_beats_gg,
                            "proxy_semantic_beats_gg": proxy_semantic_beats_gg,
                        }
                    )
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
        "packet",
        "actual_tokens",
        "proxy_tokens",
        "absolute_error",
        "relative_error_pct",
        "actual_winner",
        "proxy_winner",
        "winner_match",
        "semantic_vs_gg_match",
        "actual_semantic_beats_gg",
        "proxy_semantic_beats_gg",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    grouped_cases = case_rows(rows)
    winner_matches = sum(1 for row in grouped_cases if row["winner_match"])
    semantic_matches = sum(1 for row in grouped_cases if row["semantic_vs_gg_match"])

    lines = [
        "# Token Proxy Calibration",
        "",
        "This checks whether planner token proxies preserve packet decisions against actual rendered packet token estimates.",
        "",
        f"Cases: `{len(grouped_cases)}` subgraphs, `{len(rows)}` packet rows",
        f"Packet winner rank agreement: `{winner_matches}/{len(grouped_cases)}` (`{pct(winner_matches, len(grouped_cases)):.1f}%`)",
        f"`semantic_arrow` vs `gg_max` decision agreement: `{semantic_matches}/{len(grouped_cases)}` (`{pct(semantic_matches, len(grouped_cases)):.1f}%`)",
        "",
        "## Error By Packet",
        "",
        "| Packet | Avg actual tokens | Avg proxy tokens | Avg error | Avg relative error | Cases |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for packet, items in sorted(group_by(rows, "packet").items()):
        lines.append(
            f"| {packet} | {avg(items, 'actual_tokens'):.1f} | {avg(items, 'proxy_tokens'):.1f} | "
            f"{avg(items, 'absolute_error'):.1f} | {avg(items, 'relative_error_pct'):.1f}% | {len(items)} |"
        )

    disagreements = [row for row in grouped_cases if not row["semantic_vs_gg_match"]]
    if disagreements:
        lines.extend([
            "",
            "## Semantic/GG Disagreements",
            "",
            "| Project | Start kind | Hops | Nodes | Edges | Actual winner | Proxy winner | Actual semantic<=gg | Proxy semantic<=gg |",
            "| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
        ])
        for row in disagreements[:20]:
            lines.append(
                f"| {row['project']} | {row['start_kind']} | {row['hops']} | {row['nodes']} | {row['edges']} | "
                f"{row['actual_winner']} | {row['proxy_winner']} | {row['actual_semantic_beats_gg']} | {row['proxy_semantic_beats_gg']} |"
            )

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- Exact proxy magnitude is less important than preserving packet rank decisions.",
        "- Runtime packet refinement currently relies only on the `semantic_arrow` versus `gg_max` zero-edge decision.",
        "- If zero-edge semantic/GG agreement falls below 100%, packet refinement should use a safer rule than proxy comparison.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def case_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: dict[tuple[str, str, str, int], dict[str, object]] = {}
    for row in rows:
        key = (str(row["project"]), str(row["start_kind"]), str(row["start"]), int(row["hops"]))
        seen.setdefault(key, row)
    return list(seen.values())


def group_by(rows: list[dict[str, object]], key: str) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row[key]), []).append(row)
    return grouped


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows]
    return sum(values) / max(1, len(values))


def pct(numerator: int, denominator: int) -> float:
    return numerator / max(1, denominator) * 100.0


def main() -> None:
    rows = run()
    if not rows:
        RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_CSV.write_text("", encoding="utf-8")
        SUMMARY_MD.write_text(
            "# Token Proxy Calibration\n\n"
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
