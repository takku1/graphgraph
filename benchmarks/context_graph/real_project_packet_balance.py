from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graphgraph.core import Edge, Graph  # noqa: E402
from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.io import save_graph  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402
from graphgraph.validate import validate_packet  # noqa: E402
from benchmarks.context_graph.local_corpus import small_medium_paths  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
RESULTS_CSV = OUT / "real_project_packet_balance.csv"
SUMMARY_MD = OUT / "real_project_packet_balance.md"
GRAPHS_DIR = OUT / "graphs"

SKIP_DIRS = (
    ".git",
    ".graphgraph",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "build",
    "dist",
    "graphify-out",
    "benchmarks/context_graph/out",
)

PACKETS = ("gg_max", "semantic_arrow", "sql", "lowlevel", "gg_max_hybrid")
QUERY_HOPS = {
    "direct_lookup": 1,
    "reverse_lookup": 1,
    "negative_query": 1,
    "subsystem_summary": 1,
    "blast_radius": 2,
    "multi_hop_path": 2,
}


@dataclass(frozen=True)
class Task:
    query_class: str
    start: str
    hops: int


def project_paths() -> list[Path]:
    raw = os.environ.get("REAL_PROJECT_PATHS")
    if raw:
        return [Path(item.strip()) for item in raw.split(";") if item.strip()]
    return small_medium_paths()


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

    starts = {
        "direct_lookup": first_with(outgoing),
        "reverse_lookup": first_with(incoming),
        "negative_query": sparse,
        "subsystem_summary": hub,
        "blast_radius": hub,
        "multi_hop_path": first_with(outgoing),
    }
    return [Task(query_class=qc, start=start, hops=QUERY_HOPS[qc]) for qc, start in starts.items()]


def scan_project(path: Path, max_nodes: int, frontend: str) -> Graph:
    return scan_directory(
        path,
        max_nodes=max_nodes,
        skip_dirs=SKIP_DIRS,
        depth="symbols",
        frontend=frontend,
        docs=True,
    )


def run() -> list[dict[str, object]]:
    max_nodes = int(os.environ.get("REAL_PROJECT_MAX_NODES", "600"))
    frontend = os.environ.get("REAL_PROJECT_FRONTEND", "auto")
    rows: list[dict[str, object]] = []
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)

    for path in project_paths():
        project = path.name
        if not path.exists():
            rows.append({"project": project, "path": str(path), "status": "missing", "error": "path does not exist"})
            continue
        try:
            graph = scan_project(path, max_nodes=max_nodes, frontend=frontend)
            save_graph(graph, GRAPHS_DIR / f"{safe_name(project)}.json")
        except Exception as exc:  # pragma: no cover - benchmark diagnostics
            rows.append({"project": project, "path": str(path), "status": "scan_error", "error": f"{type(exc).__name__}: {exc}"})
            continue

        tasks = make_tasks(graph)
        for task in tasks:
            nodes, edges = graph.expand([task.start], hops=task.hops, max_nodes=80)
            for packet in PACKETS:
                try:
                    rendered = render_packet(graph, nodes, edges, packet)
                    validation = validate_packet(rendered)
                    status = "ok" if validation.ok else "validate_fail"
                    error = "; ".join(validation.errors)
                    tokens = estimate_tokens(rendered)
                except Exception as exc:  # pragma: no cover - benchmark diagnostics
                    status = "render_error"
                    error = f"{type(exc).__name__}: {exc}"
                    tokens = 0
                rows.append(
                    {
                        "project": project,
                        "path": str(path),
                        "status": status,
                        "error": error,
                        "query_class": task.query_class,
                        "start": task.start,
                        "hops": task.hops,
                        "packet": packet,
                        "nodes": len(nodes),
                        "edges": len(edges),
                        "tokens": tokens,
                        "tokens_per_node_edge": round(tokens / max(1, len(nodes) + len(edges)), 4),
                    }
                )
    return rows


def write(rows: list[dict[str, object]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "project", "path", "status", "error", "query_class", "start", "hops",
        "packet", "nodes", "edges", "tokens", "tokens_per_node_edge",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    ok_rows = [row for row in rows if row.get("status") == "ok"]
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in ok_rows:
        key = (str(row["project"]), str(row["query_class"]), str(row["packet"]))
        grouped.setdefault(key, []).append(row)

    summary_rows = []
    for (project, query_class, packet), items in grouped.items():
        summary_rows.append(
            {
                "project": project,
                "query_class": query_class,
                "packet": packet,
                "avg_tokens": avg(items, "tokens"),
                "avg_edges": avg(items, "edges"),
                "avg_tokens_per_node_edge": avg(items, "tokens_per_node_edge"),
            }
        )

    winner_rows = []
    for project in sorted({row["project"] for row in summary_rows}):
        for query_class in sorted({row["query_class"] for row in summary_rows if row["project"] == project}):
            candidates = [row for row in summary_rows if row["project"] == project and row["query_class"] == query_class]
            winner_rows.append(min(candidates, key=lambda row: (float(row["avg_tokens"]), str(row["packet"]))))
    structural_exceptions = [
        row for row in winner_rows
        if row["packet"] not in {"gg_max", "semantic_arrow"} and float(row["avg_edges"]) > 0.0
    ]
    semantic_edge_wins = [
        row for row in winner_rows
        if row["packet"] == "semantic_arrow" and float(row["avg_edges"]) > 0.0
    ]

    by_packet: dict[str, list[dict[str, object]]] = {}
    for row in summary_rows:
        by_packet.setdefault(str(row["packet"]), []).append(row)

    threshold_rows = threshold_policy_rows(summary_rows)
    best_threshold = min(threshold_rows, key=lambda row: (float(row["avg_tokens"]), int(row["edge_threshold"]))) if threshold_rows else None

    lines = [
        "# Real Project Packet Balance",
        "",
        "This benchmark scans bounded slices of real local projects and cloned repositories, then renders identical retrieved subgraphs with each packet format.",
        "",
        "It measures the packet-format floor only. Retrieval quality and live model comprehension are separate gates.",
        "",
        "## Packet Averages",
        "",
        "| Packet | Avg tokens | Avg edges | Avg tokens/(nodes+edges) | Cases |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for packet, items in sorted(by_packet.items(), key=lambda kv: avg(kv[1], "tokens")):
        lines.append(
            f"| {packet} | {avg(items, 'avg_tokens'):.1f} | {avg(items, 'avg_edges'):.1f} | "
            f"{avg(items, 'avg_tokens_per_node_edge'):.3f} | {len(items)} |"
        )

    lines.extend([
        "",
        "## Per-Query Winners",
        "",
        "| Project | Query class | Winner | Avg tokens | Avg edges | Tokens/(nodes+edges) |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ])
    for row in winner_rows:
        lines.append(
            f"| {row['project']} | {row['query_class']} | {row['packet']} | "
            f"{float(row['avg_tokens']):.1f} | {float(row['avg_edges']):.1f} | "
            f"{float(row['avg_tokens_per_node_edge']):.3f} |"
        )

    lines.extend([
        "",
        "## Real-Project Edge Threshold Check",
        "",
        "Policy tested: use `semantic_arrow` when `edges <= T`, otherwise `gg_max`.",
        "",
    ])
    if best_threshold:
        lines.extend([
            f"- Best threshold: `T={best_threshold['edge_threshold']}`",
            f"- Avg tokens: `{float(best_threshold['avg_tokens']):.1f}`",
            f"- Token premium vs all-`gg_max`: `{float(best_threshold['premium_vs_all_gg_max_pct']):.3f}%`",
            "",
        ])
    lines.extend([
        "| Threshold | Avg tokens | Premium vs all-gg_max | Semantic choices | gg_max choices |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in threshold_rows[:10]:
        lines.append(
            f"| {row['edge_threshold']} | {float(row['avg_tokens']):.1f} | "
            f"{float(row['premium_vs_all_gg_max_pct']):.3f}% | "
            f"{row['semantic_choices']} | {row['gg_max_choices']} |"
        )

    failures = [row for row in rows if row.get("status") not in {"ok"}]
    if failures:
        lines.extend([
            "",
            "## Failures",
            "",
            "| Project | Status | Error |",
            "| --- | --- | --- |",
        ])
        for row in failures[:20]:
            lines.append(f"| {row.get('project', '')} | {row.get('status', '')} | {row.get('error', '')} |")

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- The lowest-token winner here is the current real-project packet floor for identical graph evidence.",
    ])
    if structural_exceptions:
        exception_text = ", ".join(
            f"{row['project']}/{row['query_class']} -> `{row['packet']}`"
            for row in structural_exceptions[:12]
        )
        suffix = "" if len(structural_exceptions) <= 12 else f", plus {len(structural_exceptions) - 12} more"
        lines.append(
            "- `gg_max` is the broad structural floor on this run, but non-`gg_max` structural winners exist: "
            f"{exception_text}{suffix}."
        )
    else:
        lines.append("- On this bounded real-project run, `gg_max` dominates every non-empty structural packet.")
    if semantic_edge_wins:
        edge_text = ", ".join(
            f"{row['project']}/{row['query_class']} edges={float(row['avg_edges']):.1f}"
            for row in semantic_edge_wins[:12]
        )
        suffix = "" if len(semantic_edge_wins) <= 12 else f", plus {len(semantic_edge_wins) - 12} more"
        lines.append(f"- `semantic_arrow` also wins some non-empty low-edge packets: {edge_text}{suffix}.")
    else:
        lines.append("- `semantic_arrow` only wins empty or near-empty packets where its compact header matters.")
    lines.extend([
        "- Treat `semantic_arrow` for empty/low-edge packets and `gg_max` for most structural packets as the default candidate policy; inspect listed exceptions before hard-coding a universal rule.",
        "- Live-model comprehension remains a separate fallback gate, not part of this local packet floor measurement.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


def threshold_policy_rows(summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    cases: dict[tuple[str, str], dict[str, dict[str, object]]] = {}
    for row in summary_rows:
        key = (str(row["project"]), str(row["query_class"]))
        cases.setdefault(key, {})[str(row["packet"])] = row

    all_gg = [packets["gg_max"] for packets in cases.values() if "gg_max" in packets]
    all_gg_avg = avg(all_gg, "avg_tokens")
    rows = []
    for threshold in range(0, 11):
        selected = []
        semantic_choices = 0
        gg_choices = 0
        for packets in cases.values():
            if "gg_max" not in packets or "semantic_arrow" not in packets:
                continue
            gg_row = packets["gg_max"]
            semantic_row = packets["semantic_arrow"]
            if float(gg_row["avg_edges"]) <= threshold:
                selected.append(semantic_row)
                semantic_choices += 1
            else:
                selected.append(gg_row)
                gg_choices += 1
        selected_avg = avg(selected, "avg_tokens")
        rows.append(
            {
                "edge_threshold": threshold,
                "avg_tokens": selected_avg,
                "premium_vs_all_gg_max_pct": ((selected_avg / all_gg_avg) - 1.0) * 100.0 if all_gg_avg else 0.0,
                "semantic_choices": semantic_choices,
                "gg_max_choices": gg_choices,
            }
        )
    return rows


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def main() -> None:
    rows = run()
    if not rows:
        raise SystemExit("No rows generated.")
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
