from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out" / "protocol"
PROTOCOL_CSV = OUT / "protocol_results.csv"
MANIFEST = ROOT / "benchmark_manifest.json"
RESULTS_CSV = OUT / "adaptive_threshold_sweep.csv"
RESULTS_MD = OUT / "adaptive_threshold_sweep.md"


READABLE_FORMATS = ("semantic_arrow", "sql")
COMPACT_FORMAT = "gg_max"
THRESHOLDS = tuple(range(0, 41))


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def avg(rows: list[dict], key: str) -> float:
    return sum(float(row[key]) for row in rows) / max(1, len(rows))


def strategy_for(query_class: str, fmt: str) -> str:
    hop = 2 if query_class in {"blast_radius", "multi_hop_path"} else 1
    return f"graph_{hop}hop_{fmt}"


def pass_threshold(rows: list[dict], thresholds: dict) -> bool:
    return (
        avg(rows, "node_recall") >= thresholds["min_node_recall"]
        and avg(rows, "edge_recall") >= thresholds["min_edge_recall"]
        and avg(rows, "irrelevant_context_ratio") <= thresholds["max_irrelevant_context_ratio"]
    )


def quality(rows: list[dict]) -> float:
    return (
        0.45 * avg(rows, "node_recall")
        + 0.40 * avg(rows, "edge_recall")
        + 0.15 * avg(rows, "path_recall")
    )


def run() -> tuple[list[dict], list[dict]]:
    if not PROTOCOL_CSV.exists():
        raise SystemExit(f"Missing {PROTOCOL_CSV}; run protocol_benchmark.py first.")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    thresholds = manifest["thresholds"]
    rows = read_csv(PROTOCOL_CSV)

    by_task: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_task[(row["corpus"], row["query_class"])][row["strategy"]] = row

    policy_rows: list[dict] = []
    selected_rows: list[dict] = []
    for readable in READABLE_FORMATS:
        for threshold in THRESHOLDS:
            chosen = []
            missing = []
            readable_count = 0
            compact_count = 0
            for (corpus, query_class), strategies in sorted(by_task.items()):
                compact_name = strategy_for(query_class, COMPACT_FORMAT)
                readable_name = strategy_for(query_class, readable)
                compact = strategies.get(compact_name)
                readable_row = strategies.get(readable_name)
                if compact is None or readable_row is None:
                    missing.append(f"{corpus}/{query_class}")
                    continue

                compact_edges = int(float(compact["retrieved_edges"]))
                if compact_edges <= threshold:
                    selected = dict(readable_row)
                    readable_count += 1
                else:
                    selected = dict(compact)
                    compact_count += 1
                selected["policy"] = f"{readable}_lte_{threshold}_else_{COMPACT_FORMAT}"
                selected["readable_format"] = readable
                selected["edge_threshold"] = threshold
                selected["decision_edges"] = compact_edges
                chosen.append(selected)
                selected_rows.append(selected)

            if not chosen:
                continue

            all_compact = []
            for (_corpus, query_class), strategies in sorted(by_task.items()):
                row = strategies.get(strategy_for(query_class, COMPACT_FORMAT))
                if row is not None:
                    all_compact.append(row)

            avg_tokens = avg(chosen, "tokens")
            compact_tokens = avg(all_compact, "tokens")
            policy_rows.append(
                {
                    "readable_format": readable,
                    "edge_threshold": threshold,
                    "policy": f"{readable}_lte_{threshold}_else_{COMPACT_FORMAT}",
                    "avg_tokens": round(avg_tokens, 3),
                    "token_premium_vs_all_gg_max_pct": round(((avg_tokens / compact_tokens) - 1.0) * 100.0, 3),
                    "quality": round(quality(chosen), 4),
                    "node_recall": round(avg(chosen, "node_recall"), 4),
                    "edge_recall": round(avg(chosen, "edge_recall"), 4),
                    "path_recall": round(avg(chosen, "path_recall"), 4),
                    "irrelevant_context_ratio": round(avg(chosen, "irrelevant_context_ratio"), 4),
                    "readable_choices": readable_count,
                    "compact_choices": compact_count,
                    "passed": pass_threshold(chosen, thresholds),
                    "missing": "; ".join(missing),
                }
            )
    return policy_rows, selected_rows


def write(policy_rows: list[dict], selected_rows: list[dict]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(policy_rows[0].keys()))
        writer.writeheader()
        writer.writerows(policy_rows)

    passing = [row for row in policy_rows if row["passed"]]
    best_by_tokens = min(passing, key=lambda r: (float(r["avg_tokens"]), abs(int(r["edge_threshold"]) - 3))) if passing else None
    nearest_three = [
        row for row in policy_rows
        if row["passed"] and int(row["edge_threshold"]) == 3
    ]

    lines = [
        "# Adaptive Edge-Threshold Sweep",
        "",
        "Policy tested: use a readable packet when the compact candidate has `retrieved_edges <= T`; otherwise use `gg_max`.",
        "",
        "This is not live model scoring. It is a min-max proxy over existing protocol benchmark rows: tokens, retrieval recall, path recall, and irrelevant context.",
        "",
        "## Best Passing Policy",
        "",
    ]
    if best_by_tokens:
        lines.extend([
            f"- Policy: `{best_by_tokens['policy']}`",
            f"- Avg tokens: `{best_by_tokens['avg_tokens']}`",
            f"- Token premium vs all-`gg_max`: `{best_by_tokens['token_premium_vs_all_gg_max_pct']}%`",
            f"- Quality: `{best_by_tokens['quality']}`",
            f"- Node recall: `{best_by_tokens['node_recall']}`",
            f"- Edge recall: `{best_by_tokens['edge_recall']}`",
            f"- Irrelevant context ratio: `{best_by_tokens['irrelevant_context_ratio']}`",
            "",
        ])
    else:
        lines.extend(["No passing policy found under the manifest thresholds.", ""])

    lines.extend([
        "## Threshold 3 Check",
        "",
        "| Readable format | Threshold | Avg tokens | Premium vs all-gg_max | Quality | Node recall | Edge recall | Irrelevant ratio | Readable choices | Compact choices |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in nearest_three:
        lines.append(
            f"| {row['readable_format']} | {row['edge_threshold']} | {row['avg_tokens']} | "
            f"{row['token_premium_vs_all_gg_max_pct']}% | {row['quality']} | "
            f"{row['node_recall']} | {row['edge_recall']} | {row['irrelevant_context_ratio']} | "
            f"{row['readable_choices']} | {row['compact_choices']} |"
        )

    lines.extend([
        "",
        "## Passing Frontier",
        "",
        "| Readable format | Threshold | Avg tokens | Premium vs all-gg_max | Quality | Readable choices | Compact choices |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in sorted(passing, key=lambda r: (float(r["avg_tokens"]), r["readable_format"], int(r["edge_threshold"])))[:20]:
        lines.append(
            f"| {row['readable_format']} | {row['edge_threshold']} | {row['avg_tokens']} | "
            f"{row['token_premium_vs_all_gg_max_pct']}% | {row['quality']} | "
            f"{row['readable_choices']} | {row['compact_choices']} |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- If threshold `3` has low premium, it is a reasonable first readability escape hatch.",
        "- If threshold `3` never chooses a readable packet, the tested corpus has larger retrieved subgraphs and the useful threshold is higher.",
        "- This benchmark cannot prove model comprehension. It only identifies cheap candidate thresholds to send into live answer scoring.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    policy_rows, selected_rows = run()
    if not policy_rows:
        raise SystemExit("No policy rows generated.")
    write(policy_rows, selected_rows)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
