from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from model_reasoning_benchmark import load_expected, packet_edges, packet_node_ids
from protocol_benchmark import get_token_counter

ROOT = Path(__file__).resolve().parent
PROTOCOL_OUT = ROOT / "out" / "protocol"
PROMPTS_JSONL = PROTOCOL_OUT / "model_reasoning_prompts.jsonl"
EVAL_KEYS_JSONL = PROTOCOL_OUT / "model_reasoning_eval_keys.jsonl"
RESULTS_CSV = PROTOCOL_OUT / "prompt_preflight.csv"
RESULTS_MD = PROTOCOL_OUT / "prompt_preflight.md"


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Prompt file missing: {path}. Run model_reasoning_benchmark.py first.")
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if not records:
        raise SystemExit(f"Prompt file is empty: {path}")
    return records


def load_eval_counts(path: Path) -> dict[tuple[str, str, int, str], tuple[int, int]]:
    if not path.exists():
        return {}
    counts = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            key = (record["corpus"], record["task"], int(record["hops"]), record["variant"])
            counts[key] = (len(record.get("expected_nodes", [])), len(record.get("expected_edges", [])))
    return counts


def avg(values: list[int]) -> float:
    return sum(values) / max(1, len(values))


def pct(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = round((len(ordered) - 1) * percentile)
    return ordered[idx]


def build_rows(records: list[dict], eval_counts: dict[tuple[str, str, int, str], tuple[int, int]], count_tokens) -> list[dict]:
    rows = []
    for record in records:
        prompt_tokens = count_tokens(record["prompt"])
        key = (record["corpus"], record["task"], int(record["hops"]), record["variant"])
        expected_nodes, expected_edges = load_expected(record["corpus"], record["task"])
        available_nodes = packet_node_ids(record["prompt"])
        available_edges = packet_edges(record["prompt"])
        node_recall = len(expected_nodes & available_nodes) / max(1, len(expected_nodes))
        edge_recall = len(expected_edges & available_edges) / max(1, len(expected_edges)) if expected_edges else 1.0
        irrelevant_node_ratio = len(available_nodes - expected_nodes) / max(1, len(available_nodes))
        irrelevant_edge_ratio = len(available_edges - expected_edges) / max(1, len(available_edges))
        negative_direct_edge_count = count_edges_between(available_edges, expected_nodes) if record["task"] == "negative_query" else 0
        expected_node_count, expected_edge_count = eval_counts.get(
            key,
            (len(record.get("expected_nodes", [])), len(record.get("expected_edges", []))),
        )
        rows.append(
            {
                "corpus": record["corpus"],
                "task": record["task"],
                "hops": int(record["hops"]),
                "variant": record["variant"],
                "prompt_tokens": prompt_tokens,
                "expected_node_count": expected_node_count,
                "expected_edge_count": expected_edge_count,
                "prompt_answer_key_fields": int("expected_nodes" in record or "expected_edges" in record),
                "packet_node_count": len(available_nodes),
                "packet_edge_count": len(available_edges),
                "node_recall": round(node_recall, 4),
                "edge_recall": round(edge_recall, 4),
                "irrelevant_node_ratio": round(irrelevant_node_ratio, 4),
                "irrelevant_edge_ratio": round(irrelevant_edge_ratio, 4),
                "negative_direct_edge_count": negative_direct_edge_count,
                "packet_path": record["packet_path"],
            }
        )
    return rows


def count_edges_between(edges: set[tuple[str, str, str]], nodes: set[str]) -> int:
    if len(nodes) < 2:
        return sum(1 for source, target, _kind in edges if source in nodes or target in nodes)
    return sum(1 for source, target, _kind in edges if source in nodes and target in nodes)


def write_csv(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def estimate_cost(total_input_tokens: int, prompt_count: int, input_price: float | None, output_price: float | None, expected_output_tokens: int) -> str:
    if input_price is None and output_price is None:
        return "Cost estimate skipped; pass explicit per-1M token prices to estimate dollars."
    input_cost = 0.0 if input_price is None else (total_input_tokens / 1_000_000) * input_price
    output_tokens = prompt_count * expected_output_tokens
    output_cost = 0.0 if output_price is None else (output_tokens / 1_000_000) * output_price
    return (
        f"Estimated cost with supplied prices: input `${input_cost:.6f}`, "
        f"output `${output_cost:.6f}` at {expected_output_tokens} expected output tokens per prompt, "
        f"total `${input_cost + output_cost:.6f}`."
    )


def write_md(rows: list[dict], tokenizer: str, input_price: float | None, output_price: float | None, expected_output_tokens: int) -> None:
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["variant"], row["hops"])].append(row)

    total_input_tokens = sum(row["prompt_tokens"] for row in rows)
    leaked_key_fields = sum(int(row["prompt_answer_key_fields"]) for row in rows)
    corpora = sorted({row["corpus"] for row in rows})
    tasks = sorted({row["task"] for row in rows})
    variants = sorted({row["variant"] for row in rows})

    lines = [
        "# Prompt Preflight",
        "",
        f"Prompt records: `{len(rows)}`",
        f"Tokenizer: `{tokenizer}`",
        f"Corpora: `{', '.join(corpora)}`",
        f"Tasks: `{', '.join(tasks)}`",
        f"Variants: `{', '.join(variants)}`",
        f"Total input tokens for one full run: `{total_input_tokens}`",
        f"Prompt records with answer-key fields: `{leaked_key_fields}`",
        "",
        estimate_cost(total_input_tokens, len(rows), input_price, output_price, expected_output_tokens),
        "",
        "| Variant | Hops | Prompts | Avg tokens | P50 | P90 | Max | Avg expected nodes | Avg expected edges |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (variant, hops), items in sorted(grouped.items()):
        token_values = [int(item["prompt_tokens"]) for item in items]
        node_values = [int(item["expected_node_count"]) for item in items]
        edge_values = [int(item["expected_edge_count"]) for item in items]
        lines.append(
            f"| {variant} | {hops} | {len(items)} | {avg(token_values):.1f} | "
            f"{pct(token_values, 0.50)} | {pct(token_values, 0.90)} | {max(token_values)} | "
            f"{avg(node_values):.1f} | {avg(edge_values):.1f} |"
        )

    lines.extend(
        [
            "",
            "| Variant | Hops | Node recall | Edge recall | Irrelevant nodes | Irrelevant edges | Packet nodes | Packet edges |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for (variant, hops), items in sorted(grouped.items()):
        lines.append(
            f"| {variant} | {hops} | {sum(float(item['node_recall']) for item in items) / len(items):.3f} | "
            f"{sum(float(item['edge_recall']) for item in items) / len(items):.3f} | "
            f"{sum(float(item['irrelevant_node_ratio']) for item in items) / len(items):.3f} | "
            f"{sum(float(item['irrelevant_edge_ratio']) for item in items) / len(items):.3f} | "
            f"{sum(int(item['packet_node_count']) for item in items) / len(items):.1f} | "
            f"{sum(int(item['packet_edge_count']) for item in items) / len(items):.1f} |"
        )

    negative_items = [row for row in rows if row["task"] == "negative_query"]
    if negative_items:
        false_positive_packets = sum(1 for row in negative_items if int(row["negative_direct_edge_count"]) > 0)
        lines.extend(
            [
                "",
                "Negative-query direct-edge packet false positives: "
                f"`{false_positive_packets}/{len(negative_items)}`",
            ]
        )

    lines.extend(
        [
            "",
            "Use this before live model runs. It verifies that the frozen prompt set has the expected coverage and exposes the token budget before API spend.",
            "",
            f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
        ]
    )
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize frozen model-reasoning prompts before live model execution.")
    parser.add_argument("--input-price-per-1m", type=float, default=None)
    parser.add_argument("--output-price-per-1m", type=float, default=None)
    parser.add_argument("--expected-output-tokens", type=int, default=250)
    args = parser.parse_args()

    tokenizer, count_tokens = get_token_counter()
    records = load_records(PROMPTS_JSONL)
    eval_counts = load_eval_counts(EVAL_KEYS_JSONL)
    rows = build_rows(records, eval_counts, count_tokens)
    write_csv(rows)
    write_md(rows, tokenizer, args.input_price_per_1m, args.output_price_per_1m, args.expected_output_tokens)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
