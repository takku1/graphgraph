from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROTOCOL_OUT = ROOT / "out" / "protocol"
PROMPTS_JSONL = PROTOCOL_OUT / "saved_prompts.jsonl"
ANSWERS_JSONL = PROTOCOL_OUT / "llm_answers.jsonl"
ANSWERS_CSV = PROTOCOL_OUT / "llm_answer_metrics.csv"


def extract_ids(text: str) -> set[str]:
    return set(re.findall(r"\bN\d{5}\b", text))


def run_openai(prompt: str) -> tuple[str, float, float, str]:
    if os.environ.get("RUN_OPENAI_ANSWER_EVAL") != "1":
        raise RuntimeError("Set RUN_OPENAI_ANSWER_EVAL=1 to run live model answers.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for live model answers.")
    from openai import OpenAI  # type: ignore

    model = os.environ.get("OPENAI_ANSWER_MODEL", "gpt-4o-mini")
    client = OpenAI()
    start = time.perf_counter()
    first = None
    chunks = []
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=300,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            if first is None:
                first = time.perf_counter()
            chunks.append(delta)
    end = time.perf_counter()
    return "".join(chunks), ((first or end) - start) * 1000, (end - start) * 1000, model


def load_expected(corpus: str, task_class: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    path = PROTOCOL_OUT / "corpora" / corpus / "tasks_answer_key.json"
    tasks = json.loads(path.read_text(encoding="utf-8"))
    task = next(t for t in tasks if t["class"] == task_class)
    nodes = set(task["expected_nodes"])
    edges = {tuple(edge) for edge in task["expected_edges"]}
    return nodes, edges


def main() -> None:
    if not PROMPTS_JSONL.exists():
        raise SystemExit("Run protocol_benchmark.py first; saved_prompts.jsonl is missing.")

    rows = []
    with PROMPTS_JSONL.open("r", encoding="utf-8") as f, ANSWERS_JSONL.open("w", encoding="utf-8") as out:
        for line in f:
            record = json.loads(line)
            answer, ttft_ms, total_ms, model = run_openai(record["prompt"])
            packet_ids = extract_ids(record["prompt"])
            answer_ids = extract_ids(answer)
            expected_ids, expected_edges = load_expected(record["corpus"], record["task"])
            hallucinated_ids = sorted(answer_ids - packet_ids)
            answer_node_recall = len(answer_ids & expected_ids) / max(1, len(expected_ids))
            answer_extra_expected_miss = sorted(expected_ids - answer_ids)
            row = {
                "corpus": record["corpus"],
                "task": record["task"],
                "strategy": record["strategy"],
                "model": model,
                "ttft_ms": round(ttft_ms, 3),
                "total_ms": round(total_ms, 3),
                "expected_node_count": len(expected_ids),
                "expected_edge_count": len(expected_edges),
                "answer_node_recall": round(answer_node_recall, 4),
                "answer_node_ids": " ".join(sorted(answer_ids)),
                "missed_expected_node_ids": " ".join(answer_extra_expected_miss),
                "hallucinated_node_ids": " ".join(hallucinated_ids),
                "hallucinated_node_count": len(hallucinated_ids),
            }
            rows.append(row)
            out.write(json.dumps({**record, **row, "answer": answer}, ensure_ascii=False) + "\n")

    with ANSWERS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {ANSWERS_JSONL}")
    print(f"Wrote {ANSWERS_CSV}")


if __name__ == "__main__":
    main()
