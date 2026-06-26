from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.eval import EvalTask, evaluate_graph  # noqa: E402


TASKS = ROOT / "benchmarks" / "context_graph" / "data" / "local_project_tasks.json"
GRAPHS = ROOT / "benchmarks" / "context_graph" / "out" / "local_projects"
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "local_projects"
MIN_NODE_RECALL = 0.66


def main() -> None:
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    for project, task_items in data["projects"].items():
        graph_path = GRAPHS / f"{project}.json"
        if not graph_path.exists():
            rows.append({
                "project": project,
                "query": "",
                "query_class": "",
                "node_recall": 0.0,
                "edge_recall": 0.0,
                "returned_nodes": 0,
                "returned_edges": 0,
                "token_estimate": 0,
                "status": "missing_graph",
            })
            continue
        tasks = [
            EvalTask(
                query=str(item["query"]),
                query_class=str(item.get("query_class", "blast_radius")),
                expected_nodes=tuple(str(node) for node in item.get("expected_nodes", [])),
                expected_edges=tuple(tuple(edge) for edge in item.get("expected_edges", [])),
            )
            for item in task_items
        ]
        for result in evaluate_graph(graph_path, tasks, max_nodes=40):
            rows.append({
                "project": project,
                "query": result.query,
                "query_class": result.query_class,
                "node_recall": result.node_recall,
                "edge_recall": result.edge_recall,
                "returned_nodes": result.returned_nodes,
                "returned_edges": result.returned_edges,
                "token_estimate": result.token_estimate,
                "status": "pass" if result.node_recall >= MIN_NODE_RECALL else "fail",
            })

    OUT.mkdir(parents=True, exist_ok=True)
    _write_csv(OUT / "local_project_eval.csv", rows)
    _write_md(OUT / "local_project_eval.md", rows)
    failed = [row for row in rows if row["status"] != "pass"]
    if failed:
        raise SystemExit(f"{len(failed)} local project eval task(s) failed")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = ["project", "query", "query_class", "node_recall", "edge_recall", "returned_nodes", "returned_edges", "token_estimate", "status"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_md(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "# Local Project Eval",
        "",
        f"Minimum node recall: `{MIN_NODE_RECALL}`",
        "",
        "| Project | Query | Class | Node Recall | Nodes | Edges | Tokens | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['project']} | {row['query']} | {row['query_class']} | "
            f"{float(row['node_recall']):.3f} | {row['returned_nodes']} | {row['returned_edges']} | "
            f"{row['token_estimate']} | {row['status']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

