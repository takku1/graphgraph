from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph import Edge, Graph, Node  # noqa: E402
from graphgraph.research.attention_field import (  # noqa: E402
    Hierarchy,
    compile_greedy_cover,
    compile_optimal_cover,
    evaluate_cover,
    evaluate_top_k,
    exact_influence_field,
)

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "global_attention"


def fixture() -> tuple[Graph, Hierarchy]:
    labels = "abcdefgh"
    graph = Graph(nodes={label: Node(label, label, "function", f"src/{label}.py") for label in labels})
    graph.edges.extend(
        [
            Edge("a", "b", "calls"),
            Edge("b", "c", "calls"),
            Edge("c", "d", "calls"),
            Edge("d", "a", "calls"),
            Edge("d", "e", "calls", confidence=0.8),
            Edge("e", "f", "calls"),
            Edge("f", "g", "calls"),
            Edge("g", "h", "calls"),
            Edge("h", "e", "calls"),
        ]
    )
    hierarchy = Hierarchy(
        {
            "root": ("left", "right"),
            "left": ("left_near", "left_far"),
            "right": ("right_near", "right_far"),
            "left_near": ("a", "b"),
            "left_far": ("c", "d"),
            "right_near": ("e", "f"),
            "right_far": ("g", "h"),
        },
        ("root",),
    )
    return graph, hierarchy


def unbalanced_hierarchy() -> Hierarchy:
    return Hierarchy(
        {
            "root": ("wide", "narrow"),
            "wide": ("a", "b", "c", "d"),
            "narrow": ("e", "f"),
        },
        ("root",),
    )


def run() -> dict[str, object]:
    graph, hierarchy = fixture()
    field = exact_influence_field(graph, {"a": 1.0})
    rows = []
    previous_optimal = float("inf")
    gates = {
        "coverage": True,
        "mass_conservation": True,
        "optimal_monotone_l2": True,
        "greedy_bounded_by_optimum": True,
        "leaf_exactness": True,
    }
    for budget in range(1, len(hierarchy.leaves) + 1):
        optimal_plan = compile_optimal_cover(hierarchy, field, budget)
        greedy_plan = compile_greedy_cover(hierarchy, field, budget)
        optimal = evaluate_cover(hierarchy, field, optimal_plan)
        greedy = evaluate_cover(hierarchy, field, greedy_plan)
        top_k = evaluate_top_k(field, budget)
        gates["coverage"] &= bool(optimal["coverage"]["valid"] and greedy["coverage"]["valid"])
        gates["mass_conservation"] &= optimal["mass_error"] <= 1e-12 and greedy["mass_error"] <= 1e-12
        gates["optimal_monotone_l2"] &= optimal["l2_error"] <= previous_optimal + 1e-15
        gates["greedy_bounded_by_optimum"] &= greedy["l2_error"] + 1e-15 >= optimal["l2_error"]
        previous_optimal = optimal["l2_error"]
        rows.append(
            {
                "budget": budget,
                "optimal_units": optimal_plan.representation_units,
                "greedy_units": greedy_plan.representation_units,
                "optimal_cover": list(optimal_plan.cover),
                "greedy_cover": list(greedy_plan.cover),
                "optimal_l1": optimal["l1_error"],
                "optimal_l2": optimal["l2_error"],
                "greedy_l2": greedy["l2_error"],
                "top_k_l2": top_k["l2_error"],
                "top_k_coverage": top_k["coverage"],
                "optimal_rwc": optimal["resolution_weighted_coverage"],
            }
        )
    gates["leaf_exactness"] = rows[-1]["optimal_l2"] <= 1e-15

    adversarial = unbalanced_hierarchy()
    greedy_counterexample = {
        "a": 0.1576244644117335,
        "b": 0.2572940158328786,
        "c": 0.20904766318798926,
        "d": 0.00009180314777116714,
        "e": 0.07350767030705409,
        "f": 0.30243438311257337,
    }
    optimal_plan = compile_optimal_cover(adversarial, greedy_counterexample, 5)
    greedy_plan = compile_greedy_cover(adversarial, greedy_counterexample, 5)
    optimal_result = evaluate_cover(adversarial, greedy_counterexample, optimal_plan)
    greedy_result = evaluate_cover(adversarial, greedy_counterexample, greedy_plan)
    metric_counterexample = {
        "a": 0.021628600730411483,
        "b": 0.0011157563921729348,
        "c": 0.5329719140000019,
        "d": 0.11655287068542892,
        "e": 0.32545659389402826,
        "f": 0.0022742642979565754,
    }
    coarse = evaluate_cover(
        adversarial, metric_counterexample, compile_optimal_cover(adversarial, metric_counterexample, 1)
    )
    refined = evaluate_cover(
        adversarial, metric_counterexample, compile_optimal_cover(adversarial, metric_counterexample, 2)
    )
    gates["greedy_counterexample_detected"] = greedy_result["l2_error"] > optimal_result["l2_error"] * 1.4
    gates["metric_non_equivalence_detected"] = (
        refined["l2_error"] < coarse["l2_error"] and refined["l1_error"] > coarse["l1_error"]
    )
    counterexamples = {
        "greedy": {
            "budget": 5,
            "optimal_cover": list(optimal_plan.cover),
            "greedy_cover": list(greedy_plan.cover),
            "optimal_l2": optimal_result["l2_error"],
            "greedy_l2": greedy_result["l2_error"],
            "relative_regret": greedy_result["l2_error"] / optimal_result["l2_error"] - 1.0,
        },
        "metric": {
            "coarse_l1": coarse["l1_error"],
            "refined_l1": refined["l1_error"],
            "coarse_l2": coarse["l2_error"],
            "refined_l2": refined["l2_error"],
        },
    }
    return {
        "field": field,
        "rows": rows,
        "counterexamples": counterexamples,
        "gates": gates,
        "ok": all(gates.values()),
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Global Project Attention — Phase 0 Oracle",
        "",
        "This is a mathematical ceiling on one eight-leaf hierarchy. It uses oracle cell mass and",
        "therefore does not support H1 or production promotion.",
        "",
        "## Gates",
        "",
    ]
    for gate, ok in report["gates"].items():
        lines.append(f"- `{gate}`: `{'PASS' if ok else 'FAIL'}`")
    lines.extend(
        [
            "",
            "| Units | Optimal L2 | Greedy L2 | Top-k L2 | Top-k coverage | Optimal RWC |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["rows"]:
        lines.append(
            f"| {row['budget']} | {row['optimal_l2']:.8f} | {row['greedy_l2']:.8f} | "
            f"{row['top_k_l2']:.8f} | {row['top_k_coverage']:.3f} | {row['optimal_rwc']:.6f} |"
        )
    greedy = report["counterexamples"]["greedy"]
    metric = report["counterexamples"]["metric"]
    lines.extend(
        [
            "",
            "## Falsifying counterexamples",
            "",
            f"- One-step greedy relative L2 regret: `{greedy['relative_regret']:.2%}` at five units.",
            f"- Optimal cover: `{greedy['optimal_cover']}`; greedy cover: `{greedy['greedy_cover']}`.",
            f"- L2-guided refinement lowers L2 `{metric['coarse_l2']:.8f} -> {metric['refined_l2']:.8f}` ",
            f"  while L1 rises `{metric['coarse_l1']:.8f} -> {metric['refined_l1']:.8f}`.",
        ]
    )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- GRC=1 is a cover identity, not evidence of useful reasoning.",
            "- Exhaustive L2 is the hierarchy-specific mathematical ceiling under uniform cell reconstruction.",
            "- Greedy refinement is an algorithmic approximation to that ceiling.",
            "- Top-k is not a global representation because omitted entities carry no representation or mass.",
            "- H1 remains pending until equal serialized-token tests use estimates unavailable to the oracle.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    report = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase0.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (OUT / "phase0.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    if not report["ok"]:
        raise SystemExit("Phase-0 oracle gates failed")


if __name__ == "__main__":
    main()
