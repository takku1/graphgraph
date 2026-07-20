"""Snippet usefulness A/B benchmark: graph packet alone vs packet + lazy snippets.

Graph packets are structural (label/kind/path/summary/facts) and never embed
raw source lines. `services/snippets.py`'s `render_source_snippets` is the
second stage of the precision ladder: exact source text for selected nodes,
loaded only on demand. This benchmark quantifies the actual trade-off on real
repos: how many extra tokens snippets cost, versus how much exact-source-line
evidence they add that the structural packet alone never had.

For each symbol/file anchor task (reusing cross_repo_anchor_stress's task
generator), it takes the anchor node's real declared source line and checks
whether that *exact* line of code is already substring-present in the plain
packet text (expected: rarely/never, since packets don't carry raw source),
then checks whether it's present once snippets are appended (expected: yes,
whenever the source path/line resolves) -- and records the token cost of
getting there.

Usage:
    python benchmarks/context_graph/snippet_usefulness_benchmark.py
    BAKEOFF_PROJECTS=flask;requests python benchmarks/context_graph/snippet_usefulness_benchmark.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
BENCH_DIR = Path(__file__).resolve().parent
for p in (SRC, BENCH_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import cross_repo_anchor_stress as cras  # noqa: E402 - reuse task generation
import local_corpus  # noqa: E402

from graphgraph.analysis.eval import estimate_tokens  # noqa: E402
from graphgraph.graph.core import Graph  # noqa: E402
from graphgraph.io import load_any, save_graph  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph  # noqa: E402
from graphgraph.retrieval import retrieve_context  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402
from graphgraph.services.snippets import render_source_snippets  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "snippet_usefulness"
GRAPHS = OUT / "graphs"
RESULTS_CSV = OUT / "snippet_usefulness.csv"
SUMMARY_MD = OUT / "snippet_usefulness.md"

MAX_NODES = int(os.environ.get("SNIPPET_BENCH_MAX_NODES", "3000"))
MAX_TASKS_PER_PROJECT = int(os.environ.get("SNIPPET_BENCH_MAX_TASKS", "6"))
TASK_KINDS = {"symbol_direct", "file_summary"}


def corpus() -> list[Path]:
    only_projects = os.environ.get("BAKEOFF_PROJECTS")
    paths = local_corpus.small_medium_paths()
    if only_projects:
        wanted = {name.strip() for name in only_projects.split(";") if name.strip()}
        paths = [p for p in paths if p.name in wanted]
    return paths


def source_line_for_node(graph: Graph, root: Path, node_id: str) -> str | None:
    node = graph.nodes.get(node_id)
    if node is None or not node.path:
        return None
    candidate = root / node.path
    if not candidate.exists() or not candidate.is_file():
        return None
    line_no = _node_line(node)
    try:
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    idx = (line_no - 1) if line_no else 0
    idx = max(0, min(idx, len(lines) - 1))
    line = lines[idx].strip()
    return line if len(line) >= 8 else None  # too-short lines are unreliable substring markers


def _node_line(node) -> int | None:
    import re

    match = re.search(r"\bL(\d+)\b", node.summary or "")
    if not match:
        return None
    try:
        return max(1, int(match.group(1)))
    except ValueError:
        return None


def bench_project(path: Path) -> list[dict[str, object]]:
    project = path.name
    graph_path = GRAPHS / f"{project}.json"
    if graph_path.exists():
        graph = load_any(graph_path)
    else:
        graph = scan_directory(
            path, max_nodes=MAX_NODES, skip_dirs=cras.SKIP_DIRS, depth="symbols", frontend="auto", docs=True
        )
        save_graph(graph, graph_path)

    tasks = [t for t in cras.make_tasks(graph) if t.kind in TASK_KINDS][:MAX_TASKS_PER_PROJECT]
    rows: list[dict[str, object]] = []
    for task in tasks:
        anchor_id = task.expected_nodes[0]
        source_line = source_line_for_node(graph, path, anchor_id)
        if source_line is None:
            continue

        plan = plan_context(task.query_class, task.query)
        result = retrieve_context(graph, task.query, task.query_class, hops=plan.hops, max_nodes=plan.node_budget)
        plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, result.nodes, result.edges))
        packet = render_packet(graph, result.nodes, result.edges, plan.packet)
        packet_tokens = estimate_tokens(packet)

        try:
            snippet_text = render_source_snippets(starts=[anchor_id], graph_path=graph_path, context_lines=4, max_lines=40)
        except Exception:
            snippet_text = ""
        combined = packet + "\n\n" + snippet_text
        combined_tokens = estimate_tokens(combined)

        rows.append({
            "project": project,
            "task_kind": task.kind,
            "query": task.query,
            "anchor": anchor_id,
            "evidence_in_packet_alone": source_line in packet,
            "evidence_in_packet_plus_snippet": source_line in combined,
            "packet_tokens": packet_tokens,
            "snippet_tokens": combined_tokens - packet_tokens,
            "combined_tokens": combined_tokens,
        })
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    for path in corpus():
        print(f"Benchmarking {path.name}...", flush=True)
        start = time.perf_counter()
        rows.extend(bench_project(path))
        print(f"  done in {time.perf_counter() - start:.1f}s")

    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


def write(rows: list[dict[str, object]]) -> None:
    import csv

    fields = [
        "project", "task_kind", "query", "anchor", "evidence_in_packet_alone",
        "evidence_in_packet_plus_snippet", "packet_tokens", "snippet_tokens", "combined_tokens",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    total = len(rows)
    packet_alone_hits = sum(1 for r in rows if r["evidence_in_packet_alone"])
    combined_hits = sum(1 for r in rows if r["evidence_in_packet_plus_snippet"])
    avg_packet_tokens = avg(rows, "packet_tokens")
    avg_snippet_tokens = avg(rows, "snippet_tokens")

    lines = [
        "# Snippet Usefulness Benchmark",
        "",
        "For each anchor task, checks whether the exact source line at the anchor's",
        "declared location is already present in the structural graph packet alone,",
        "versus present once lazy source snippets are appended -- and the token cost",
        "of getting there.",
        "",
        f"Tasks: `{total}`",
        f"Exact source line present in packet alone: `{packet_alone_hits}/{total}`",
        f"Exact source line present in packet + snippet: `{combined_hits}/{total}`",
        f"Avg packet tokens (no snippet): `{avg_packet_tokens:.1f}`",
        f"Avg snippet token cost (marginal): `{avg_snippet_tokens:.1f}`",
        "",
        "| Project | Kind | Query | Evidence in packet alone | Evidence w/ snippet | Packet tokens | Snippet tokens |",
        "| --- | --- | --- | :---: | :---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['project']} | {row['task_kind']} | {row['query']} | "
            f"{'yes' if row['evidence_in_packet_alone'] else 'no'} | "
            f"{'yes' if row['evidence_in_packet_plus_snippet'] else 'no'} | "
            f"{row['packet_tokens']} | {row['snippet_tokens']} |"
        )

    lines.extend([
        "",
        "## Read",
        "",
        "- This does not measure LLM answer quality; it measures whether exact",
        "  source-level evidence (a specific line of code) is textually available",
        "  in the context at all, and what it costs in tokens.",
        "- A packet-alone hit is expected to be rare/zero -- packets carry summaries",
        "  and facts, not raw source lines -- so a high packet-alone hit rate would",
        "  indicate summaries are effectively echoing source verbatim (worth a look).",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


if __name__ == "__main__":
    main()
