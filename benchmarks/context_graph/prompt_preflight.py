from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from protocol_benchmark import get_token_counter


ROOT = Path(__file__).resolve().parent
PROTOCOL_OUT = ROOT / "out" / "protocol"
PROMPTS_JSONL = PROTOCOL_OUT / "model_reasoning_prompts.jsonl"
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


def avg(values: list[int]) -> float:
    return sum(values) / max(1, len(values))


def pct(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = round((len(ordered) - 1) * percentile)
    return ordered[idx]


def build_rows(records: list[dict], count_tokens) -> list[dict]:
    rows = []
    for record in records:
        prompt_tokens = count_tokens(record["prompt"])
        rows.append(
            {
                "corpus": record["corpus"],
                "task": record["task"],
                "hops": int(record["hops"]),
                "variant": record["variant"],
                "prompt_tokens": prompt_tokens,
                "expected_node_count": len(record.get("expected_nodes", [])),
                "expected_edge_count": len(record.get("expected_edges", [])),
                "packet_path": record["packet_path"],
            }
        )
    return rows


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
    rows = build_rows(records, count_tokens)
    write_csv(rows)
    write_md(rows, tokenizer, args.input_price_per_1m, args.output_price_per_1m, args.expected_output_tokens)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
