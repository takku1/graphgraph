from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
ANSWERABILITY_CSV = OUT / "real_project_answerability_limit.csv"
PACKET_BALANCE_CSV = OUT / "real_project_packet_balance.csv"
RESULTS_CSV = OUT / "planner_fit_results.csv"
SUMMARY_MD = OUT / "planner_fit_report.md"


@dataclass(frozen=True)
class FitRow:
    policy: str
    scope: str
    answerable: int
    cases: int
    avg_tokens: float
    premium_vs_oracle_pct: float
    notes: str


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def truthy(value: object) -> bool:
    return str(value).lower() == "true"


def avg(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def pct(numerator: float, denominator: float) -> float:
    return numerator / denominator * 100.0 if denominator else 0.0


def case_key(row: dict[str, str]) -> tuple[str, str]:
    return row["project"], row["query_class"]


def answerable_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if truthy(row.get("answerable"))]


def cheapest_answerable_by_case(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in answerable_rows(rows):
        grouped[case_key(row)].append(row)
    winners: dict[tuple[str, str], dict[str, str]] = {}
    for key, items in grouped.items():
        winners[key] = min(items, key=lambda row: (float(row["tokens"]), int(row["hops"]), row["packet"], row["candidate"]))
    return winners


def selected_by_candidate(rows: list[dict[str, str]], candidate: str) -> dict[tuple[str, str], dict[str, str]]:
    return {case_key(row): row for row in rows if row["candidate"] == candidate}


def candidate_names(rows: list[dict[str, str]]) -> list[str]:
    return sorted({row["candidate"] for row in rows})


def evaluate_selection(
    name: str,
    scope: str,
    selected: dict[tuple[str, str], dict[str, str]],
    oracle: dict[tuple[str, str], dict[str, str]],
    notes: str,
) -> FitRow:
    keys = sorted(oracle)
    present = [selected[key] for key in keys if key in selected]
    answerable = sum(1 for row in present if truthy(row.get("answerable")))
    tokens = avg([float(row["tokens"]) for row in present])
    oracle_tokens = avg([float(oracle[key]["tokens"]) for key in keys])
    return FitRow(
        policy=name,
        scope=scope,
        answerable=answerable,
        cases=len(keys),
        avg_tokens=tokens,
        premium_vs_oracle_pct=((tokens / oracle_tokens) - 1.0) * 100.0 if oracle_tokens else 0.0,
        notes=notes,
    )


def best_global_candidate(rows: list[dict[str, str]], oracle: dict[tuple[str, str], dict[str, str]]) -> FitRow:
    fits: list[FitRow] = []
    for candidate in candidate_names(rows):
        selected = selected_by_candidate(rows, candidate)
        fit = evaluate_selection(candidate, "global_candidate", selected, oracle, "same candidate for every query class")
        if fit.answerable == fit.cases:
            fits.append(fit)
    return min(fits, key=lambda fit: (fit.avg_tokens, fit.policy))


def best_per_class_candidate(rows: list[dict[str, str]], oracle: dict[tuple[str, str], dict[str, str]]) -> tuple[FitRow, dict[str, str]]:
    by_class = sorted({row["query_class"] for row in rows})
    selected: dict[tuple[str, str], dict[str, str]] = {}
    choices: dict[str, str] = {}
    for query_class in by_class:
        class_rows = [row for row in rows if row["query_class"] == query_class]
        class_oracle = {key: value for key, value in oracle.items() if key[1] == query_class}
        best: FitRow | None = None
        best_candidate = ""
        for candidate in candidate_names(class_rows):
            candidate_selected = selected_by_candidate(class_rows, candidate)
            fit = evaluate_selection(candidate, query_class, candidate_selected, class_oracle, "per-query-class candidate")
            if fit.answerable != fit.cases:
                continue
            if best is None or (fit.avg_tokens, fit.policy) < (best.avg_tokens, best.policy):
                best = fit
                best_candidate = candidate
        if best_candidate:
            choices[query_class] = best_candidate
            selected.update(selected_by_candidate(class_rows, best_candidate))
    return (
        evaluate_selection(
            "per_class_candidate_fit",
            "per_class",
            selected,
            oracle,
            "; ".join(f"{qc}={candidate}" for qc, candidate in sorted(choices.items())),
        ),
        choices,
    )


def best_budget_fit(rows: list[dict[str, str]], oracle: dict[tuple[str, str], dict[str, str]]) -> tuple[FitRow, FitRow]:
    budget_candidates = sorted({row["candidate"] for row in rows if row["candidate"].startswith("current_budget_")})
    global_fits = []
    for candidate in budget_candidates:
        fit = evaluate_selection(candidate, "global_budget", selected_by_candidate(rows, candidate), oracle, "same current-policy budget for all classes")
        if fit.answerable == fit.cases:
            global_fits.append(fit)
    global_best = min(global_fits, key=lambda fit: (fit.avg_tokens, fit.policy))

    selected: dict[tuple[str, str], dict[str, str]] = {}
    choices: dict[str, str] = {}
    for query_class in sorted({row["query_class"] for row in rows}):
        class_rows = [row for row in rows if row["query_class"] == query_class]
        class_oracle = {key: value for key, value in oracle.items() if key[1] == query_class}
        best: FitRow | None = None
        best_candidate = ""
        for candidate in budget_candidates:
            fit = evaluate_selection(candidate, query_class, selected_by_candidate(class_rows, candidate), class_oracle, "per-query-class budget")
            if fit.answerable != fit.cases:
                continue
            if best is None or (fit.avg_tokens, fit.policy) < (best.avg_tokens, best.policy):
                best = fit
                best_candidate = candidate
        if best_candidate:
            choices[query_class] = best_candidate
            selected.update(selected_by_candidate(class_rows, best_candidate))
    per_class_best = evaluate_selection(
        "per_class_budget_fit",
        "per_class_budget",
        selected,
        oracle,
        "; ".join(f"{qc}={candidate.removeprefix('current_budget_')}" for qc, candidate in sorted(choices.items())),
    )
    return global_best, per_class_best


def packet_balance_cases(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, dict[str, str]]]:
    cases: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        if row.get("status") != "ok":
            continue
        cases[(row["project"], row["query_class"])][row["packet"]] = row
    return cases


def packet_threshold_fits(packet_rows: list[dict[str, str]]) -> list[FitRow]:
    cases = packet_balance_cases(packet_rows)
    usable = {key: packets for key, packets in cases.items() if "gg_max" in packets and "semantic_arrow" in packets}
    if not usable:
        return []
    oracle_tokens = avg([min(float(p["tokens"]) for p in packets.values()) for packets in usable.values()])
    fits: list[FitRow] = []
    for threshold in range(0, 33):
        selected_tokens = []
        semantic_choices = 0
        for packets in usable.values():
            gg = packets["gg_max"]
            semantic = packets["semantic_arrow"]
            if float(gg["edges"]) <= threshold:
                selected_tokens.append(float(semantic["tokens"]))
                semantic_choices += 1
            else:
                selected_tokens.append(float(gg["tokens"]))
        tokens = avg(selected_tokens)
        fits.append(
            FitRow(
                policy=f"edge_threshold_T{threshold}",
                scope="packet_selector",
                answerable=len(usable),
                cases=len(usable),
                avg_tokens=tokens,
                premium_vs_oracle_pct=((tokens / oracle_tokens) - 1.0) * 100.0 if oracle_tokens else 0.0,
                notes=f"semantic_arrow when edges <= {threshold}; semantic choices={semantic_choices}",
            )
        )
    return fits


def sigmoid_packet_fits(packet_rows: list[dict[str, str]]) -> list[FitRow]:
    cases = packet_balance_cases(packet_rows)
    usable = {key: packets for key, packets in cases.items() if "gg_max" in packets and "semantic_arrow" in packets}
    if not usable:
        return []
    oracle_tokens = avg([min(float(p["tokens"]) for p in packets.values()) for packets in usable.values()])
    fits: list[FitRow] = []
    for midpoint in [x / 2 for x in range(0, 21)]:
        for sharpness in (0.5, 1.0, 2.0, 4.0, 8.0):
            expected_tokens = []
            hard_tokens = []
            semantic_mass = 0.0
            hard_semantic = 0
            for packets in usable.values():
                gg = packets["gg_max"]
                semantic = packets["semantic_arrow"]
                edges = float(gg["edges"])
                # High probability near zero edges, fast decay as evidence becomes structural.
                exponent = sharpness * (edges - midpoint)
                if exponent > 60:
                    p_semantic = 0.0
                elif exponent < -60:
                    p_semantic = 1.0
                else:
                    p_semantic = 1.0 / (1.0 + math.exp(exponent))
                semantic_mass += p_semantic
                expected_tokens.append(p_semantic * float(semantic["tokens"]) + (1.0 - p_semantic) * float(gg["tokens"]))
                if p_semantic >= 0.5:
                    hard_tokens.append(float(semantic["tokens"]))
                    hard_semantic += 1
                else:
                    hard_tokens.append(float(gg["tokens"]))
            tokens = avg(hard_tokens)
            fits.append(
                FitRow(
                    policy=f"sigmoid_mid{midpoint:g}_k{sharpness:g}",
                    scope="activation_packet_selector",
                    answerable=len(usable),
                    cases=len(usable),
                    avg_tokens=tokens,
                    premium_vs_oracle_pct=((tokens / oracle_tokens) - 1.0) * 100.0 if oracle_tokens else 0.0,
                    notes=(
                        f"hard avg from p>=0.5; expected_tokens={avg(expected_tokens):.1f}; "
                        f"semantic_mass={semantic_mass:.2f}; hard_semantic={hard_semantic}"
                    ),
                )
            )
    return fits


def linear_token_models(packet_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    by_packet: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in packet_rows:
        if row.get("status") == "ok":
            by_packet[row["packet"]].append(row)
    models: list[dict[str, object]] = []
    for packet, rows in sorted(by_packet.items()):
        x_rows = [(1.0, float(row["nodes"]), float(row["edges"])) for row in rows]
        y = [float(row["tokens"]) for row in rows]
        coeffs = solve_normal_equation(x_rows, y)
        predictions = [coeffs[0] + coeffs[1] * x[1] + coeffs[2] * x[2] for x in x_rows]
        mean_y = avg(y)
        ss_res = sum((actual - pred) ** 2 for actual, pred in zip(y, predictions))
        ss_tot = sum((actual - mean_y) ** 2 for actual in y)
        models.append(
            {
                "packet": packet,
                "intercept": coeffs[0],
                "node_coef": coeffs[1],
                "edge_coef": coeffs[2],
                "r2": 1.0 - ss_res / ss_tot if ss_tot else 1.0,
                "mean_abs_error": avg([abs(actual - pred) for actual, pred in zip(y, predictions)]),
                "cases": len(rows),
            }
        )
    return models


def solve_normal_equation(x_rows: list[tuple[float, float, float]], y: list[float]) -> tuple[float, float, float]:
    xtx = [[0.0 for _ in range(3)] for _ in range(3)]
    xty = [0.0, 0.0, 0.0]
    for x, target in zip(x_rows, y):
        for i in range(3):
            xty[i] += x[i] * target
            for j in range(3):
                xtx[i][j] += x[i] * x[j]
    return solve_3x3(xtx, xty)


def solve_3x3(matrix: list[list[float]], vector: list[float]) -> tuple[float, float, float]:
    a = [row[:] + [value] for row, value in zip(matrix, vector)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-9:
            return (0.0, 0.0, 0.0)
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        for item in range(col, 4):
            a[col][item] /= scale
        for row in range(3):
            if row == col:
                continue
            factor = a[row][col]
            for item in range(col, 4):
                a[row][item] -= factor * a[col][item]
    return a[0][3], a[1][3], a[2][3]


def write_results(fits: list[FitRow], token_models: list[dict[str, object]], per_class_choices: dict[str, str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["policy", "scope", "answerable", "cases", "avg_tokens", "premium_vs_oracle_pct", "notes"],
        )
        writer.writeheader()
        for fit in fits:
            writer.writerow(
                {
                    "policy": fit.policy,
                    "scope": fit.scope,
                    "answerable": fit.answerable,
                    "cases": fit.cases,
                    "avg_tokens": f"{fit.avg_tokens:.3f}",
                    "premium_vs_oracle_pct": f"{fit.premium_vs_oracle_pct:.3f}",
                    "notes": fit.notes,
                }
            )

    oracle = next(fit for fit in fits if fit.policy == "oracle_cheapest_answerable")
    current = next(fit for fit in fits if fit.policy == "current_default")
    answerability_scopes = {"runtime", "global_candidate", "global_budget", "per_class", "per_class_budget"}
    best_answerability = min(
        (fit for fit in fits if fit.scope in answerability_scopes and fit.answerable == fit.cases),
        key=lambda fit: (fit.avg_tokens, fit.policy),
    )
    packet_fits = [fit for fit in fits if fit.scope in {"packet_selector", "activation_packet_selector"}]
    best_packet = min(packet_fits, key=lambda fit: (fit.avg_tokens, fit.policy)) if packet_fits else None

    lines = [
        "# Planner Fit Benchmark",
        "",
        "This report fits simple planner families against saved empirical rows.",
        "",
        "The oracle is the cheapest raw Graph.expand candidate that contains each",
        "synthetic fixture's exact structural evidence. It is a planner lower bound,",
        "not the production retrieval gate or a model-answering result.",
        "",
        "## Summary",
        "",
        f"- Oracle cheapest-answerable avg tokens: `{oracle.avg_tokens:.1f}`",
        f"- Current default avg tokens: `{current.avg_tokens:.1f}` (`{current.premium_vs_oracle_pct:.3f}%` over oracle)",
        f"- Best fully answerable planner fit: `{best_answerability.policy}` at `{best_answerability.avg_tokens:.1f}` tokens (`{best_answerability.premium_vs_oracle_pct:.3f}%` over answerability oracle)",
    ]
    if best_packet:
        lines.append(f"- Best packet selector fit: `{best_packet.policy}` at `{best_packet.avg_tokens:.1f}` tokens (`{best_packet.notes}`)")
    if per_class_choices:
        lines.append("- Per-class candidate fit: " + ", ".join(f"`{qc}` -> `{candidate}`" for qc, candidate in sorted(per_class_choices.items())))
    lines.extend(
        [
            "",
            "## Fitted Policies",
            "",
            "| Policy | Scope | Answerable | Avg tokens | Premium vs oracle | Notes |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for fit in sorted(fits, key=lambda item: (item.scope, item.avg_tokens, item.policy)):
        lines.append(
            f"| `{fit.policy}` | {fit.scope} | {fit.answerable}/{fit.cases} | "
            f"{fit.avg_tokens:.1f} | {fit.premium_vs_oracle_pct:.3f}% | {fit.notes} |"
        )

    lines.extend(
        [
            "",
            "## Linear Token Surface",
            "",
            "Least-squares fit: `tokens = intercept + node_coef * nodes + edge_coef * edges`.",
            "",
            "| Packet | Intercept | Node coef | Edge coef | R2 | Mean abs error | Cases |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for model in sorted(token_models, key=lambda item: str(item["packet"])):
        lines.append(
            f"| `{model['packet']}` | {float(model['intercept']):.2f} | "
            f"{float(model['node_coef']):.3f} | {float(model['edge_coef']):.3f} | "
            f"{float(model['r2']):.4f} | {float(model['mean_abs_error']):.1f} | {model['cases']} |"
        )

    lines.extend(
        [
            "",
            "## Read",
            "",
            "- The fixture oracle defines a raw-expansion lower bound; production behavior is gated separately.",
            "- The packet selector fit tests the piecewise rule and a smooth activation-style rule over edge count.",
            "- If the best activation fit collapses to the same hard edge threshold, there is no current evidence that a softer packet selector buys tokens.",
            "- A lower per-class candidate fit is a planner-change candidate only if its semantics match the query class, not merely because the synthetic oracle accepts it.",
            "",
            f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    answer_rows = read_csv(ANSWERABILITY_CSV)
    packet_rows = read_csv(PACKET_BALANCE_CSV)
    if not answer_rows:
        SUMMARY_MD.write_text(
            "# Planner Fit Benchmark\n\n"
            "Skipped: answerability CSV missing. Run `real_project_answerability_limit.py` first.\n",
            encoding="utf-8",
        )
        print(SUMMARY_MD.read_text(encoding="utf-8"))
        return

    oracle = cheapest_answerable_by_case(answer_rows)
    oracle_fit = FitRow(
        "oracle_cheapest_answerable",
        "lower_bound",
        len(oracle),
        len(oracle),
        avg([float(row["tokens"]) for row in oracle.values()]),
        0.0,
        "cheapest answerable candidate per project/query_class",
    )
    current_fit = evaluate_selection("current_default", "runtime", selected_by_candidate(answer_rows, "current_default"), oracle, "current planner output")
    global_best = best_global_candidate(answer_rows, oracle)
    per_class_best, per_class_choices = best_per_class_candidate(answer_rows, oracle)
    global_budget, per_class_budget = best_budget_fit(answer_rows, oracle)
    packet_fits = packet_threshold_fits(packet_rows)
    sigmoid_fits = sigmoid_packet_fits(packet_rows)
    token_models = linear_token_models(packet_rows)

    selected_packet_fits: list[FitRow] = []
    if packet_fits:
        best_threshold = min(packet_fits, key=lambda fit: (fit.avg_tokens, fit.policy))
        selected_packet_fits.append(best_threshold)
        selected_packet_fits.extend(fit for fit in packet_fits[:6] if fit.policy != best_threshold.policy)
    if sigmoid_fits:
        selected_packet_fits.append(min(sigmoid_fits, key=lambda fit: (fit.avg_tokens, fit.policy)))

    fits = [
        oracle_fit,
        current_fit,
        global_best,
        per_class_best,
        global_budget,
        per_class_budget,
        *selected_packet_fits,
    ]
    write_results(fits, token_models, per_class_choices)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    run()
