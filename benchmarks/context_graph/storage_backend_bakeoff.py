"""Real-repo storage backend bake-off: JSON baseline vs native .gg.

Scans each project in `local_corpus.py` exactly once, then for every
candidate storage format: saves it (recording file size + save time), loads
it cold from disk (recording load time), and runs a small representative
query set against the loaded graph (recording per-query latency). This is
the empirical counterpart to the synthetic comparison in
`protocol_benchmark.py` / `storage_design_research.md` -- it answers the
question "which format actually wins on real code", not a synthetic corpus.

Usage:
    python benchmarks/context_graph/storage_backend_bakeoff.py
    BAKEOFF_TIER=small_medium python benchmarks/context_graph/storage_backend_bakeoff.py
    BAKEOFF_PROJECTS=flask;requests python benchmarks/context_graph/storage_backend_bakeoff.py
    BAKEOFF_FORCE=1 BAKEOFF_PROJECTS=flask python benchmarks/context_graph/storage_backend_bakeoff.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BENCH_DIR = Path(__file__).resolve().parent
for p in (SRC, BENCH_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from graphgraph.core import Graph  # noqa: E402
from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.io import load_any, save_graph  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph  # noqa: E402
from graphgraph.retrieval import retrieve_context  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402

import cross_repo_anchor_stress as cras  # noqa: E402 - reuse task generation, not duplicate it
import local_corpus  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "storage_bakeoff"
GRAPHS = OUT / "graphs"
RESULTS_CSV = OUT / "storage_backend_bakeoff.csv"
SUMMARY_MD = OUT / "storage_backend_bakeoff.md"

FORMATS = (".json", ".gg")

SKIP_DIRS = (
    ".git", ".graphgraph", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pycache__", ".venv", "venv", "node_modules", "target", "build", "dist",
    "graphify-out", "benchmarks/context_graph/out", ".lake",
)

SMALL_MEDIUM_MAX_NODES = int(os.environ.get("BAKEOFF_SMALL_MEDIUM_MAX_NODES", "3000"))
LARGE_MAX_NODES = int(os.environ.get("BAKEOFF_LARGE_MAX_NODES", str(local_corpus.DEFAULT_LARGE_TIER_MAX_NODES)))
QUERY_ROUNDS_COLD = 1
QUERY_ROUNDS_CACHED = 3
MAX_TASKS_PER_PROJECT = 5
FIELDS = [
    "project", "tier", "format", "status", "error", "source_nodes", "source_edges", "scan_ms",
    "file_bytes", "save_ms", "load_ms", "cold_query_round_ms", "cached_query_ms_per_query",
    "tokens_last_round", "loaded_nodes", "loaded_edges",
    "node_fidelity", "edge_fidelity", "metadata_fidelity", "full_fidelity",
]


def corpus() -> list[tuple[Path, str]]:
    only_tier = os.environ.get("BAKEOFF_TIER")
    only_projects = os.environ.get("BAKEOFF_PROJECTS")
    tiered = local_corpus.all_tiered_paths()
    if only_projects:
        wanted = {name.strip() for name in only_projects.split(";") if name.strip()}
        tiered = [(p, tier) for p, tier in tiered if p.name in wanted]
        present = {p.name for p, _tier in tiered}
        for name in sorted(wanted - present):
            for root, tier in (
                (local_corpus.AIPROJECTS_ROOT, "small_medium"),
                (local_corpus.RESOURCES_ROOT, "small_medium"),
            ):
                path = root / name
                if path.exists():
                    tiered.append((path, tier))
                    break
    if only_tier:
        tiered = [(p, tier) for p, tier in tiered if tier == only_tier]
    return tiered


def scan_project(path: Path, tier: str) -> Graph:
    max_nodes = LARGE_MAX_NODES if tier == "large" else SMALL_MEDIUM_MAX_NODES
    return scan_directory(path, max_nodes=max_nodes, skip_dirs=SKIP_DIRS, depth="symbols", frontend="auto", docs=True)


def make_query_tasks(graph: Graph) -> list[cras.Task]:
    return cras.make_tasks(graph)[:MAX_TASKS_PER_PROJECT]


def time_queries(graph: Graph, tasks: list[cras.Task], *, rounds: int) -> tuple[float, int]:
    """Return (total_seconds, tokens_of_last_round) running the task set `rounds` times."""
    total = 0.0
    tokens = 0
    for _ in range(rounds):
        start = time.perf_counter()
        tokens = 0
        for task in tasks:
            plan = plan_context(task.query_class, task.query)
            result = retrieve_context(graph, task.query, task.query_class, hops=plan.hops, max_nodes=plan.node_budget)
            plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, result.nodes, result.edges))
            packet = render_packet(graph, result.nodes, result.edges, plan.packet)
            tokens += estimate_tokens(packet)
        total += time.perf_counter() - start
    return total, tokens


def bench_format(graph: Graph, canonical: Graph, tasks: list[cras.Task], project_name: str, fmt: str) -> dict[str, object]:
    path = GRAPHS / f"{safe_name(project_name)}{fmt}"
    if path.exists():
        path.unlink()

    save_start = time.perf_counter()
    try:
        save_graph(graph, path)
    except Exception as exc:  # pragma: no cover - benchmark diagnostics
        return {"format": fmt, "status": "save_error", "error": f"{type(exc).__name__}: {exc}"}
    save_ms = (time.perf_counter() - save_start) * 1000

    file_bytes = path.stat().st_size if path.exists() else 0

    load_start = time.perf_counter()
    try:
        loaded = load_any(path)
    except Exception as exc:  # pragma: no cover - benchmark diagnostics
        return {"format": fmt, "status": "load_error", "error": f"{type(exc).__name__}: {exc}"}
    load_ms = (time.perf_counter() - load_start) * 1000
    node_fidelity = loaded.nodes == canonical.nodes
    edge_fidelity = loaded.edges == canonical.edges
    metadata_fidelity = loaded.metadata == canonical.metadata

    cold_s, _ = time_queries(loaded, tasks, rounds=QUERY_ROUNDS_COLD)
    cached_s, tokens = time_queries(loaded, tasks, rounds=QUERY_ROUNDS_CACHED)
    per_query_ms = (cached_s / max(1, QUERY_ROUNDS_CACHED * max(1, len(tasks)))) * 1000

    return {
        "format": fmt,
        "status": "ok",
        "error": "",
        "file_bytes": file_bytes,
        "save_ms": round(save_ms, 3),
        "load_ms": round(load_ms, 3),
        "cold_query_round_ms": round(cold_s * 1000, 3),
        "cached_query_ms_per_query": round(per_query_ms, 4),
        "tokens_last_round": tokens,
        "loaded_nodes": len(loaded.nodes),
        "loaded_edges": len(loaded.edges),
        "node_fidelity": node_fidelity,
        "edge_fidelity": edge_fidelity,
        "metadata_fidelity": metadata_fidelity,
        "full_fidelity": node_fidelity and edge_fidelity and metadata_fidelity,
    }


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = read_existing_rows()
    force = os.environ.get("BAKEOFF_FORCE") == "1"
    for path, tier in corpus():
        project = path.name
        if not force and project_complete(rows, project):
            print(f"Skipping {project}; complete rows already present (set BAKEOFF_FORCE=1 to rerun).", flush=True)
            continue
        print(f"Scanning {project} ({tier})...", flush=True)
        scan_start = time.perf_counter()
        try:
            graph = scan_project(path, tier)
        except Exception as exc:  # pragma: no cover - benchmark diagnostics
            rows.append({"project": project, "tier": tier, "format": "-", "status": "scan_error", "error": f"{type(exc).__name__}: {exc}"})
            write(rows)
            continue
        scan_ms = (time.perf_counter() - scan_start) * 1000
        tasks = make_query_tasks(graph)
        print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges, {len(tasks)} tasks, scan={scan_ms:.0f}ms")
        canonical_path = GRAPHS / f"{safe_name(project)}.canonical.json"
        save_graph(graph, canonical_path)
        canonical = load_any(canonical_path)

        for fmt in FORMATS:
            print(f"  format {fmt}...", flush=True)
            row = bench_format(graph, canonical, tasks, project, fmt)
            row.update({"project": project, "tier": tier, "scan_ms": round(scan_ms, 1), "source_nodes": len(graph.nodes), "source_edges": len(graph.edges)})
            rows.append(row)
        write(rows)

    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


def read_existing_rows() -> list[dict[str, object]]:
    if not RESULTS_CSV.exists():
        return []
    with RESULTS_CSV.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def project_complete(rows: list[dict[str, object]], project: str) -> bool:
    project_rows = [row for row in rows if row.get("project") == project and row.get("status") == "ok"]
    formats = {row.get("format") for row in project_rows}
    return set(FORMATS).issubset(formats)


def write(rows: list[dict[str, object]]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})

    ok_rows = [row for row in rows if row.get("status") == "ok"]
    by_format: dict[str, list[dict[str, object]]] = {}
    for row in ok_rows:
        by_format.setdefault(str(row["format"]), []).append(row)

    lines = [
        "# Storage Backend Bake-Off",
        "",
        "Real-repo comparison of persisted graph storage formats. Each project is",
        "scanned once; every format below saves/loads/queries the *same* in-memory",
        "graph, so differences are attributable to the storage format alone.",
        "",
        f"Projects: `{len({row['project'] for row in rows})}`",
        f"Small/medium max nodes: `{SMALL_MEDIUM_MAX_NODES}`  |  Large tier max nodes: `{LARGE_MAX_NODES}`",
        "",
        "## By Format (averaged across all projects)",
        "",
        "| Format | Projects | Avg file bytes | Avg save ms | Avg load ms | Avg cached ms/query |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fmt, items in sorted(by_format.items()):
        lines.append(
            f"| `{fmt}` | {len(items)} | {avg(items, 'file_bytes'):.0f} | {avg(items, 'save_ms'):.2f} | "
            f"{avg(items, 'load_ms'):.2f} | {avg(items, 'cached_query_ms_per_query'):.4f} |"
        )

    lines.extend([
        "",
        "## By Project x Format",
        "",
        "| Project | Tier | Format | Full fidelity | File bytes | Save ms | Load ms | Cached ms/query |",
        "| --- | --- | --- | :---: | ---: | ---: | ---: | ---: |",
    ])
    for row in sorted(ok_rows, key=lambda r: (str(r["project"]), str(r["format"]))):
        lines.append(
            f"| {row['project']} | {row['tier']} | `{row['format']}` | "
            f"{'yes' if row.get('full_fidelity') else 'no'} | {row['file_bytes']} | "
            f"{row['save_ms']} | {row['load_ms']} | {row['cached_query_ms_per_query']} |"
        )

    fidelity_failures = [row for row in ok_rows if not row.get("full_fidelity")]
    if fidelity_failures:
        lines.extend([
            "",
            "## Fidelity Failures",
            "",
            "| Project | Tier | Format | Nodes | Edges | Metadata |",
            "| --- | --- | --- | :---: | :---: | :---: |",
        ])
        for row in fidelity_failures:
            lines.append(
                f"| {row['project']} | {row['tier']} | `{row['format']}` | "
                f"{'ok' if row.get('node_fidelity') else 'lossy'} | "
                f"{'ok' if row.get('edge_fidelity') else 'lossy'} | "
                f"{'ok' if row.get('metadata_fidelity') else 'lossy'} |"
            )

    failures = [row for row in rows if row.get("status") not in {"ok"}]
    if failures:
        lines.extend([
            "",
            "## Failures",
            "",
            "| Project | Tier | Format | Status | Error |",
            "| --- | --- | --- | --- | --- |",
        ])
        for row in failures:
            lines.append(f"| {row.get('project')} | {row.get('tier')} | {row.get('format')} | {row.get('status')} | {row.get('error', '')} |")

    lines.extend([
        "",
        "## Read",
        "",
        "- `save_ms`/`load_ms` isolate storage-format cost only; `scan_ms` (per-project, see CSV) is separate and identical across formats since the graph is scanned once and reused.",
        "- `cached_query_ms_per_query` measures repeated retrieval against one already-loaded graph, so it reflects the loaded in-memory representation's query-friendliness, not disk I/O.",
        "- `full_fidelity` means nodes, edges, and metadata round-trip exactly. Lossy formats can be useful packet/debug formats but should not be promoted as the persisted graph store.",
        f"- CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


if __name__ == "__main__":
    main()
