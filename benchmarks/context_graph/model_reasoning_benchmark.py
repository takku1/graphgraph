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
EVAL_KEYS_JSONL = PROTOCOL_OUT / "model_reasoning_eval_keys.jsonl"
RESULTS_CSV = PROTOCOL_OUT / "model_reasoning_results.csv"
RESULTS_MD = PROTOCOL_OUT / "model_reasoning_summary.md"
ANSWERS_JSONL = PROTOCOL_OUT / "model_reasoning_answers.jsonl"

VARIANTS = ["lowlevel_schema", "sql_schema", "hybrid_schema", "semantic_arrow_schema", "gg_max_schema", "gg_lex_schema", "gg_lex_hybrid_schema"]
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
                            "packet_path": str(packet_path.relative_to(ROOT)).replace("\\", "/"),
                            "prompt": build_eval_prompt(packet_prompt),
                        }
                    )
    return records


def write_prompts(records: list[dict]) -> None:
    with PROMPTS_JSONL.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    with EVAL_KEYS_JSONL.open("w", encoding="utf-8") as f:
        for record in records:
            expected_nodes, expected_edges = load_expected(record["corpus"], record["task"])
            f.write(
                json.dumps(
                    {
                        "corpus": record["corpus"],
                        "task": record["task"],
                        "hops": record["hops"],
                        "variant": record["variant"],
                        "expected_nodes": sorted(expected_nodes),
                        "expected_edges": [list(edge) for edge in sorted(expected_edges)],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def extract_json(text: str) -> dict:
    t = text.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    
    start_idx = t.find('{')
    if start_idx == -1:
        raise ValueError("No JSON object found")
    
    body = t[start_idx:]
    
    # Try adding closing braces to fix truncation
    if not body.endswith('}'):
        for i in range(1, 5):
            try:
                return json.loads(body + '}' * i)
            except json.JSONDecodeError:
                pass
                
    # Fix unquoted answer strings
    fixed_body = body
    match_unquoted = re.search(r'"answer":\s*([A-Za-z][^"\n}]*)', fixed_body)
    if match_unquoted:
        unquoted_val = match_unquoted.group(1).strip()
        fixed_body = fixed_body.replace(match_unquoted.group(0), f'"answer": "{unquoted_val}"')
        
    try:
        return json.loads(fixed_body)
    except json.JSONDecodeError:
        pass
        
    match = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
            
    if not fixed_body.endswith('}'):
        for i in range(1, 5):
            try:
                return json.loads(fixed_body + '}' * i)
            except json.JSONDecodeError:
                pass
                
    return json.loads(text)


def normalize_answer(answer: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    data = extract_json(answer)
    nodes = {str(node) for node in data.get("node_ids", [])}
    edges = set()
    for edge in data.get("edges", []):
        if isinstance(edge, list) and len(edge) >= 3:
            edges.add((str(edge[0]), str(edge[1]), str(edge[2])))
    return nodes, edges


def packet_node_ids(prompt: str) -> set[str]:
    return set(re.findall(r"\bN\d{5}\b", prompt))


def packet_edges(prompt: str) -> set[tuple[str, str, str]]:
    """Best-effort packet-boundary parser for hallucination checks."""
    edges: set[tuple[str, str, str]] = set()
    relation_ids = dict(re.findall(r"(?m)^(\d+):([A-Za-z_][A-Za-z0-9_]*)$", prompt))

    for source, target, relation_id in re.findall(r"\b(N\d{5}),(N\d{5}),(\d+),", prompt):
        relation = relation_ids.get(relation_id)
        if relation:
            edges.add((source, target, relation))

    for source, target, relation in re.findall(r"\b(N\d{5}),(N\d{5}),([A-Za-z_][A-Za-z0-9_]*),", prompt):
        edges.add((source, target, relation))

    for source, relation, target in re.findall(r"\b(N\d{5})\s+-([A-Za-z_][A-Za-z0-9_]*)->\s+(N\d{5})", prompt):
        edges.add((source, target, relation))

    return edges


def load_corpus_mappings(corpus: str) -> tuple[dict[str, str], dict[str, str]]:
    path = PROTOCOL_OUT / "corpora" / corpus / "graph.json"
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    label_to_id = {}
    id_to_label = {}
    
    nodes_list = data.get("nodes", [])
    for node in nodes_list:
        nid = node.get("id")
        label = node.get("label")
        if nid and label:
            label_to_id[label] = nid
            id_to_label[nid] = label
    return label_to_id, id_to_label

def parse_prompt_node_map(prompt: str) -> dict[str, str]:
    mapping = {}
    match_max = re.search(r"\[n\]\n(.*?)(?:\n\[e\]|\Z)", prompt, re.DOTALL)
    if match_max:
        for line in match_max.group(1).strip().split("\n"):
            if line.startswith("#"):
                continue
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    match_low = re.search(r"<n>\n(.*?)\n</n>", prompt, re.DOTALL)
    if match_low:
        for line in match_low.group(1).strip().split("\n"):
            parts = line.strip().split(":", 1)
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    match_arrow = re.search(r"@nodes\n(.*?)(?:\n@edges|\Z)", prompt, re.DOTALL)
    if match_arrow:
        for line in match_arrow.group(1).strip().split("\n"):
            parts = line.strip().split(":", 1)
            if len(parts) == 2:
                mapping[parts[0]] = parts[1].strip()
    return mapping

def parse_prompt_relation_map(prompt: str) -> dict[str, str]:
    mapping = {}
    match_r = re.search(r"(?:\[r\]|<r>)\n(.*?)(?:\n\[n\]|\n</r>|\Z)", prompt, re.DOTALL)
    if match_r:
        for line in match_r.group(1).strip().split("\n"):
            parts = line.strip().split(":", 1)
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    return mapping

def resolve_answer_to_canonical(
    prompt: str,
    corpus: str,
    answer_nodes: set[str],
    answer_edges: set[tuple[str, str, str]]
) -> tuple[set[str], set[tuple[str, str, str]]]:
    prompt_nodes = parse_prompt_node_map(prompt)
    prompt_relations = parse_prompt_relation_map(prompt)
    label_to_id, _ = load_corpus_mappings(corpus)
    
    def to_canonical_id(node_ref: str) -> str:
        if re.match(r"^N\d+$", node_ref):
            return node_ref
        label = prompt_nodes.get(node_ref, node_ref)
        return label_to_id.get(label, node_ref)
        
    resolved_nodes = {to_canonical_id(n) for n in answer_nodes}
    resolved_edges = set()
    for src, tgt, rel in answer_edges:
        canon_src = to_canonical_id(src)
        canon_tgt = to_canonical_id(tgt)
        canon_rel = prompt_relations.get(rel, rel)
        resolved_edges.add((canon_src, canon_tgt, canon_rel))
        
    return resolved_nodes, resolved_edges

def get_available_nodes_and_edges(prompt: str, corpus: str) -> tuple[set[str], set[tuple[str, str, str]]]:
    prompt_nodes = parse_prompt_node_map(prompt)
    prompt_relations = parse_prompt_relation_map(prompt)
    label_to_id, _ = load_corpus_mappings(corpus)
    
    available_nodes = set()
    for ref, label in prompt_nodes.items():
        nid = label_to_id.get(label)
        if nid:
            available_nodes.add(nid)
            
    raw_nids = set(re.findall(r"\bN\d{5}\b", prompt))
    available_nodes.update(raw_nids)
    
    available_edges = set()
    match_e = re.search(r"\[e\]\n(.*?)(?:\n\Z|\n\[|\Z)", prompt, re.DOTALL)
    if match_e:
        for line in match_e.group(1).strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 3:
                src_ref, tgt_ref, rel_ref = parts[0], parts[1], parts[2]
                src_label = prompt_nodes.get(src_ref)
                tgt_label = prompt_nodes.get(tgt_ref)
                src_id = label_to_id.get(src_label)
                tgt_id = label_to_id.get(tgt_label)
                rel = prompt_relations.get(rel_ref, rel_ref)
                if src_id and tgt_id:
                    available_edges.add((src_id, tgt_id, rel))
                    
    match_a = re.search(r"<a>\n(.*?)\n</a>", prompt, re.DOTALL)
    if match_a:
        for line in match_a.group(1).strip().split("\n"):
            parts = line.strip().split(",")
            if len(parts) >= 3:
                src_ref, tgt_ref, rel_ref = parts[0], parts[1], parts[2]
                src_label = prompt_nodes.get(src_ref, src_ref)
                tgt_label = prompt_nodes.get(tgt_ref, tgt_ref)
                src_id = label_to_id.get(src_label, src_label)
                tgt_id = label_to_id.get(tgt_label, tgt_label)
                rel = prompt_relations.get(rel_ref, rel_ref)
                available_edges.add((src_id, tgt_id, rel))
                
    for src, rel, tgt in re.findall(r"\b(N\d{5})\s+-([A-Za-z_][A-Za-z0-9_]*)->\s+(N\d{5})", prompt):
        available_edges.add((src, tgt, rel))
        
    for src, tgt, rel in re.findall(r"\b(N\d{5}),(N\d{5}),([A-Za-z_][A-Za-z0-9_]*)", prompt):
        available_edges.add((src, tgt, rel))
        
    return available_nodes, available_edges

def score_answer(record: dict, answer: str, ttft_ms: float | None, total_ms: float | None, model: str) -> dict:
    expected_nodes, expected_edges = load_expected(record["corpus"], record["task"])
    available_nodes, available_edges = get_available_nodes_and_edges(record["prompt"], record["corpus"])
    try:
        raw_nodes, raw_edges = normalize_answer(answer)
        answer_nodes, answer_edges = resolve_answer_to_canonical(record["prompt"], record["corpus"], raw_nodes, raw_edges)
        parse_status = "PASS"
    except Exception as exc:
        answer_nodes, answer_edges = set(), set()
        parse_status = f"FAIL:{exc.__class__.__name__}"

    node_recall = len(answer_nodes & expected_nodes) / max(1, len(expected_nodes))
    edge_recall = len(answer_edges & expected_edges) / max(1, len(expected_edges)) if expected_edges else 1.0
    packet_node_recall = len(answer_nodes & available_nodes) / max(1, len(answer_nodes)) if answer_nodes else 1.0
    packet_edge_recall = len(answer_edges & available_edges) / max(1, len(answer_edges)) if answer_edges else 1.0
    hallucinated_nodes = sorted(answer_nodes - available_nodes)
    hallucinated_edges = sorted(answer_edges - available_edges)
    irrelevant_nodes = sorted((answer_nodes & available_nodes) - expected_nodes)
    irrelevant_edges = sorted((answer_edges & available_edges) - expected_edges)
    negative_false_positive_edge_count = len(answer_edges) if record["task"] == "negative_query" else 0
    return {
        "corpus": record["corpus"],
        "task": record["task"],
        "hops": record["hops"],
        "variant": record["variant"],
        "model": model,
        "parse_status": parse_status,
        "node_recall": round(node_recall, 4),
        "edge_recall": round(edge_recall, 4),
        "packet_node_precision": round(packet_node_recall, 4),
        "packet_edge_precision": round(packet_edge_recall, 4),
        "hallucinated_node_count": len(hallucinated_nodes),
        "hallucinated_edge_count": len(hallucinated_edges),
        "irrelevant_node_count": len(irrelevant_nodes),
        "irrelevant_edge_count": len(irrelevant_edges),
        "negative_false_positive_edge_count": negative_false_positive_edge_count,
        "answer_node_count": len(answer_nodes),
        "answer_edge_count": len(answer_edges),
        "expected_node_count": len(expected_nodes),
        "expected_edge_count": len(expected_edges),
        "packet_node_count": len(available_nodes),
        "packet_edge_count": len(available_edges),
        "ttft_ms": "" if ttft_ms is None else round(ttft_ms, 3),
        "total_ms": "" if total_ms is None else round(total_ms, 3),
    }


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

    model = os.environ.get("OPENAI_REASONING_MODEL", "gpt-4o-mini")
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = get_api_key("OPENAI_API_KEY") or "ollama"
    client = OpenAI(api_key=api_key, base_url=base_url)
    start = time.perf_counter()
    first = None
    chunks: list[str] = []
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1000,
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
    base_url = os.environ.get("OPENAI_BASE_URL")
    if preferred == "ollama" or base_url:
        return run_openai(prompt)
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
            f"- private eval keys: `{EVAL_KEYS_JSONL.relative_to(ROOT)}`",
            "",
            "Run live scoring explicitly with `RUN_OPENAI_REASONING_EVAL=1` or `RUN_GEMINI_REASONING_EVAL=1`.",
            "Set `OPENAI_API_KEY` or `GEMINI_API_KEY`, or store the key in Windows Credential Manager.",
            "Use `SCORE_EXISTING_REASONING_ANSWERS=1` to rescore saved answers without calling a model.",
        ])
    else:
        lines.extend([
            f"Rows: {len(rows)}",
            "",
            "| Variant | Hops | Parse pass | Node recall | Edge recall | Packet node precision | Packet edge precision | Hallucinated edges | Irrelevant edges | TTFT ms | Total ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        groups: dict[tuple[str, int], list[dict]] = {}
        for row in rows:
            groups.setdefault((row["variant"], int(row["hops"])), []).append(row)
        for (variant, hops), items in sorted(groups.items()):
            avg = lambda key: sum(float(item[key] or 0) for item in items) / len(items)
            parse_pass = sum(1 for item in items if item["parse_status"] == "PASS") / len(items)
            lines.append(
                f"| {variant} | {hops} | {parse_pass:.3f} | {avg('node_recall'):.3f} | {avg('edge_recall'):.3f} | "
                f"{avg('packet_node_precision'):.3f} | {avg('packet_edge_precision'):.3f} | "
                f"{avg('hallucinated_edge_count'):.3f} | {avg('irrelevant_edge_count'):.3f} | "
                f"{avg('ttft_ms'):.1f} | {avg('total_ms'):.1f} |"
            )
        negative_rows = [row for row in rows if row["task"] == "negative_query"]
        if negative_rows:
            total_false_positive_edges = sum(int(row["negative_false_positive_edge_count"]) for row in negative_rows)
            lines.extend([
                "",
                f"Negative-query false-positive answer edges: `{total_false_positive_edges}` across `{len(negative_rows)}` rows.",
            ])
        lines.extend(["", f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`", f"Answers: `{ANSWERS_JSONL.relative_to(ROOT)}`"])
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not PACKETS.exists():
        raise SystemExit("Run interpretability_benchmark.py first; interpretability packets are missing.")
    records = iter_prompt_records()
    limit = os.environ.get("LIMIT_TASKS")
    if limit:
        records = records[:int(limit)]
    write_prompts(records)

    if os.environ.get("SCORE_EXISTING_REASONING_ANSWERS") == "1":
        if not ANSWERS_JSONL.exists():
            raise SystemExit("No saved answers found to score.")
        rows = []
        with ANSWERS_JSONL.open("r", encoding="utf-8") as answers_in:
            for line in answers_in:
                record = json.loads(line)
                rows.append(score_answer(record, record.get("answer", ""), record.get("ttft_ms"), record.get("total_ms"), record.get("model", "saved")))
        write_results(rows, skipped=False)
        print(RESULTS_MD.read_text(encoding="utf-8"))
        return

    run_eval = os.environ.get("RUN_OPENAI_REASONING_EVAL") == "1" or os.environ.get("RUN_GEMINI_REASONING_EVAL") == "1"

    if not run_eval:
        write_results([], skipped=True)
        print(RESULTS_MD.read_text(encoding="utf-8"))
        return

    rows = []
    with ANSWERS_JSONL.open("w", encoding="utf-8") as answers_out:
        for record in records:
            answer, ttft_ms, total_ms, model = run_llm(record["prompt"])
            rows.append(score_answer(record, answer, ttft_ms, total_ms, model))
            answers_out.write(json.dumps({**record, "answer": answer, "ttft_ms": ttft_ms, "total_ms": total_ms, "model": model}, ensure_ascii=False) + "\n")
    write_results(rows, skipped=False)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
