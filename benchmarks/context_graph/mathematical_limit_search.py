from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out" / "protocol"
PROTOCOL_CSV = OUT / "protocol_results.csv"
MANIFEST = ROOT / "benchmark_manifest.json"
RESULTS_CSV = OUT / "mathematical_limit_search.csv"
RESULTS_MD = OUT / "mathematical_limit_search.md"


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def avg(rows: list[dict], key: str) -> float:
    return sum(float(row[key]) for row in rows) / max(1, len(rows))


def quality(rows: list[dict]) -> float:
    return (
        0.45 * avg(rows, "node_recall")
        + 0.40 * avg(rows, "edge_recall")
        + 0.15 * avg(rows, "path_recall")
    )


def passes(rows: list[dict], thresholds: dict) -> tuple[bool, str]:
    failures = []
    node_recall = avg(rows, "node_recall")
    edge_recall = avg(rows, "edge_recall")
    irrelevant = avg(rows, "irrelevant_context_ratio")
    negative_ok = avg(rows, "negative_ok")
    if node_recall < thresholds["min_node_recall"]:
        failures.append(f"node_recall {node_recall:.3f} < {thresholds['min_node_recall']}")
    if edge_recall < thresholds["min_edge_recall"]:
        failures.append(f"edge_recall {edge_recall:.3f} < {thresholds['min_edge_recall']}")
    if irrelevant > thresholds["max_irrelevant_context_ratio"]:
        failures.append(f"irrelevant {irrelevant:.3f} > {thresholds['max_irrelevant_context_ratio']}")
    if any(row["query_class"] == "negative_query" for row in rows) and negative_ok < 1.0:
        failures.append(f"negative_ok {negative_ok:.3f} < 1.0")
    return not failures, "; ".join(failures)


def summarize(rows: list[dict], thresholds: dict) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["query_class"], row["strategy"])].append(row)

    out = []
    for (query_class, strategy), items in sorted(grouped.items()):
        ok, failure = passes(items, thresholds)
        out.append(
            {
                "query_class": query_class,
                "strategy": strategy,
                "avg_tokens": round(avg(items, "tokens"), 3),
                "quality": round(quality(items), 4),
                "node_recall": round(avg(items, "node_recall"), 4),
                "edge_recall": round(avg(items, "edge_recall"), 4),
                "path_recall": round(avg(items, "path_recall"), 4),
                "irrelevant_context_ratio": round(avg(items, "irrelevant_context_ratio"), 4),
                "negative_ok": round(avg(items, "negative_ok"), 4),
                "retrieved_nodes": round(avg(items, "retrieved_nodes"), 3),
                "retrieved_edges": round(avg(items, "retrieved_edges"), 3),
                "passed": ok,
                "failure": failure,
            }
        )
    return out


def static_gg_max_strategy(query_class: str) -> str:
    hop = 2 if query_class in {"blast_radius", "multi_hop_path"} else 1
    return f"graph_{hop}hop_gg_max"


def write(rows: list[dict]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    passing = [row for row in rows if row["passed"]]
    query_classes = sorted({row["query_class"] for row in rows})
    winners = []
    for query_class in query_classes:
        candidates = [row for row in passing if row["query_class"] == query_class]
        if candidates:
            winners.append(min(candidates, key=lambda row: (float(row["avg_tokens"]), -float(row["quality"]))))

    gg_rows = []
    for query_class in query_classes:
        strategy = static_gg_max_strategy(query_class)
        match = next((row for row in rows if row["query_class"] == query_class and row["strategy"] == strategy), None)
        if match:
            gg_rows.append(match)

    winner_tokens = sum(float(row["avg_tokens"]) for row in winners)
    gg_tokens = sum(float(row["avg_tokens"]) for row in gg_rows)
    winner_avg = winner_tokens / max(1, len(winners))
    gg_avg = gg_tokens / max(1, len(gg_rows))

    lines = [
        "# Mathematical Limit Search",
        "",
        "This searches the existing protocol strategy set for the lowest-token passing strategy per query class.",
        "",
        "Unlike the earlier edge-threshold sweep, this treats `negative_ok` as a hard gate for `negative_query`.",
        "It is still a proxy benchmark, not live model comprehension scoring.",
        "",
        "## Current Proxy Lower Bound",
        "",
        f"- Avg tokens across query-class winners: `{winner_avg:.3f}`",
        f"- Avg tokens for current static `gg_max` routing: `{gg_avg:.3f}`",
        f"- Savings vs static `gg_max`: `{((1.0 - (winner_avg / gg_avg)) * 100.0):.3f}%`",
        "",
        "| Query class | Winner | Avg tokens | Quality | Node recall | Edge recall | Path recall | Irrelevant ratio | Negative OK | Avg edges |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in winners:
        lines.append(
            f"| {row['query_class']} | {row['strategy']} | {row['avg_tokens']} | {row['quality']} | "
            f"{row['node_recall']} | {row['edge_recall']} | {row['path_recall']} | "
            f"{row['irrelevant_context_ratio']} | {row['negative_ok']} | {row['retrieved_edges']} |"
        )

    lines.extend([
        "",
        "## Static gg_max Baseline",
        "",
        "| Query class | Strategy | Avg tokens | Quality | Negative OK | Passed | Failure |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ])
    for row in gg_rows:
        lines.append(
            f"| {row['query_class']} | {row['strategy']} | {row['avg_tokens']} | "
            f"{row['quality']} | {row['negative_ok']} | {row['passed']} | {row['failure']} |"
        )

    lines.extend([
        "",
        "## Top Passing Strategies Per Query Class",
        "",
        "| Query class | Strategy | Avg tokens | Quality | Negative OK | Avg nodes | Avg edges |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for query_class in query_classes:
        candidates = sorted(
            [row for row in passing if row["query_class"] == query_class],
            key=lambda row: (float(row["avg_tokens"]), -float(row["quality"])),
        )
        for row in candidates[:5]:
            lines.append(
                f"| {row['query_class']} | {row['strategy']} | {row['avg_tokens']} | "
                f"{row['quality']} | {row['negative_ok']} | {row['retrieved_nodes']} | {row['retrieved_edges']} |"
            )

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- The proxy floor is the cheapest policy table available from the current benchmark strategy set.",
        "- Any production default still needs packet parser validation and live answer scoring before promotion.",
        "- For `negative_query`, strategies that retrieve graph edges are rejected even if node/edge recall looks good, because the answer should prove absence.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not PROTOCOL_CSV.exists():
        raise SystemExit(f"Missing {PROTOCOL_CSV}; run protocol_benchmark.py first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = summarize(read_csv(PROTOCOL_CSV), manifest["thresholds"])
    if not rows:
        raise SystemExit("No rows generated.")
    write(rows)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
