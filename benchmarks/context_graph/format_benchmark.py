from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
RESULTS_CSV = OUT / "format_results.csv"
RESULTS_MD = OUT / "format_results.md"


def get_token_counter() -> tuple[str, Callable[[str], int]]:
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return "tiktoken:cl100k_base", lambda text: len(enc.encode(text))
    except Exception:
        return "approx:ceil(chars/4)", lambda text: max(1, math.ceil(len(text) / 4))


def make_graph(size: int) -> dict:
    if size < 3:
        raise ValueError("size must be >= 3")
    nodes = [
        {"id": str(i), "name": name_for(i), "type": "file"}
        for i in range(1, size + 1)
    ]
    edges = []
    for i in range(1, size):
        edges.append({"source": str(i), "target": str(i + 1), "dependency": round(0.50 + ((i % 50) / 100), 2)})
    for i in range(1, size - 2, 3):
        edges.append({"source": str(i), "target": str(i + 3), "dependency": round(0.70 + ((i % 20) / 100), 2)})
    return {"nodes": nodes, "edges": edges}


def name_for(i: int) -> str:
    base = [
        "AuthService", "Database", "TokenGen", "UserStore", "SessionStore",
        "PermissionService", "AuditLog", "AdminPanel", "LockoutPolicy",
        "PasswordResetFlow", "EmailLinkSigner", "SigningKeyRing",
    ]
    if i <= len(base):
        return base[i - 1]
    return f"Module{i:03d}"


def fmt_json(graph: dict) -> str:
    return json.dumps(graph, indent=2)


def fmt_json_min(graph: dict) -> str:
    return json.dumps(graph, separators=(",", ":"))


def fmt_sql_rows(graph: dict) -> str:
    node_rows = " | ".join(f"{n['id']},{n['name']},{n['type']}" for n in graph["nodes"])
    edge_rows = " | ".join(f"{e['source']},{e['target']},{e['dependency']}" for e in graph["edges"])
    return f"TABLE nodes: id,name,type | {node_rows}\nTABLE edges: source,target,weight | {edge_rows}"


def fmt_graphml(graph: dict) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <graph id="G" edgedefault="directed">',
    ]
    for node in graph["nodes"]:
        lines.append(f'    <node id="{node["id"]}"><data key="name">{node["name"]}</data><data key="type">{node["type"]}</data></node>')
    for idx, edge in enumerate(graph["edges"], 1):
        lines.append(
            f'    <edge id="e{idx}" source="{edge["source"]}" target="{edge["target"]}">'
            f'<data key="weight">{edge["dependency"]}</data></edge>'
        )
    lines.extend(["  </graph>", "</graphml>"])
    return "\n".join(lines)


def fmt_markdown_compact(graph: dict) -> str:
    lines = ["# Project Graph", "", "Nodes:"]
    for node in graph["nodes"]:
        lines.append(f"- {node['id']}: {node['name']} ({node['type']})")
    lines.append("")
    lines.append("Edges:")
    for edge in graph["edges"]:
        lines.append(f"- {edge['source']} depends on {edge['target']} weight {edge['dependency']}")
    return "\n".join(lines)


def fmt_low_level_adj(graph: dict) -> str:
    lines = ["<g>"]
    lines.extend(f"{node['id']}:{node['name']}" for node in graph["nodes"])
    lines.append("<a>")
    lines.extend(f"{edge['source']},{edge['target']},{edge['dependency']}" for edge in graph["edges"])
    lines.extend(["</a>", "</g>"])
    return "\n".join(lines)


def fmt_relation_coded_adj(graph: dict) -> str:
    lines = ["<g>", "r1:dep", "<n>"]
    lines.extend(f"{node['id']}:{node['name']}" for node in graph["nodes"])
    lines.append("</n>")
    lines.append("<a>")
    lines.extend(f"{edge['source']},{edge['target']},1,{edge['dependency']}" for edge in graph["edges"])
    lines.extend(["</a>", "</g>"])
    return "\n".join(lines)


def fmt_semantic_arrow(graph: dict) -> str:
    lines = ["@nodes"]
    for node in graph["nodes"]:
        lines.append(f"{node['id']}: {node['name']}")
    lines.append("")
    lines.append("@edges")
    for edge in graph["edges"]:
        lines.append(f"{edge['source']} -dep-> {edge['target']} ({edge['dependency']})")
    return "\n".join(lines)


def fmt_gg_max(graph: dict) -> str:
    lines = ["[r]", "1:dep", "[n]"]
    for node in graph["nodes"]:
        lines.append(f"{node['id']} {node['name']}")
    lines.append("[e]")
    for edge in graph["edges"]:
        lines.append(f"{edge['source']} {edge['target']} 1 {edge['dependency']}")
    return "\n".join(lines)


def fmt_csr_arrays(graph: dict) -> str:
    node_count = len(graph["nodes"])
    by_source: dict[int, list[dict]] = {i: [] for i in range(1, node_count + 1)}
    for edge in graph["edges"]:
        by_source[int(edge["source"])].append(edge)

    ptr = [0]
    col = []
    weights = []
    for source in range(1, node_count + 1):
        outgoing = sorted(by_source[source], key=lambda e: int(e["target"]))
        col.extend(int(e["target"]) for e in outgoing)
        weights.extend(e["dependency"] for e in outgoing)
        ptr.append(len(col))

    labels = ",".join(f"{node['id']}:{node['name']}" for node in graph["nodes"])
    ptr_s = ",".join(str(v) for v in ptr)
    col_s = ",".join(str(v) for v in col)
    weight_s = ",".join(str(v) for v in weights)
    return f"N={labels}\nR=dep\nCSR ptr={ptr_s}\ncol={col_s}\nw={weight_s}"


def fmt_gg_lex(graph: dict) -> str:
    lines = ["[r]", "1:dep", "[n]"]
    seen = set()
    node_to_id = {}
    for node in graph["nodes"]:
        label = node["name"]
        base = "".join(c.lower() for c in label if c.isalnum())
        if not base:
            base = "node"
        candidate = base[:8]
        if candidate in seen:
            suffix = 2
            while f"{candidate[:6]}{suffix}" in seen:
                suffix += 1
            candidate = f"{candidate[:6]}{suffix}"
        seen.add(candidate)
        node_to_id[node["id"]] = candidate
        lines.append(f"{candidate} {label}")
    lines.append("[e]")
    for edge in graph["edges"]:
        src_id = node_to_id[edge["source"]]
        tgt_id = node_to_id[edge["target"]]
        lines.append(f"{src_id} {tgt_id} 1 {edge['dependency']}")
    return "\n".join(lines)


FORMATTERS: dict[str, Callable[[dict], str]] = {
    "json_pretty": fmt_json,
    "json_minified": fmt_json_min,
    "sql_rows": fmt_sql_rows,
    "graphml": fmt_graphml,
    "markdown_compact": fmt_markdown_compact,
    "low_level_adj": fmt_low_level_adj,
    "relation_coded_adj": fmt_relation_coded_adj,
    "semantic_arrow": fmt_semantic_arrow,
    "gg_max": fmt_gg_max,
    "gg_lex": fmt_gg_lex,
    "csr_arrays": fmt_csr_arrays,
}


def optional_openai_latency(prompt: str) -> tuple[float | None, float | None, str]:
    if os.environ.get("RUN_OPENAI_LATENCY") != "1":
        return None, None, "skipped: set RUN_OPENAI_LATENCY=1"
    if not os.environ.get("OPENAI_API_KEY"):
        return None, None, "skipped: OPENAI_API_KEY missing"
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        return None, None, f"skipped: openai package unavailable ({exc.__class__.__name__})"

    model = os.environ.get("OPENAI_LATENCY_MODEL", "gpt-4o-mini")
    client = OpenAI()
    start = time.perf_counter()
    first_token_at = None
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=64,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta and first_token_at is None:
            first_token_at = time.perf_counter()
    end = time.perf_counter()
    ttft_ms = None if first_token_at is None else (first_token_at - start) * 1000
    total_ms = (end - start) * 1000
    return ttft_ms, total_ms, f"openai:{model}"


def run() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    tokenizer_name, count_tokens = get_token_counter()
    rows = []
    for size in [3, 12, 50, 200]:
        graph = make_graph(size)
        edge_count = len(graph["edges"])
        payloads = {name: formatter(graph) for name, formatter in FORMATTERS.items()}
        max_tokens = max(count_tokens(payload) for payload in payloads.values())
        for name, payload in payloads.items():
            prompt = (
                "Analyze this project context graph. Answer only with the direct "
                "dependencies of node 1.\n\n"
                f"{payload}"
            )
            tokens = count_tokens(payload)
            prompt_tokens = count_tokens(prompt)
            ttft_ms, total_ms, latency_source = optional_openai_latency(prompt)
            rows.append(
                {
                    "graph_size_nodes": size,
                    "graph_size_edges": edge_count,
                    "format": name,
                    "tokenizer": tokenizer_name,
                    "chars": len(payload),
                    "tokens": tokens,
                    "prompt_tokens": prompt_tokens,
                    "relative_to_worst": round(tokens / max_tokens, 4),
                    "ttft_ms": "" if ttft_ms is None else round(ttft_ms, 3),
                    "total_ms": "" if total_ms is None else round(total_ms, 3),
                    "latency_source": latency_source,
                }
            )
    return rows


def write(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    tokenizer = rows[0]["tokenizer"]
    lines = ["# Format Overhead Benchmark", "", f"Tokenizer: `{tokenizer}`", ""]
    lines.append("| Nodes | Edges | Format | Tokens | Prompt tokens | Relative to worst | Latency source |")
    lines.append("| ---: | ---: | --- | ---: | ---: | ---: | --- |")
    for row in rows:
        lines.append(
            f"| {row['graph_size_nodes']} | {row['graph_size_edges']} | {row['format']} | "
            f"{row['tokens']} | {row['prompt_tokens']} | {row['relative_to_worst']} | "
            f"{row['latency_source']} |"
        )
    lines.append("")
    lines.append("Relative to worst is computed within each graph size; lower is better.")
    lines.append("Latency columns are blank unless `RUN_OPENAI_LATENCY=1` is set.")
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
