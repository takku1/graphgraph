from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from .global_attention_phase1 import (
        GRAPH_NAMES,
        MAX_EXACT_RECALL_LOSS,
        MIN_RESOLUTION_GAIN,
        REAL_GRAPH_DIR,
        evaluate_graph_path,
    )
except ImportError:
    from global_attention_phase1 import (  # type: ignore[no-redef]
        GRAPH_NAMES,
        MAX_EXACT_RECALL_LOSS,
        MIN_RESOLUTION_GAIN,
        REAL_GRAPH_DIR,
        evaluate_graph_path,
    )

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "global_attention"
REPORT_JSON = OUT / "phase1_formula_sweep.json"
REPORT_MD = OUT / "phase1_formula_sweep.md"
WEIGHTS = (0.001, 0.01, 0.1, 1.0)
BUDGETS = (32, 64)


def main() -> None:
    graph_paths = [REAL_GRAPH_DIR / f"{name}.json" for name in GRAPH_NAMES]
    missing = [path.name for path in graph_paths if not path.exists()]
    if missing:
        print(f"SKIP: missing formula-sweep graphs: {', '.join(missing)}")
        return

    rows: list[dict[str, object]] = []
    for weight in WEIGHTS:
        for graph_path in graph_paths:
            for row in evaluate_graph_path(
                graph_path,
                budgets=BUDGETS,
                exactness_weight=weight,
            ):
                rows.append({**row, "exactness_weight": weight})

    report = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def summarize(
    rows: list[dict[str, object]],
    *,
    weights: tuple[float, ...] = WEIGHTS,
    budgets: tuple[int, ...] = BUDGETS,
    weight_key: str = "exactness_weight",
) -> dict[str, object]:
    groups: dict[tuple[float, int, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[
            (
                float(row[weight_key]),
                int(row["representation_units"]),
                str(row["project"]),
            )
        ].append(row)

    def average(items: list[dict[str, object]], key: str) -> float:
        return sum(float(item[key]) for item in items) / max(1, len(items))

    configurations: list[dict[str, object]] = []
    for weight in weights:
        for budget in budgets:
            projects: dict[str, dict[str, float]] = {}
            for project in GRAPH_NAMES:
                items = groups[(weight, budget, project)]
                resolution = average(items, "candidate_resolution_recall")
                exact = average(items, "candidate_exact_recall")
                flat = average(items, "flat_exact_recall")
                projects[project] = {
                    "resolution_gain": resolution - flat,
                    "exact_recall_loss": flat - exact,
                }
            gains = [row["resolution_gain"] for row in projects.values()]
            losses = [row["exact_recall_loss"] for row in projects.values()]
            configurations.append(
                {
                    "formula_weight": weight,
                    "representation_units": budget,
                    "worst_project_gain": min(gains),
                    "mean_project_gain": sum(gains) / len(gains),
                    "maximum_exact_recall_loss": max(losses),
                    "guardrail_pass": max(losses) <= MAX_EXACT_RECALL_LOSS,
                    "projects": projects,
                }
            )

    winner = max(
        configurations,
        key=lambda row: (
            bool(row["guardrail_pass"]),
            float(row["worst_project_gain"]),
            float(row["mean_project_gain"]),
            -float(row["formula_weight"]),
        ),
    )
    candidate_found = bool(winner["guardrail_pass"]) and float(winner["worst_project_gain"]) >= MIN_RESOLUTION_GAIN
    deterministic_gates = {
        "complete_cover": all(float(row["coverage"]) == 1.0 for row in rows),
        "mass_conservation": all(float(row["mass_error"]) <= 1e-10 for row in rows),
        "equal_token_ceiling": all(int(row["flat_tokens"]) <= int(row["candidate_tokens"]) for row in rows),
    }
    return {
        "status": (
            "formula_candidate_found"
            if candidate_found and all(deterministic_gates.values())
            else "no_formula_champion"
        ),
        "interpretation": "development/validation sweep only; selected configuration requires untouched project holdouts",
        "weights": weights,
        "budgets": budgets,
        "deterministic_gates": deterministic_gates,
        "winner": winner,
        "configurations": configurations,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Global Project Attention — Phase 1 Formula Sweep",
        "",
        f"Status: `{report['status']}`",
        "",
        "GraphGraph, Chess, Express, and Requests are development/validation data.",
        "Selection maximizes worst-project resolution gain subject to the exact-recall guardrail.",
        "",
        "| Weight | Units | Worst gain | Mean gain | Max exact loss | Guardrail |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["configurations"]:
        lines.append(
            f"| {row['formula_weight']:.3g} | {row['representation_units']} | "
            f"{row['worst_project_gain']:+.3f} | {row['mean_project_gain']:+.3f} | "
            f"{row['maximum_exact_recall_loss']:+.3f} | "
            f"{'PASS' if row['guardrail_pass'] else 'FAIL'} |"
        )
    winner = report["winner"]
    selected_heading = (
        "Selected configuration"
        if report["status"] == "formula_candidate_found"
        else "Least-bad configuration (not selected)"
    )
    lines.extend(
        [
            "",
            f"## {selected_heading}",
            "",
            f"- weight: `{winner['formula_weight']}`",
            f"- representation units: `{winner['representation_units']}`",
            f"- worst-project resolution gain: `{winner['worst_project_gain']:+.3f}`",
            f"- maximum exact-recall loss: `{winner['maximum_exact_recall_loss']:+.3f}`",
            "",
            "This result cannot promote H1. Only a formula_candidate_found result may be",
            "frozen for repositories absent from this sweep.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
