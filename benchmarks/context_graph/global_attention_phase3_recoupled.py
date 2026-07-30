"""EXP-GPA-RECOUPLED / EXP-GPA-HYBRID-RESERVE: cover verdicts on a real field.

Phase 1 rejected the C1 cover formulas and the sweeps rejected the coefficient
family. `EXP-GPA-COUPLING` then showed the field feeding those covers is empty
on three of four projects, so neither verdict isolated the formula.

This re-runs both the C1 greedy cover (unit budgets) and the shipped
`hybrid_reserve_v1` (token budgets) with the evaluator, tasks, seeds, budgets,
and baselines held exactly at their Phase 1 values, exchanging only the edge
coupling. Gold task evidence enters after both packets are frozen, as before.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_attention_phase1 import (  # noqa: E402
    EXACTNESS_WEIGHT,
    GRAPH_NAMES,
    MAX_EXACT_RECALL_LOSS,
    MIN_RESOLUTION_GAIN,
    REAL_GRAPH_DIR,
    candidate_packet,
    load_any,
    make_tasks,
)

from graphgraph.graph.coupling import EDGE_COUPLINGS  # noqa: E402
from graphgraph.packets import estimate_tokens  # noqa: E402
from graphgraph.representation import (  # noqa: E402
    HybridRepresentationConfig,
    compile_hybrid_representation,
)
from graphgraph.research import (  # noqa: E402
    build_path_hierarchy,
    evaluate_expected_resolution,
    select_flat_nodes_at_token_budget,
)
from graphgraph.research.attention_field import influence_field  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "protocol"
REPORT_JSON = OUT / "global_attention_recoupled.json"
REPORT_MD = OUT / "global_attention_recoupled.md"

UNIT_BUDGETS = (16, 32, 64)
TOKEN_BUDGETS = (1024, 2048, 4096)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else float("nan")


def cover_rows(name: str, coupling: str) -> list[dict[str, object]]:
    """C1 greedy formula cover at fixed representation-unit budgets."""
    graph = load_any(REAL_GRAPH_DIR / f"{name}.json")
    hierarchy = build_path_hierarchy(graph, max_branching=8)
    rows: list[dict[str, object]] = []
    for task in make_tasks(graph):
        seed_mass = 1.0 / len(task.starts)
        field = influence_field(
            graph, {n: seed_mass for n in task.starts}, coupling=coupling
        )
        for budget in UNIT_BUDGETS:
            plan, packet = candidate_packet(
                graph, hierarchy, field, budget, exactness_weight=EXACTNESS_WEIGHT
            )
            tokens = estimate_tokens(packet)
            flat_nodes = select_flat_nodes_at_token_budget(graph, field, tokens)
            evidence = evaluate_expected_resolution(
                hierarchy.hierarchy, plan, task.expected_nodes
            )
            flat_recall = len(set(flat_nodes) & task.expected_nodes) / max(
                1, len(task.expected_nodes)
            )
            rows.append(
                {
                    "arm": "C1-cover",
                    "project": name,
                    "coupling": coupling,
                    "budget": budget,
                    "tokens": tokens,
                    "resolution_recall": evidence["resolution_recall"],
                    "exact_recall": evidence["exact_recall"],
                    "flat_exact_recall": flat_recall,
                    "resolution_gain": evidence["resolution_recall"] - flat_recall,
                    "exact_recall_loss": flat_recall - evidence["exact_recall"],
                }
            )
    return rows


def reserve_rows(name: str, coupling: str) -> list[dict[str, object]]:
    """The shipped hybrid_reserve_v1 at token budgets, versus equal-token flat."""
    graph = load_any(REAL_GRAPH_DIR / f"{name}.json")
    rows: list[dict[str, object]] = []
    for task in make_tasks(graph):
        seed_mass = 1.0 / len(task.starts)
        seeds = {n: seed_mass for n in task.starts}
        field = influence_field(graph, seeds, coupling=coupling)
        for budget in TOKEN_BUDGETS:
            started = time.perf_counter()
            try:
                result = compile_hybrid_representation(
                    graph,
                    seeds,
                    config=HybridRepresentationConfig(
                        token_budget=budget, coupling=coupling
                    ),
                )
            except ValueError:
                continue
            compile_ms = (time.perf_counter() - started) * 1000.0
            tokens = estimate_tokens(result.packet)
            flat_nodes = select_flat_nodes_at_token_budget(graph, field, tokens)

            expected = list(dict.fromkeys(task.expected_nodes))
            denominator = max(1, len(expected))
            exact_recall = len(set(expected) & set(result.exact_nodes)) / denominator
            flat_recall = len(set(expected) & set(flat_nodes)) / denominator
            # Preregistered primary metric: resolution recall, which credits an
            # aggregate cell with 1/|cell| rather than nothing. The flat
            # baseline has no aggregates, so its resolution recall is its exact
            # recall -- scoring the reserve on exact recall alone would silently
            # discard the only thing it spends its residual budget on.
            resolution_recall = (
                sum(result.resolution_of(node_id) for node_id in expected) / denominator
            )
            rows.append(
                {
                    "arm": "hybrid-reserve",
                    "project": name,
                    "coupling": coupling,
                    "budget": budget,
                    "tokens": tokens,
                    "within_budget": bool(result.receipt["within_budget"]),
                    "exact_entities": result.receipt["exact_entities"],
                    "aggregate_cells": result.receipt["aggregate_cells"],
                    "aggregate_mass": result.receipt["aggregate_mass"],
                    "refinements": result.receipt["refinements"],
                    "exact_recall": exact_recall,
                    "resolution_recall": resolution_recall,
                    "flat_exact_recall": flat_recall,
                    "exact_recall_gain": exact_recall - flat_recall,
                    "resolution_gain": resolution_recall - flat_recall,
                    "compile_ms": compile_ms,
                }
            )
    return rows


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    cells: list[dict[str, object]] = []
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row["arm"]), str(row["project"]), str(row["coupling"]))
        groups.setdefault(key, []).append(row)

    for (arm, project, coupling), group in sorted(groups.items()):
        cell: dict[str, object] = {
            "arm": arm,
            "project": project,
            "coupling": coupling,
            "samples": len(group),
        }
        if arm == "C1-cover":
            cell["median_resolution_gain"] = _median(
                [float(r["resolution_gain"]) for r in group]
            )
            cell["max_exact_recall_loss"] = max(
                float(r["exact_recall_loss"]) for r in group
            )
        else:
            cell["median_resolution_gain"] = _median(
                [float(r["resolution_gain"]) for r in group]
            )
            cell["median_exact_recall_gain"] = _median(
                [float(r["exact_recall_gain"]) for r in group]
            )
            cell["median_aggregate_mass"] = _median(
                [float(r["aggregate_mass"]) for r in group]
            )
            cell["median_refinements"] = _median([float(r["refinements"]) for r in group])
            cell["median_compile_ms"] = _median([float(r["compile_ms"]) for r in group])
        cells.append(cell)

    verdicts: dict[str, dict[str, object]] = {}
    for arm in ("C1-cover", "hybrid-reserve"):
        for coupling in EDGE_COUPLINGS:
            group = [c for c in cells if c["arm"] == arm and c["coupling"] == coupling]
            if not group:
                continue
            if arm == "C1-cover":
                worst = min(float(c["median_resolution_gain"]) for c in group)
                loss = max(float(c["max_exact_recall_loss"]) for c in group)
                verdicts[f"{arm}/{coupling}"] = {
                    "worst_project_resolution_gain": worst,
                    "max_exact_recall_loss": loss,
                    "promotable": worst >= MIN_RESOLUTION_GAIN
                    and loss <= MAX_EXACT_RECALL_LOSS,
                }
            else:
                worst = min(float(c["median_resolution_gain"]) for c in group)
                verdicts[f"{arm}/{coupling}"] = {
                    "worst_project_resolution_gain": worst,
                    "worst_project_exact_recall_gain": min(
                        float(c["median_exact_recall_gain"]) for c in group
                    ),
                    "median_aggregate_mass": _median(
                        [float(c["median_aggregate_mass"]) for c in group]
                    ),
                    "promotable": worst >= MIN_RESOLUTION_GAIN,
                }
    return {
        "experiment_ids": ["EXP-GPA-RECOUPLED", "EXP-GPA-HYBRID-RESERVE"],
        "min_resolution_gain": MIN_RESOLUTION_GAIN,
        "max_exact_recall_loss": MAX_EXACT_RECALL_LOSS,
        "cells": cells,
        "verdicts": verdicts,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# EXP-GPA-RECOUPLED — cover verdicts on a non-degenerate field",
        "",
        f"Promotion needs worst-project gain >= `{report['min_resolution_gain']}` "
        f"with exact-recall loss <= `{report['max_exact_recall_loss']}`. Evaluator, "
        "tasks, seeds, budgets, and the equal-token flat baseline are unchanged "
        "from Phase 1; only the edge coupling differs.",
        "",
        "## C1 greedy cover (representation-unit budgets)",
        "",
        "| project | coupling | median resolution gain | max exact-recall loss |",
        "| --- | --- | ---: | ---: |",
    ]
    for cell in report["cells"]:  # type: ignore[index]
        if cell["arm"] != "C1-cover":
            continue
        lines.append(
            f"| {cell['project']} | {cell['coupling']} | "
            f"{cell['median_resolution_gain']:+.4f} | {cell['max_exact_recall_loss']:+.4f} |"
        )
    lines += [
        "",
        "## hybrid_reserve_v1 (token budgets)",
        "",
        "| project | coupling | median resolution gain | median exact-recall gain | median aggregate mass | median refinements | median compile ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cell in report["cells"]:  # type: ignore[index]
        if cell["arm"] != "hybrid-reserve":
            continue
        lines.append(
            f"| {cell['project']} | {cell['coupling']} | "
            f"{cell['median_resolution_gain']:+.4f} | "
            f"{cell['median_exact_recall_gain']:+.4f} | {cell['median_aggregate_mass']:.4f} | "
            f"{cell['median_refinements']:.1f} | {cell['median_compile_ms']:.0f} |"
        )
    lines += ["", "## Verdicts", "", "| arm / coupling | worst-project gain | promotable |", "| --- | ---: | :---: |"]
    for key, verdict in report["verdicts"].items():  # type: ignore[index]
        gain = verdict.get("worst_project_resolution_gain")
        if gain is None:
            gain = verdict.get("worst_project_exact_recall_gain")
        lines.append(
            f"| {key} | {float(gain):+.4f} | {'YES' if verdict['promotable'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    missing = [n for n in GRAPH_NAMES if not (REAL_GRAPH_DIR / f"{n}.json").exists()]
    if missing:
        print(f"SKIP: missing frozen Phase 1 graphs: {', '.join(missing)}")
        return
    rows: list[dict[str, object]] = []
    for name in GRAPH_NAMES:
        for coupling in ("directed", "symmetric"):
            rows.extend(cover_rows(name, coupling))
            rows.extend(reserve_rows(name, coupling))
    report = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps({"rows": rows, **report}, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
