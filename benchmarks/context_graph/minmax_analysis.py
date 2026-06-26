from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
PROTOCOL_OUT = OUT / "protocol"
FORMAT_CSV = OUT / "format_results.csv"
PROTOCOL_CSV = PROTOCOL_OUT / "protocol_results.csv"
INTERPRETABILITY_CSV = PROTOCOL_OUT / "interpretability_results.csv"
MANIFEST = ROOT / "benchmark_manifest.json"
REPORT = PROTOCOL_OUT / "minmax_report.md"


DEFAULT_INPUT_COST_PER_1M = 0.15


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def avg(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / max(1, len(items))


def money(tokens: float, price_per_1m: float = DEFAULT_INPUT_COST_PER_1M) -> float:
    return (tokens / 1_000_000) * price_per_1m


def pass_threshold(items: list[dict], thresholds: dict) -> tuple[bool, list[str]]:
    node = avg(items, "node_recall")
    edge = avg(items, "edge_recall")
    irrelevant = avg(items, "irrelevant_context_ratio")
    failures = []
    if node < thresholds["min_node_recall"]:
        failures.append(f"node recall {node:.3f} < {thresholds['min_node_recall']}")
    if edge < thresholds["min_edge_recall"]:
        failures.append(f"edge recall {edge:.3f} < {thresholds['min_edge_recall']}")
    if irrelevant > thresholds["max_irrelevant_context_ratio"]:
        failures.append(f"irrelevant context {irrelevant:.3f} > {thresholds['max_irrelevant_context_ratio']}")
    return not failures, failures


def dominates(a: dict, b: dict) -> bool:
    a_tokens = float(a["avg_tokens"])
    b_tokens = float(b["avg_tokens"])
    a_recall = float(a["quality"])
    b_recall = float(b["quality"])
    a_noise = float(a["irrelevant_context_ratio"])
    b_noise = float(b["irrelevant_context_ratio"])
    return (
        a_tokens <= b_tokens
        and a_recall >= b_recall
        and a_noise <= b_noise
        and (a_tokens < b_tokens or a_recall > b_recall or a_noise < b_noise)
    )


def protocol_summary(rows: list[dict], thresholds: dict) -> tuple[list[dict], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["corpus"], row["strategy"])].append(row)

    summaries = []
    for (corpus, strategy), items in grouped.items():
        node = avg(items, "node_recall")
        edge = avg(items, "edge_recall")
        path = avg(items, "path_recall")
        quality = (0.45 * node) + (0.40 * edge) + (0.15 * path)
        passed, failures = pass_threshold(items, thresholds)
        summaries.append(
            {
                "corpus": corpus,
                "strategy": strategy,
                "avg_tokens": avg(items, "tokens"),
                "input_cost_per_query": money(avg(items, "tokens")),
                "node_recall": node,
                "edge_recall": edge,
                "path_recall": path,
                "quality": quality,
                "irrelevant_context_ratio": avg(items, "irrelevant_context_ratio"),
                "latency_ms": avg(items, "latency_ms"),
                "passed": passed,
                "failures": "; ".join(failures),
            }
        )

    frontiers = []
    for corpus in sorted({s["corpus"] for s in summaries}):
        candidates = [s for s in summaries if s["corpus"] == corpus and s["passed"]]
        for candidate in candidates:
            if not any(dominates(other, candidate) for other in candidates if other is not candidate):
                frontiers.append(candidate)
    return summaries, frontiers


def format_summary(rows: list[dict]) -> list[dict]:
    by_size: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_size[row["graph_size_nodes"]].append(row)

    out = []
    for size, items in sorted(by_size.items(), key=lambda kv: int(kv[0])):
        worst = max(float(item["tokens"]) for item in items)
        best = min(float(item["tokens"]) for item in items)
        for item in sorted(items, key=lambda r: float(r["tokens"])):
            out.append(
                {
                    "nodes": int(size),
                    "edges": int(item["graph_size_edges"]),
                    "format": item["format"],
                    "tokens": int(float(item["tokens"])),
                    "prompt_tokens": int(float(item["prompt_tokens"])),
                    "relative_to_worst": float(item["tokens"]) / worst,
                    "relative_to_best": float(item["tokens"]) / best,
                    "input_cost_per_query": money(float(item["prompt_tokens"])),
                }
            )
    return out


def write_report(format_rows: list[dict], summaries: list[dict], frontiers: list[dict]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Min-Max Context Graph Report",
        "",
        "Objective: minimize input tokens, TTFT proxy, and input cost while preserving recall.",
        "",
        f"Cost model: `${DEFAULT_INPUT_COST_PER_1M}` per 1M input tokens. Change `DEFAULT_INPUT_COST_PER_1M` in `minmax_analysis.py` for a different provider/model.",
        "",
        "## Format Overhead",
        "",
        "| Nodes | Edges | Format | Tokens | Prompt tokens | vs best | vs worst | Est. input cost/query |",
        "| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in format_rows:
        lines.append(
            f"| {row['nodes']} | {row['edges']} | {row['format']} | {row['tokens']} | "
            f"{row['prompt_tokens']} | {row['relative_to_best']:.2f}x | "
            f"{row['relative_to_worst']:.3f} | ${row['input_cost_per_query']:.8f} |"
        )

    lines.extend([
        "",
        "## Smallest Passing Retrieval Strategy",
        "",
        "| Corpus | Winner | Avg tokens | Quality | Node recall | Edge recall | Path recall | Irrelevant ratio | Est. input cost/query |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for corpus in sorted({s["corpus"] for s in summaries}):
        passing = [s for s in summaries if s["corpus"] == corpus and s["passed"]]
        if not passing:
            lines.append(f"| {corpus} | none |  |  |  |  |  |  |  |")
            continue
        winner = min(passing, key=lambda s: s["avg_tokens"])
        lines.append(
            f"| {corpus} | {winner['strategy']} | {winner['avg_tokens']:.1f} | "
            f"{winner['quality']:.3f} | {winner['node_recall']:.3f} | {winner['edge_recall']:.3f} | "
            f"{winner['path_recall']:.3f} | {winner['irrelevant_context_ratio']:.3f} | "
            f"${winner['input_cost_per_query']:.8f} |"
        )

    lines.extend([
        "",
        "## Pareto Frontier",
        "",
        "A strategy is on the frontier if no other passing strategy has lower/equal tokens, higher/equal quality, and lower/equal irrelevant context.",
        "",
        "| Corpus | Strategy | Avg tokens | Quality | Irrelevant ratio |",
        "| --- | --- | ---: | ---: | ---: |",
    ])
    for row in sorted(frontiers, key=lambda r: (r["corpus"], r["avg_tokens"])):
        lines.append(
            f"| {row['corpus']} | {row['strategy']} | {row['avg_tokens']:.1f} | "
            f"{row['quality']:.3f} | {row['irrelevant_context_ratio']:.3f} |"
        )

    if INTERPRETABILITY_CSV.exists():
        interp_rows = read_csv(INTERPRETABILITY_CSV)
        grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for row in interp_rows:
            if row["hops"] == "2":
                grouped[(row["corpus"], row["hops"], row["variant"])].append(row)
        lines.extend([
            "",
            "## Interpretability Overhead",
            "",
            "Two-hop packets shown because they are the perfect-recall safety point.",
            "",
            "| Corpus | Variant | Schema tokens | Packet tokens | Uncached prompt | Cached prompt |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ])
        for (corpus, _hops, variant), items in sorted(grouped.items()):
            if variant not in {"lowlevel_schema", "sql_schema", "hybrid_schema", "compact_schema"}:
                continue
            lines.append(
                f"| {corpus} | {variant} | {avg(items, 'schema_tokens'):.1f} | "
                f"{avg(items, 'packet_tokens'):.1f} | {avg(items, 'uncached_prompt_tokens'):.1f} | "
                f"{avg(items, 'cached_prompt_tokens'):.1f} |"
            )

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- For raw structural prompt encoding, `low_level_adj` / CSR-like arrays are the current token floor.",
        "- `sql_rows` is the first fallback when a model needs column labels like `source`, `target`, and `weight`.",
        "- For retrieval plus rendering, the current smallest passing strategy is `graph_1hop_lowlevel`; `graph_2hop_lowlevel` is the high-recall safety baseline.",
        "- For machine storage, CSR-style binary is the likely sparse-graph floor; dense bitmaps only win for tiny topology-only graphs and become poor on sparse large graphs.",
        "- Schema overhead is small enough that low-level packets remain the prompt floor; prompt caching makes that advantage cleaner.",
        "- Full Markdown is an oracle-like recall baseline, but it fails the noise/cost objective once corpora grow.",
        "- Keyword and BM25 are useful cheap baselines, but current runs show they miss too many relationship edges.",
        "",
        "## Next Validation",
        "",
        "1. Run live model-answer tests on `low_level_adj` packets for multi-hop and blast-radius queries.",
        "2. If answer-node recall or edge reasoning fails, test `sql_rows` as the semantic-label fallback.",
        "3. If both pass, compare TTFT and input cost to choose the production default.",
        "",
    ])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not FORMAT_CSV.exists():
        raise SystemExit(f"Missing {FORMAT_CSV}; run format_benchmark.py first.")
    if not PROTOCOL_CSV.exists():
        raise SystemExit(f"Missing {PROTOCOL_CSV}; run protocol_benchmark.py first.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    format_rows = format_summary(read_csv(FORMAT_CSV))
    summaries, frontiers = protocol_summary(read_csv(PROTOCOL_CSV), manifest["thresholds"])
    write_report(format_rows, summaries, frontiers)
    print(REPORT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
