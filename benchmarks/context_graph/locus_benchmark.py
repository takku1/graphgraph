from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from graphgraph.analysis.eval import evaluate_graph, load_eval_tasks
from graphgraph.analysis.metrics import compare_graphs
from graphgraph.io import load_any

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks" / "context_graph"
OUT = BENCH / "out" / "locus"
TASKS = BENCH / "data" / "locus_tasks.json"
DEFAULT_LOCUS = Path(os.environ.get("AIPROJECTS_ROOT", Path.home() / "aiprojects")) / "locus"
MIN_NATIVE_NODE_RECALL = 1.0
MIN_NATIVE_EDGE_RECALL = 1.0
DEFAULT_NATIVE_TOKEN_CEILING = 1300
NATIVE_TOKEN_CEILINGS = {
    "what calls compile_rules_slice": 240,
    "differentiation synthesizer applier derivative rules": 360,
    "symbolic expression visitor condition visitor": 500,
    "matrix transpose orthogonal symmetric square vector rules": 360,
    "locus README installation usage": 240,
}


def main() -> None:
    locus = Path(os.environ.get("LOCUS_REPO", str(DEFAULT_LOCUS)))
    OUT.mkdir(parents=True, exist_ok=True)
    graphs = ensure_graphs(locus)
    tasks = load_eval_tasks(TASKS)

    rows = []
    for name, path in graphs.items():
        if not path.exists():
            continue
        for result in evaluate_graph(path, tasks, max_nodes=40):
            rows.append({
                "graph": name,
                **result.__dict__,
            })

    write_csv(OUT / "locus_eval.csv", rows)
    write_summary(OUT / "locus_summary.md", rows, graphs)
    failures = threshold_failures(rows)

    if "native" in graphs and "graphify" in graphs and graphs["graphify"].exists():
        comparison = compare_graphs(load_any(graphs["native"]), load_any(graphs["graphify"]))
        (OUT / "native_vs_graphify.json").write_text(json.dumps({
            "left": comparison.left.__dict__,
            "right": comparison.right.__dict__,
            "shared_node_paths": comparison.shared_node_paths,
            "shared_edge_keys": comparison.shared_edge_keys,
            "left_only_edge_keys": comparison.left_only_edge_keys,
            "right_only_edge_keys": comparison.right_only_edge_keys,
            "shared_normalized_edges": comparison.shared_normalized_edges,
        }, indent=2), encoding="utf-8")

    if failures and os.environ.get("LOCUS_ENFORCE_THRESHOLDS", "1") != "0":
        raise SystemExit("Locus native thresholds failed:\n" + "\n".join(f"- {failure}" for failure in failures))


def ensure_graphs(locus: Path) -> dict[str, Path]:
    native = OUT / "locus-native.json"
    graphify = OUT / "locus-graphify-import.json"
    source_graphify = locus / "graphify-out" / "graph.json"

    if os.environ.get("LOCUS_REBUILD", "0") == "1" or not native.exists():
        run([
            sys.executable, "-m", "graphgraph", "scan",
            "--directory", str(locus),
            "--depth", "symbols",
            "--frontend", os.environ.get("LOCUS_FRONTEND", "auto"),
            "--docs",
            "--max-nodes", os.environ.get("LOCUS_MAX_NODES", "1200"),
            "--skip-dirs", "graphify-out", ".code-review-graph", "target", "target_new",
            "target_new2", "archive", "spikes", "test-inputs",
            "--output", str(native),
        ])

    if source_graphify.exists() and (os.environ.get("LOCUS_REBUILD", "0") == "1" or not graphify.exists()):
        run([
            sys.executable, "-m", "graphgraph", "ingest",
            "--input", str(source_graphify),
            "--output", str(graphify),
        ])

    return {"native": native, "graphify": graphify}


def run(cmd: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict[str, object]], graphs: dict[str, Path]) -> None:
    lines = ["# Locus Benchmark", ""]
    lines.append("## Graphs")
    lines.append("")
    for name, graph_path in graphs.items():
        if graph_path.exists():
            graph = load_any(graph_path)
            lines.append(f"- `{name}`: {len(graph.nodes):,} nodes, {len(graph.edges):,} edges at `{graph_path}`")
    lines.append("")
    lines.append("## Retrieval Eval")
    lines.append("")
    lines.append("| Graph | Query | Node Recall | Edge Recall | MRR | NDCG@5 | NDCG@10 | Nodes | Edges | Token Estimate |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        lines.append(
            f"| {row['graph']} | {row['query']} | {float(row['node_recall']):.3f} | "
            f"{float(row['edge_recall']):.3f} | {float(row.get('mrr', 0.0)):.3f} | "
            f"{float(row.get('ndcg_at_5', 0.0)):.3f} | {float(row.get('ndcg_at_10', 0.0)):.3f} | "
            f"{row['returned_nodes']} | {row['returned_edges']} | {row['token_estimate']} |"
        )
    failures = threshold_failures(rows)
    lines.append("")
    lines.append("## Native Thresholds")
    lines.append("")
    if failures:
        for failure in failures:
            lines.append(f"- FAIL: {failure}")
    else:
        lines.append("- PASS")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def threshold_failures(rows: list[dict[str, object]]) -> list[str]:
    failures: list[str] = []
    for row in rows:
        if row.get("graph") != "native":
            continue
        query = str(row["query"])
        node_recall = float(row["node_recall"])
        edge_recall = float(row["edge_recall"])
        tokens = int(row["token_estimate"])
        ceiling = NATIVE_TOKEN_CEILINGS.get(query, DEFAULT_NATIVE_TOKEN_CEILING)
        if node_recall < MIN_NATIVE_NODE_RECALL:
            failures.append(f"{query}: node recall {node_recall:.3f} < {MIN_NATIVE_NODE_RECALL:.3f}")
        if edge_recall < MIN_NATIVE_EDGE_RECALL:
            failures.append(f"{query}: edge recall {edge_recall:.3f} < {MIN_NATIVE_EDGE_RECALL:.3f}")
        if tokens > ceiling:
            failures.append(f"{query}: tokens {tokens} > {ceiling}")
    return failures


if __name__ == "__main__":
    main()
