"""EXP-GPA-COUPLING-PROD: does symmetric coupling survive production ranking?

`EXP-GPA-RECOUPLED` measured a +0.066 exact-recall gain for symmetric coupling
on a *pure field-ranked* selection. Production `search_nodes` is not that: it
combines personalized PageRank with lexical scoring, a degree boost, kind
priors, and scope filters, and it switches to localized PPR above 512 nodes.
A signal that helps a bare field can easily vanish once it is one term among
many.

This scores real labelled eval tasks through the real ranker, changing only the
coupling of the PageRank term, using the eval harness's own MRR/NDCG functions.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from graphgraph.analysis.eval import (  # noqa: E402
    _node_keys,
    _resolve_node_expectation_ids,
    load_eval_tasks,
    ndcg_at_k,
    reciprocal_rank,
)
from graphgraph.io import find_graph_path, load_any_cached  # noqa: E402
from graphgraph.retrieval.search import search_nodes  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "protocol"
REPORT_JSON = OUT / "coupling_production_ranking.json"
REPORT_MD = OUT / "coupling_production_ranking.md"

TASK_FILES = (
    "eval/graphgraph-self.json",
    "eval/graphgraph-calibration.json",
    "eval/graphgraph-doc-authority-target.json",
)
COUPLINGS = ("directed", "symmetric", "reverse")
LIMIT = 20


def score(graph, tasks, coupling: str) -> list[dict[str, object]]:
    # Eval expectations are written as labels ("handle_select_symbols"), not
    # node IDs. Matching them literally scores every arm at zero, so resolve
    # them exactly as the eval harness does before scoring anything.
    node_keys_by_id = {nid: _node_keys(graph, (nid,)) for nid in graph.nodes}
    rows: list[dict[str, object]] = []
    for task in tasks:
        if not task.expected_nodes:
            continue
        groups = [
            _resolve_node_expectation_ids(graph, node_keys_by_id, item)
            for item in task.expected_nodes
        ]
        unresolved = sum(1 for group in groups if not group)
        expected_ids: set[str] = set()
        for group in groups:
            expected_ids |= group
        if not expected_ids:
            continue
        started = time.perf_counter()
        matches = search_nodes(
            graph, task.query, limit=LIMIT, personalize=True, coupling=coupling
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        ranked = [match.node.id for match in matches]
        returned = set(ranked)
        rows.append(
            {
                "query": task.query,
                "query_class": task.query_class,
                "coupling": coupling,
                # Group-wise, like the harness: one expectation is satisfied by
                # any of the ids it resolves to.
                "recall": sum(bool(group & returned) for group in groups) / len(groups),
                "unresolved_expectations": unresolved,
                "mrr": reciprocal_rank(ranked, expected_ids),
                "ndcg_at_5": ndcg_at_k(ranked, expected_ids, 5),
                "ndcg_at_10": ndcg_at_k(ranked, expected_ids, 10),
                "latency_ms": elapsed_ms,
            }
        )
    return rows


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    per_coupling: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        per_coupling.setdefault(str(row["coupling"]), []).append(row)

    # Pair positionally, not by query text: the task files repeat three query
    # strings, so a dict keyed on the query silently pairs a row against a
    # different task and made the directed arm differ from itself.
    baseline = per_coupling.get("directed", [])
    cells = []
    for coupling, group in per_coupling.items():
        assert len(group) == len(baseline), "coupling arms must score the same tasks in order"
        paired_recall = [
            float(row["recall"]) - float(base["recall"])
            for row, base in zip(group, baseline)
        ]
        paired_mrr = [
            float(row["mrr"]) - float(base["mrr"]) for row, base in zip(group, baseline)
        ]
        paired_ndcg = [
            float(row["ndcg_at_10"]) - float(base["ndcg_at_10"])
            for row, base in zip(group, baseline)
        ]
        cells.append(
            {
                "coupling": coupling,
                "tasks": len(group),
                "mean_recall": mean(float(r["recall"]) for r in group),
                "mean_mrr": mean(float(r["mrr"]) for r in group),
                "mean_ndcg_at_10": mean(float(r["ndcg_at_10"]) for r in group),
                "median_latency_ms": median(float(r["latency_ms"]) for r in group),
                "paired_recall_delta": mean(paired_recall) if paired_recall else 0.0,
                "paired_mrr_delta": mean(paired_mrr) if paired_mrr else 0.0,
                "paired_ndcg_delta": mean(paired_ndcg) if paired_ndcg else 0.0,
                "recall_better": sum(1 for x in paired_recall if x > 1e-9),
                "recall_worse": sum(1 for x in paired_recall if x < -1e-9),
                "mrr_better": sum(1 for x in paired_mrr if x > 1e-9),
                "mrr_worse": sum(1 for x in paired_mrr if x < -1e-9),
                "ndcg_better": sum(1 for x in paired_ndcg if x > 1e-9),
                "ndcg_worse": sum(1 for x in paired_ndcg if x < -1e-9),
            }
        )
    return {"experiment_id": "EXP-GPA-COUPLING-PROD", "cells": cells}


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# EXP-GPA-COUPLING-PROD — symmetric coupling inside production ranking",
        "",
        "Real labelled eval tasks scored through `search_nodes` with the eval "
        "harness's own MRR/NDCG. Only the PageRank term's edge orientation "
        "changes; lexical scoring and the degree boost still read the real edges.",
        "",
        "| coupling | tasks | mean recall | mean MRR | mean NDCG@10 | paired NDCG delta | NDCG better/worse | median ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: |",
    ]
    for cell in report["cells"]:  # type: ignore[index]
        lines.append(
            f"| {cell['coupling']} | {cell['tasks']} | {cell['mean_recall']:.4f} | "
            f"{cell['mean_mrr']:.4f} | {cell['mean_ndcg_at_10']:.4f} | "
            f"{cell['paired_ndcg_delta']:+.4f} | "
            f"{cell['ndcg_better']}/{cell['ndcg_worse']} | "
            f"{cell['median_latency_ms']:.0f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    graph_path = find_graph_path(ROOT)
    if graph_path is None or not Path(graph_path).exists():
        print("SKIP: no graph found; run `graphgraph scan --depth symbols --docs`")
        return
    graph = load_any_cached(Path(graph_path))
    tasks = []
    for name in TASK_FILES:
        path = ROOT / name
        if path.exists():
            tasks.extend(load_eval_tasks(path))
    if not tasks:
        print("SKIP: no eval tasks found")
        return

    rows: list[dict[str, object]] = []
    for coupling in COUPLINGS:
        rows.extend(score(graph, tasks, coupling))
    report = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps({"rows": rows, **report}, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
