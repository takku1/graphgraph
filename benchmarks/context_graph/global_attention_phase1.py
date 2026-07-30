from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from .real_project_answerability_limit import make_tasks
except ImportError:
    from real_project_answerability_limit import make_tasks  # type: ignore[no-redef]

from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import estimate_tokens  # noqa: E402
from graphgraph.research import (  # noqa: E402
    build_path_hierarchy,
    compile_greedy_formula_cover,
    evaluate_cover,
    evaluate_expected_resolution,
    render_cover_plan,
    render_exact_nodes,
    select_flat_nodes_at_token_budget,
)

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "global_attention"
REPORT_JSON = OUT / "phase1.json"
REPORT_MD = OUT / "phase1.md"
REAL_GRAPH_DIR = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects" / "graphs"
GRAPH_NAMES = ("graphgraph", "chess", "express", "requests")
BUDGETS = (16, 32, 64)
EXACTNESS_WEIGHT = 0.01
MIN_RESOLUTION_GAIN = 0.02
MAX_EXACT_RECALL_LOSS = 0.02


def candidate_packet(
    graph,
    hierarchy,
    field,
    representation_units: int,
    *,
    exactness_weight: float = EXACTNESS_WEIGHT,
    resolution_weight: float = 0.0,
):
    """Compile C1 without accepting evaluator-only expected evidence."""
    plan = compile_greedy_formula_cover(
        hierarchy.hierarchy,
        field,
        representation_units,
        exactness_weight=exactness_weight,
        resolution_weight=resolution_weight,
    )
    packet = render_cover_plan(graph, hierarchy, field, plan)
    return plan, packet


def main() -> None:
    graph_paths = [REAL_GRAPH_DIR / f"{name}.json" for name in GRAPH_NAMES]
    missing = [path.name for path in graph_paths if not path.exists()]
    if missing:
        print(f"SKIP: missing frozen Phase 1 graphs: {', '.join(missing)}")
        return
    rows: list[dict[str, object]] = []

    for graph_path in graph_paths:
        rows.extend(evaluate_graph_path(graph_path))

    report = summarize(graph_paths, rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def evaluate_graph_path(
    graph_path: Path,
    *,
    budgets: tuple[int, ...] = BUDGETS,
    exactness_weight: float = EXACTNESS_WEIGHT,
    resolution_weight: float = 0.0,
) -> list[dict[str, object]]:
    graph = load_any(graph_path)
    hierarchy = build_path_hierarchy(graph, max_branching=8)
    tasks = make_tasks(graph)
    rows: list[dict[str, object]] = []
    for task in tasks:
        seed_mass = 1.0 / len(task.starts)
        ppr_started = time.perf_counter()
        field = graph.personalized_pagerank(
            {node_id: seed_mass for node_id in task.starts},
            max_iter=30,
            tol=1e-7,
        )
        ppr_ms = (time.perf_counter() - ppr_started) * 1000.0
        for budget in budgets:
            compile_started = time.perf_counter()
            plan, packet = candidate_packet(
                graph,
                hierarchy,
                field,
                budget,
                exactness_weight=exactness_weight,
                resolution_weight=resolution_weight,
            )
            compile_ms = (time.perf_counter() - compile_started) * 1000.0
            candidate_tokens = estimate_tokens(packet)
            flat_started = time.perf_counter()
            flat_nodes = select_flat_nodes_at_token_budget(
                graph,
                field,
                candidate_tokens,
            )
            flat_packet = render_exact_nodes(graph, field, flat_nodes)
            flat_ms = (time.perf_counter() - flat_started) * 1000.0

            # Gold task evidence enters only after both packets are frozen.
            candidate_evidence = evaluate_expected_resolution(
                hierarchy.hierarchy,
                plan,
                task.expected_nodes,
            )
            flat_exact_recall = len(set(flat_nodes) & task.expected_nodes) / max(
                1,
                len(task.expected_nodes),
            )
            cover = evaluate_cover(hierarchy.hierarchy, field, plan)
            rows.append(
                {
                    "project": graph_path.stem,
                    "query_class": task.query_class,
                    "representation_units": budget,
                    "candidate_tokens": candidate_tokens,
                    "flat_tokens": estimate_tokens(flat_packet),
                    "candidate_exact_recall": candidate_evidence["exact_recall"],
                    "candidate_resolution_recall": candidate_evidence["resolution_recall"],
                    "candidate_worst_resolution": candidate_evidence["worst_resolution"],
                    "flat_exact_recall": flat_exact_recall,
                    "coverage": cover["coverage"]["coverage"],
                    "mass_error": cover["mass_error"],
                    "l1_error": cover["l1_error"],
                    "rwc": cover["resolution_weighted_coverage"],
                    "ppr_ms": ppr_ms,
                    "compile_ms": compile_ms,
                    "flat_ms": flat_ms,
                }
            )
    return rows


def summarize(graph_paths: list[Path], rows: list[dict[str, object]]) -> dict[str, object]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["representation_units"])].append(row)

    def average(items: list[dict[str, object]], key: str) -> float:
        return sum(float(item[key]) for item in items) / max(1, len(items))

    by_budget: dict[str, dict[str, object]] = {}
    for budget, items in sorted(grouped.items()):
        candidate_exact = average(items, "candidate_exact_recall")
        candidate_resolution = average(items, "candidate_resolution_recall")
        flat_exact = average(items, "flat_exact_recall")
        by_budget[str(budget)] = {
            "cases": len(items),
            "candidate_tokens": average(items, "candidate_tokens"),
            "flat_tokens": average(items, "flat_tokens"),
            "candidate_exact_recall": candidate_exact,
            "candidate_resolution_recall": candidate_resolution,
            "flat_exact_recall": flat_exact,
            "resolution_gain": candidate_resolution - flat_exact,
            "exact_recall_loss": flat_exact - candidate_exact,
            "mean_l1_error": average(items, "l1_error"),
            "mean_rwc": average(items, "rwc"),
            "mean_ppr_ms": average(items, "ppr_ms"),
            "mean_compile_ms": average(items, "compile_ms"),
            "mean_flat_ms": average(items, "flat_ms"),
        }

    project_groups: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        project_groups[(str(row["project"]), int(row["representation_units"]))].append(row)
    by_project: dict[str, dict[str, object]] = {}
    for project in GRAPH_NAMES:
        budgets: dict[str, dict[str, float]] = {}
        for budget in BUDGETS:
            items = project_groups[(project, budget)]
            candidate_exact = average(items, "candidate_exact_recall")
            candidate_resolution = average(items, "candidate_resolution_recall")
            flat_exact = average(items, "flat_exact_recall")
            budgets[str(budget)] = {
                "candidate_exact_recall": candidate_exact,
                "candidate_resolution_recall": candidate_resolution,
                "flat_exact_recall": flat_exact,
                "resolution_gain": candidate_resolution - flat_exact,
                "exact_recall_loss": flat_exact - candidate_exact,
            }
        by_project[project] = {
            "screen_pass": any(
                row["resolution_gain"] >= MIN_RESOLUTION_GAIN and row["exact_recall_loss"] <= MAX_EXACT_RECALL_LOSS
                for row in budgets.values()
            ),
            "by_budget": budgets,
        }

    gates = {
        "tasks_present": bool(rows),
        "complete_cover": all(float(row["coverage"]) == 1.0 for row in rows),
        "mass_conservation": all(float(row["mass_error"]) <= 1e-10 for row in rows),
        "equal_token_ceiling": all(int(row["flat_tokens"]) <= int(row["candidate_tokens"]) for row in rows),
    }
    screen_pass = any(
        float(item["resolution_gain"]) >= MIN_RESOLUTION_GAIN
        and float(item["exact_recall_loss"]) <= MAX_EXACT_RECALL_LOSS
        for item in by_budget.values()
    )
    heldout_pass = all(bool(by_project[project]["screen_pass"]) for project in GRAPH_NAMES[1:])
    return {
        "status": (
            "heldout_development_pass" if all(gates.values()) and screen_pass and heldout_pass else "no_champion"
        ),
        "interpretation": "representation-stage multi-project evidence only; not H1 or production promotion",
        "graphs": [str(path.relative_to(ROOT)).replace("\\", "/") for path in graph_paths],
        "tasks": len(rows) // len(BUDGETS),
        "exactness_weight": EXACTNESS_WEIGHT,
        "minimum_resolution_gain": MIN_RESOLUTION_GAIN,
        "maximum_exact_recall_loss": MAX_EXACT_RECALL_LOSS,
        "gates": gates,
        "by_budget": by_budget,
        "by_project": by_project,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Global Project Attention — Phase 1 Development Screen",
        "",
        f"Status: `{report['status']}`",
        "",
        "This is a representation-stage frozen multi-project screen. Candidate compilation",
        "uses starts and PPR only; expected evidence is evaluator-only. It cannot promote H1.",
        "",
        "## Deterministic gates",
        "",
    ]
    for gate, passed in report["gates"].items():
        lines.append(f"- `{gate}`: `{'PASS' if passed else 'FAIL'}`")
    lines.extend(
        [
            "",
            "| Units | C1 tokens | Flat tokens | C1 exact recall | C1 resolution recall | Flat exact recall | Resolution gain | Exact loss | L1 | RWC |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for budget, row in report["by_budget"].items():
        lines.append(
            f"| {budget} | {row['candidate_tokens']:.1f} | {row['flat_tokens']:.1f} | "
            f"{row['candidate_exact_recall']:.3f} | {row['candidate_resolution_recall']:.3f} | "
            f"{row['flat_exact_recall']:.3f} | {row['resolution_gain']:+.3f} | "
            f"{row['exact_recall_loss']:+.3f} | {row['mean_l1_error']:.6f} | {row['mean_rwc']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Project transfer",
            "",
            "| Project | Screen | Best resolution gain | Exact loss at best gain |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for project, project_row in report["by_project"].items():
        best = max(
            project_row["by_budget"].values(),
            key=lambda row: row["resolution_gain"],
        )
        lines.append(
            f"| {project} | {'PASS' if project_row['screen_pass'] else 'FAIL'} | "
            f"{best['resolution_gain']:+.3f} | {best['exact_recall_loss']:+.3f} |"
        )
    lines.extend(
        [
            "",
            "## Mean phase latency",
            "",
            "| Units | Full PPR ms | C1 compile ms | Flat selection ms |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for budget, row in report["by_budget"].items():
        lines.append(
            f"| {budget} | {row['mean_ppr_ms']:.1f} | {row['mean_compile_ms']:.1f} | {row['mean_flat_ms']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Decision boundary",
            "",
            f"A budget advances only with resolution gain >= {MIN_RESOLUTION_GAIN:.2f} and exact-recall loss <= {MAX_EXACT_RECALL_LOSS:.2f}.",
            "A pass only licenses held-out Phase 1 work. A failure records no champion.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
