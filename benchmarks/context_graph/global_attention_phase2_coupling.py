"""EXP-GPA-COUPLING: does the influence field admit a far field at all?

Phase 1 rejected the C1 cover formulas on real projects. That verdict assumed
the field feeding those covers carried mass worth distributing. This experiment
tests the substrate instead of the representation: the hierarchy, tasks, seeds,
budgets, and metrics are held fixed while only the edge coupling is exchanged.

`directed` is the incumbent. If it leaves the far field empty on most projects,
Phase 1 measured cover formulas over nothing, and the coupling -- not the
formula -- is the variable that has to move first.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_attention_phase1 import (  # noqa: E402
    GRAPH_NAMES,
    REAL_GRAPH_DIR,
    load_any,
    make_tasks,
)

from graphgraph.research import FIELD_COUPLINGS  # noqa: E402
from graphgraph.research.attention_field import (  # noqa: E402
    field_support_receipt,
    influence_field,
)

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "protocol"
REPORT_JSON = OUT / "global_attention_coupling.json"
REPORT_MD = OUT / "global_attention_coupling.md"

# GPA-DEF-001 asks for nonzero influence on every entity. A field that reaches
# under this fraction cannot support a far-field representation regardless of
# which cover formula consumes it.
DEGENERACY_THRESHOLD = 0.10


def evaluate_graph(name: str) -> list[dict[str, object]]:
    graph = load_any(REAL_GRAPH_DIR / f"{name}.json")
    active = frozenset(node_id for node_id, node in graph.nodes.items() if node.active)
    rows: list[dict[str, object]] = []
    for task in make_tasks(graph):
        seed_mass = 1.0 / len(task.starts)
        seeds = {node_id: seed_mass for node_id in task.starts}
        for coupling in FIELD_COUPLINGS:
            field = influence_field(graph, seeds, coupling=coupling)
            receipt = field_support_receipt(field)
            rows.append(
                {
                    "project": name,
                    "task": getattr(task, "task_id", None) or getattr(task, "name", "?"),
                    "coupling": coupling,
                    "active_entities": len(active),
                    "seeds": len(task.starts),
                    **receipt,
                }
            )
    return rows


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    def median(values: list[float]) -> float:
        ordered = sorted(values)
        return ordered[len(ordered) // 2] if ordered else float("nan")

    per_cell: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        per_cell.setdefault((str(row["project"]), str(row["coupling"])), []).append(row)

    cells = []
    for (project, coupling), group in sorted(per_cell.items()):
        supports = [float(r["support_fraction"]) for r in group]
        outside = [float(r["mass_outside_top_k"]) for r in group]
        effective = [float(r["effective_entities"]) for r in group]
        cells.append(
            {
                "project": project,
                "coupling": coupling,
                "tasks": len(group),
                "median_support_fraction": median(supports),
                "min_support_fraction": min(supports),
                "median_mass_outside_top_k": median(outside),
                "median_effective_entities": median(effective),
                "degenerate": median(supports) < DEGENERACY_THRESHOLD,
            }
        )

    per_coupling: dict[str, list[dict[str, object]]] = {}
    for cell in cells:
        per_coupling.setdefault(str(cell["coupling"]), []).append(cell)
    verdicts = {
        coupling: {
            "projects": len(group),
            "degenerate_projects": sum(1 for cell in group if cell["degenerate"]),
            "worst_median_support": min(float(c["median_support_fraction"]) for c in group),
            "median_mass_outside_top_k": median(
                [float(c["median_mass_outside_top_k"]) for c in group]
            ),
        }
        for coupling, group in sorted(per_coupling.items())
    }
    return {
        "experiment_id": "EXP-GPA-COUPLING",
        "degeneracy_threshold": DEGENERACY_THRESHOLD,
        "cells": cells,
        "verdicts": verdicts,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# EXP-GPA-COUPLING — influence-field substrate under edge coupling",
        "",
        f"A field is called degenerate when its median support fraction is below "
        f"`{report['degeneracy_threshold']}`: fewer than that share of project "
        "entities carry any query-conditioned mass, so no far-field "
        "representation has anything to encode.",
        "",
        "| project | coupling | tasks | median support | min support | median mass outside top-64 | effective entities | degenerate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for cell in report["cells"]:  # type: ignore[index]
        lines.append(
            f"| {cell['project']} | {cell['coupling']} | {cell['tasks']} | "
            f"{cell['median_support_fraction']:.4%} | {cell['min_support_fraction']:.4%} | "
            f"{cell['median_mass_outside_top_k']:.3e} | "
            f"{cell['median_effective_entities']:.1f} | "
            f"{'YES' if cell['degenerate'] else 'no'} |"
        )
    lines += ["", "## Verdict by coupling", "", "| coupling | degenerate projects | worst median support | median mass outside top-64 |", "| --- | ---: | ---: | ---: |"]
    for coupling, verdict in report["verdicts"].items():  # type: ignore[index]
        lines.append(
            f"| {coupling} | {verdict['degenerate_projects']}/{verdict['projects']} | "
            f"{verdict['worst_median_support']:.4%} | {verdict['median_mass_outside_top_k']:.3e} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    missing = [n for n in GRAPH_NAMES if not (REAL_GRAPH_DIR / f"{n}.json").exists()]
    if missing:
        print(f"SKIP: missing frozen Phase 1 graphs: {', '.join(missing)}")
        return
    rows: list[dict[str, object]] = []
    for name in GRAPH_NAMES:
        rows.extend(evaluate_graph(name))
    report = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps({"rows": rows, **report}, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
