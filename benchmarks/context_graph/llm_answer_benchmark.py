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


def get_api_key(name: str) -> str | None:
    val = os.environ.get(name)
    if val:
        return val
    try:
        import keyring
        service = "OpenAI" if "OPENAI" in name else "Gemini"
        return keyring.get_password(service, "API_KEY")
    except Exception:
        return None


def run_openai(prompt: str) -> tuple[str, float, float, str]:
    from openai import OpenAI  # type: ignore

    model = os.environ.get("OPENAI_ANSWER_MODEL", "gpt-4o-mini")
    api_key = get_api_key("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
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


def run_gemini(prompt: str) -> tuple[str, float, float, str]:
    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    api_key = get_api_key("GEMINI_API_KEY")
    start = time.perf_counter()
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        text = response.text
        end = time.perf_counter()
        return text, (end - start) * 1000, (end - start) * 1000, model
    except ImportError:
        pass
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model_obj = genai.GenerativeModel(model)
        response = model_obj.generate_content(prompt)
        text = response.text
        end = time.perf_counter()
        return text, (end - start) * 1000, (end - start) * 1000, model
    except Exception as e:
        raise RuntimeError(f"Failed to run Gemini: {e}")


def run_llm(prompt: str) -> tuple[str, float, float, str]:
    preferred = os.environ.get("PREFERRED_PROVIDER", "").lower()
    if preferred == "gemini":
        if get_api_key("GEMINI_API_KEY"):
            return run_gemini(prompt)
        elif get_api_key("OPENAI_API_KEY"):
            return run_openai(prompt)
    elif preferred == "openai":
        if get_api_key("OPENAI_API_KEY"):
            return run_openai(prompt)
        elif get_api_key("GEMINI_API_KEY"):
            return run_gemini(prompt)
    else:
        if get_api_key("OPENAI_API_KEY"):
            return run_openai(prompt)
        elif get_api_key("GEMINI_API_KEY"):
            return run_gemini(prompt)
    raise RuntimeError("No API key found for OpenAI or Gemini in environment or keyring.")


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

    openai_key = get_api_key("OPENAI_API_KEY")
    gemini_key = get_api_key("GEMINI_API_KEY")
    run_eval = (
        os.environ.get("RUN_OPENAI_ANSWER_EVAL") == "1"
        or os.environ.get("RUN_GEMINI_ANSWER_EVAL") == "1"
    )

    if not run_eval:
        print("Live model execution skipped for llm_answer_benchmark.py.")
        if openai_key or gemini_key:
            print("API key detected, but live calls require RUN_OPENAI_ANSWER_EVAL=1 or RUN_GEMINI_ANSWER_EVAL=1.")
        else:
            print("Set OPENAI_API_KEY or GEMINI_API_KEY, or store a key in Windows Credential Manager, before explicit live runs.")
        return

    rows = []
    with PROMPTS_JSONL.open("r", encoding="utf-8") as f, ANSWERS_JSONL.open("w", encoding="utf-8") as out:
        for line in f:
            record = json.loads(line)
            answer, ttft_ms, total_ms, model = run_llm(record["prompt"])
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
