from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROTOCOL_OUT = ROOT / "out" / "protocol"
PACKETS = PROTOCOL_OUT / "interpretability_packets"
PROMPTS_JSONL = PROTOCOL_OUT / "model_reasoning_prompts.jsonl"
RESULTS_CSV = PROTOCOL_OUT / "model_reasoning_results.csv"
RESULTS_MD = PROTOCOL_OUT / "model_reasoning_summary.md"
ANSWERS_JSONL = PROTOCOL_OUT / "model_reasoning_answers.jsonl"

VARIANTS = ["lowlevel_schema", "sql_schema", "hybrid_schema"]
HOPS = [1, 2]


def load_expected(corpus: str, task_class: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    path = PROTOCOL_OUT / "corpora" / corpus / "tasks_answer_key.json"
    tasks = json.loads(path.read_text(encoding="utf-8"))
    task = next(t for t in tasks if t["class"] == task_class)
    return set(task["expected_nodes"]), {tuple(edge) for edge in task["expected_edges"]}


def build_eval_prompt(packet_prompt: str) -> str:
    return (
        "Use only the graph packet below. Return strict JSON with these keys:\n"
        "- node_ids: array of relevant node IDs\n"
        "- edges: array of [source,target,type] triples for relevant edges\n"
        "- answer: one concise sentence\n\n"
        "Do not invent node IDs or edges. If no relevant edge exists, return an empty edges array.\n\n"
        f"{packet_prompt}"
    )


def iter_prompt_records() -> list[dict]:
    records = []
    for corpus_dir in sorted(PACKETS.iterdir()):
        if not corpus_dir.is_dir():
            continue
        corpus = corpus_dir.name
        for task_dir in sorted(corpus_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            task_class = task_dir.name
            expected_nodes, expected_edges = load_expected(corpus, task_class)
            for hops in HOPS:
                for variant in VARIANTS:
                    packet_path = task_dir / f"{hops}hop_{variant}.txt"
                    if not packet_path.exists():
                        continue
                    packet_prompt = packet_path.read_text(encoding="utf-8")
                    records.append(
                        {
                            "corpus": corpus,
                            "task": task_class,
                            "hops": hops,
                            "variant": variant,
                            "expected_nodes": sorted(expected_nodes),
                            "expected_edges": [list(edge) for edge in sorted(expected_edges)],
                            "packet_path": str(packet_path.relative_to(ROOT)).replace("\\", "/"),
                            "prompt": build_eval_prompt(packet_prompt),
                        }
                    )
    return records


def write_prompts(records: list[dict]) -> None:
    with PROMPTS_JSONL.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_answer(answer: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    data = extract_json(answer)
    nodes = {str(node) for node in data.get("node_ids", [])}
    edges = set()
    for edge in data.get("edges", []):
        if isinstance(edge, list) and len(edge) >= 3:
            edges.add((str(edge[0]), str(edge[1]), str(edge[2])))
    return nodes, edges


def score_answer(record: dict, answer: str, ttft_ms: float | None, total_ms: float | None, model: str) -> dict:
    expected_nodes = set(record["expected_nodes"])
    expected_edges = {tuple(edge) for edge in record["expected_edges"]}
    try:
        answer_nodes, answer_edges = normalize_answer(answer)
        parse_status = "PASS"
    except Exception as exc:
        answer_nodes, answer_edges = set(), set()
        parse_status = f"FAIL:{exc.__class__.__name__}"

    node_recall = len(answer_nodes & expected_nodes) / max(1, len(expected_nodes))
    edge_recall = len(answer_edges & expected_edges) / max(1, len(expected_edges)) if expected_edges else 1.0
    hallucinated_nodes = sorted(answer_nodes - expected_nodes)
    hallucinated_edges = sorted(answer_edges - expected_edges)
    return {
        "corpus": record["corpus"],
        "task": record["task"],
        "hops": record["hops"],
        "variant": record["variant"],
        "model": model,
        "parse_status": parse_status,
        "node_recall": round(node_recall, 4),
        "edge_recall": round(edge_recall, 4),
        "hallucinated_node_count": len(hallucinated_nodes),
        "hallucinated_edge_count": len(hallucinated_edges),
        "answer_node_count": len(answer_nodes),
        "answer_edge_count": len(answer_edges),
        "expected_node_count": len(expected_nodes),
        "expected_edge_count": len(expected_edges),
        "ttft_ms": "" if ttft_ms is None else round(ttft_ms, 3),
        "total_ms": "" if total_ms is None else round(total_ms, 3),
    }


def run_openai(prompt: str) -> tuple[str, float, float, str]:
    from openai import OpenAI  # type: ignore

    model = os.environ.get("OPENAI_REASONING_MODEL", "gpt-4o-mini")
    client = OpenAI()
    start = time.perf_counter()
    first = None
    chunks: list[str] = []
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=350,
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


def write_results(rows: list[dict], skipped: bool) -> None:
    if rows:
        with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    lines = ["# Model Reasoning Benchmark", ""]
    if skipped:
        lines.extend([
            "Live model execution skipped.",
            "",
            "Prompts were generated for later execution:",
            f"- `{PROMPTS_JSONL.relative_to(ROOT)}`",
            "",
            "Set `RUN_OPENAI_REASONING_EVAL=1` and `OPENAI_API_KEY` to run live scoring.",
        ])
    else:
        lines.extend([
            f"Rows: {len(rows)}",
            "",
            "| Variant | Hops | Node recall | Edge recall | Hallucinated nodes | Hallucinated edges | TTFT ms | Total ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        groups: dict[tuple[str, int], list[dict]] = {}
        for row in rows:
            groups.setdefault((row["variant"], int(row["hops"])), []).append(row)
        for (variant, hops), items in sorted(groups.items()):
            avg = lambda key: sum(float(item[key] or 0) for item in items) / len(items)
            lines.append(
                f"| {variant} | {hops} | {avg('node_recall'):.3f} | {avg('edge_recall'):.3f} | "
                f"{avg('hallucinated_node_count'):.3f} | {avg('hallucinated_edge_count'):.3f} | "
                f"{avg('ttft_ms'):.1f} | {avg('total_ms'):.1f} |"
            )
        lines.extend(["", f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`", f"Answers: `{ANSWERS_JSONL.relative_to(ROOT)}`"])
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not PACKETS.exists():
        raise SystemExit("Run interpretability_benchmark.py first; interpretability packets are missing.")
    records = iter_prompt_records()
    write_prompts(records)

    if os.environ.get("RUN_OPENAI_REASONING_EVAL") != "1":
        write_results([], skipped=True)
        print(RESULTS_MD.read_text(encoding="utf-8"))
        return
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required when RUN_OPENAI_REASONING_EVAL=1.")

    rows = []
    with ANSWERS_JSONL.open("w", encoding="utf-8") as answers_out:
        for record in records:
            answer, ttft_ms, total_ms, model = run_openai(record["prompt"])
            rows.append(score_answer(record, answer, ttft_ms, total_ms, model))
            answers_out.write(json.dumps({**record, "answer": answer}, ensure_ascii=False) + "\n")
    write_results(rows, skipped=False)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

