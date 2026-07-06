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

from graphgraph.metrics import summarize_graph  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402
from graphgraph.io import save_graph  # noqa: E402


DEFAULT_PROJECTS = (
    "activation",
    "chess",
    "contextminer",
    "ebaypostingautomation",
    "slotmachine",
    "tuya-ble-scanner",
)

DEFAULT_SKIP_DIRS = (
    ".git",
    ".graphgraph",
    "graphify-out",
    "node_modules",
    "target",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "outputs",
    "models",
)


@dataclass(frozen=True)
class Row:
    project: str
    path: str
    status: str
    nodes: int
    edges: int
    node_kinds: str
    edge_types: str
    error: str = ""


def main() -> None:
    base = Path(os.environ.get("AIPROJECTS_ROOT", Path.home() / "aiprojects"))
    projects = tuple(p.strip() for p in os.environ.get("LOCAL_PROJECTS", ",".join(DEFAULT_PROJECTS)).split(",") if p.strip())
    max_nodes = int(os.environ.get("LOCAL_PROJECT_MAX_NODES", "800"))
    frontend = os.environ.get("LOCAL_PROJECT_FRONTEND", "auto")
    out_dir = ROOT / "benchmarks" / "context_graph" / "out" / "local_projects"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[Row] = []
    for project in projects:
        path = base / project
        if not path.exists():
            rows.append(Row(project, str(path), "missing", 0, 0, "", "", "path does not exist"))
            continue
        try:
            graph = scan_directory(
                path,
                max_nodes=max_nodes,
                skip_dirs=DEFAULT_SKIP_DIRS,
                depth="symbols",
                frontend=frontend,
                docs=True,
            )
            graph_path = out_dir / f"{_safe_name(project)}.json"
            save_graph(graph, graph_path)
            summary = summarize_graph(graph)
            rows.append(Row(
                project=project,
                path=str(path),
                status="ok",
                nodes=summary.nodes,
                edges=summary.edges,
                node_kinds=_top(summary.node_kinds),
                edge_types=_top(summary.edge_types),
            ))
        except Exception as exc:  # pragma: no cover - benchmark diagnostics
            rows.append(Row(project, str(path), "error", 0, 0, "", "", f"{type(exc).__name__}: {exc}"))

    _write_csv(out_dir / "local_project_smoke.csv", rows)
    _write_md(out_dir / "local_project_smoke.md", rows, max_nodes=max_nodes, frontend=frontend)


def _top(items: dict[str, int], limit: int = 8) -> str:
    return " ".join(f"{key}:{value}" for key, value in sorted(items.items(), key=lambda kv: (-kv[1], kv[0]))[:limit])


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _write_csv(path: Path, rows: list[Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Row.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _write_md(path: Path, rows: list[Row], *, max_nodes: int, frontend: str) -> None:
    lines = [
        "# Local Project Smoke Benchmark",
        "",
        f"Frontend: `{frontend}`",
        f"Max nodes: `{max_nodes}`",
        "",
        "| Project | Status | Nodes | Edges | Top Node Kinds | Top Edge Types |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.project} | {row.status} | {row.nodes} | {row.edges} | "
            f"{row.node_kinds or row.error} | {row.edge_types} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
