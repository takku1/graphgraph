from __future__ import annotations

import csv
import json
import math
import re
import shutil
import sqlite3
import time
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "seed_context.json"
TASKS = ROOT / "data" / "tasks.json"
OUT = ROOT / "out"
MD_DIR = OUT / "md"
DB_PATH = OUT / "context_graph.db"
GRAPH_PATH = OUT / "graph.json"
RESULTS_CSV = OUT / "results.csv"
RESULTS_MD = OUT / "results.md"

STOPWORDS = {
    "a", "an", "and", "are", "be", "by", "can", "for", "from", "get", "how",
    "if", "in", "into", "is", "of", "on", "or", "should", "the", "to",
    "what", "when", "which", "with"
}


def load_seed() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def load_tasks() -> list[dict]:
    return json.loads(TASKS.read_text(encoding="utf-8"))


def tokenize(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)
        if t.lower() not in STOPWORDS
    }


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def get_token_counter():
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return "tiktoken:cl100k_base", lambda text: len(enc.encode(text))
    except Exception:
        return "approx:ceil(chars/4)", approx_tokens


def reset_out() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    MD_DIR.mkdir(parents=True)


def build_markdown(seed: dict) -> None:
    by_path: dict[str, list[dict]] = defaultdict(list)
    for node in seed["nodes"]:
        by_path[node["path"]].append(node)

    for rel_path, nodes in by_path.items():
        path = MD_DIR / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {Path(rel_path).stem.replace('_', ' ').title()}", ""]
        for node in nodes:
            lines.extend([
                f"## {node['label']} ({node['id']})",
                "",
                f"Kind: {node['kind']}",
                f"Summary: {node['summary']}",
                "",
                "Facts:",
            ])
            lines.extend(f"- {fact}" for fact in node["facts"])
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


def build_graph(seed: dict) -> None:
    GRAPH_PATH.write_text(json.dumps(seed, indent=2), encoding="utf-8")


def build_sqlite(seed: dict) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(
        """
        create table nodes (
            id text primary key,
            label text not null,
            kind text not null,
            path text not null,
            summary text not null,
            facts text not null
        );
        create table edges (
            source text not null,
            target text not null,
            type text not null,
            weight real not null
        );
        create table docs (
            path text primary key,
            body text not null
        );
        """
    )
    for node in seed["nodes"]:
        cur.execute(
            "insert into nodes values (?, ?, ?, ?, ?, ?)",
            (
                node["id"],
                node["label"],
                node["kind"],
                node["path"],
                node["summary"],
                "\n".join(node["facts"]),
            ),
        )
    for edge in seed["edges"]:
        cur.execute(
            "insert into edges values (?, ?, ?, ?)",
            (edge["source"], edge["target"], edge["type"], edge["weight"]),
        )
    for path in MD_DIR.rglob("*.md"):
        cur.execute(
            "insert into docs values (?, ?)",
            (str(path.relative_to(MD_DIR)).replace("\\", "/"), path.read_text(encoding="utf-8")),
        )
    con.commit()
    con.close()


def render_node(node: dict) -> str:
    facts = "\n".join(f"- {fact}" for fact in node["facts"])
    return (
        f"## {node['label']} ({node['id']})\n"
        f"Kind: {node['kind']}\n"
        f"Path: {node['path']}\n"
        f"Summary: {node['summary']}\n"
        f"{facts}\n"
    )


def score_text(query_tokens: set[str], text: str) -> int:
    haystack = tokenize(text)
    return len(query_tokens & haystack)


def select_nodes(seed: dict, question: str, limit: int = 4) -> list[str]:
    q = tokenize(question)
    scored = []
    for node in seed["nodes"]:
        text = " ".join([node["label"], node["kind"], node["summary"], " ".join(node["facts"])])
        score = score_text(q, text)
        if score:
            scored.append((score, node["id"]))
    scored.sort(reverse=True)
    return [node_id for _, node_id in scored[:limit]]


def expand_graph(seed: dict, start_ids: list[str], hops: int = 1) -> tuple[set[str], list[dict]]:
    node_ids = set(start_ids)
    selected_edges: list[dict] = []
    frontier = set(start_ids)
    for _ in range(hops):
        next_frontier = set()
        for edge in seed["edges"]:
            if edge["source"] in frontier or edge["target"] in frontier:
                selected_edges.append(edge)
                if edge["source"] not in node_ids:
                    next_frontier.add(edge["source"])
                if edge["target"] not in node_ids:
                    next_frontier.add(edge["target"])
        node_ids |= next_frontier
        frontier = next_frontier
    return node_ids, selected_edges


def context_full_markdown(seed: dict, question: str) -> str:
    parts = []
    for path in sorted(MD_DIR.rglob("*.md")):
        rel = path.relative_to(MD_DIR)
        parts.append(f"<!-- source: {rel} -->\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def context_keyword_markdown(seed: dict, question: str) -> str:
    q = tokenize(question)
    docs = []
    for path in MD_DIR.rglob("*.md"):
        body = path.read_text(encoding="utf-8")
        docs.append((score_text(q, body), str(path.relative_to(MD_DIR)), body))
    docs.sort(reverse=True)
    chosen = [doc for doc in docs if doc[0] > 0][:3]
    return "\n\n".join(f"<!-- source: {rel} -->\n{body}" for _, rel, body in chosen)


def context_sqlite(seed: dict, question: str) -> str:
    start_ids = select_nodes(seed, question)
    node_ids, selected_edges = expand_graph(seed, start_ids, hops=1)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    nodes = []
    for node_id in sorted(node_ids):
        row = cur.execute(
            "select id, label, kind, path, summary, facts from nodes where id = ?",
            (node_id,),
        ).fetchone()
        if row:
            nodes.append(row)
    con.close()
    lines = ["# SQLite Context Packet", "", "Nodes:"]
    for node_id, label, kind, path, summary, facts in nodes:
        lines.append(f"- {node_id} {label} [{kind}] {path}: {summary}")
        for fact in facts.splitlines():
            lines.append(f"  - {fact}")
    lines.append("")
    lines.append("Edges:")
    for edge in selected_edges:
        lines.append(f"- {edge['source']} -{edge['type']}-> {edge['target']} ({edge['weight']})")
    return "\n".join(lines)


def context_graph_json(seed: dict, question: str) -> str:
    start_ids = select_nodes(seed, question)
    node_ids, selected_edges = expand_graph(seed, start_ids, hops=2)
    nodes = [node for node in seed["nodes"] if node["id"] in node_ids]
    return json.dumps({"nodes": nodes, "edges": selected_edges}, separators=(",", ":"))


def context_compact_graph(seed: dict, question: str) -> str:
    start_ids = select_nodes(seed, question)
    node_ids, selected_edges = expand_graph(seed, start_ids, hops=2)
    node_by_id = {node["id"]: node for node in seed["nodes"]}
    lines = ["# Compact Graph Packet", "N:"]
    for node_id in sorted(node_ids):
        node = node_by_id[node_id]
        lines.append(f"{node_id}|{node['label']}|{node['kind']}|{node['path']}")
    lines.append("E:")
    for edge in selected_edges:
        lines.append(f"{edge['source']}|{edge['type']}|{edge['target']}|{edge['weight']}")
    return "\n".join(lines)


def context_hybrid(seed: dict, question: str) -> str:
    start_ids = select_nodes(seed, question)
    node_ids, selected_edges = expand_graph(seed, start_ids, hops=1)
    node_by_id = {node["id"]: node for node in seed["nodes"]}
    lines = ["# Hybrid Context Packet", "", "Relevant relationships:"]
    for edge in selected_edges:
        source = node_by_id[edge["source"]]
        target = node_by_id[edge["target"]]
        lines.append(
            f"- {source['label']} ({edge['source']}) {edge['type']} "
            f"{target['label']} ({edge['target']}); weight={edge['weight']}"
        )
    lines.append("")
    lines.append("Grounding snippets:")
    for node_id in sorted(node_ids):
        node = node_by_id[node_id]
        lines.append(f"- {node['label']} ({node_id}) from {node['path']}: {node['summary']}")
        for fact in node["facts"][:2]:
            lines.append(f"  - {fact}")
    return "\n".join(lines)


def context_semantic_arrow(seed: dict, question: str) -> str:
    start_ids = select_nodes(seed, question)
    node_ids, selected_edges = expand_graph(seed, start_ids, hops=2)
    node_by_id = {node["id"]: node for node in seed["nodes"]}
    lines = ["@nodes"]
    for node_id in sorted(node_ids):
        node = node_by_id[node_id]
        lines.append(f"{node_id}: {node['label']}")
    lines.append("")
    lines.append("@edges")
    for edge in selected_edges:
        lines.append(f"{edge['source']} -{edge['type']}-> {edge['target']} ({edge['weight']})")
    return "\n".join(lines)


def context_gg_max(seed: dict, question: str) -> str:
    start_ids = select_nodes(seed, question)
    node_ids, selected_edges = expand_graph(seed, start_ids, hops=2)
    node_by_id = {node["id"]: node for node in seed["nodes"]}
    relations = sorted({edge["type"] for edge in seed["edges"]})
    relation_ids = {rel: i + 1 for i, rel in enumerate(relations)}

    lines = ["[r]"]
    for rel, rel_id in relation_ids.items():
        lines.append(f"{rel_id}:{rel}")
    lines.append("[n]")
    node_to_idx = {node_id: str(i + 1) for i, node_id in enumerate(sorted(node_ids))}
    for node_id, idx in node_to_idx.items():
        node = node_by_id[node_id]
        lines.append(f"{idx} {node['label']}")
    lines.append("[e]")
    for edge in selected_edges:
        rel_id = relation_ids.get(edge["type"], edge["type"])
        src_idx = node_to_idx[edge["source"]]
        tgt_idx = node_to_idx[edge["target"]]
        lines.append(f"{src_idx} {tgt_idx} {rel_id} {edge['weight']}")
    return "\n".join(lines)


STRATEGIES = {
    "full_markdown": context_full_markdown,
    "keyword_markdown": context_keyword_markdown,
    "sqlite_graph_tables": context_sqlite,
    "graph_json_2hop": context_graph_json,
    "compact_graph_2hop": context_compact_graph,
    "semantic_arrow_2hop": context_semantic_arrow,
    "gg_max_2hop": context_gg_max,
    "hybrid_graph_markdown": context_hybrid,
}


def evidence_metrics(context: str, task: dict) -> tuple[float, float]:
    seed = load_seed()
    node_by_id = {node["id"]: node for node in seed["nodes"]}
    lower_context = context.lower()

    def has_node(node_id: str) -> bool:
        node = node_by_id[node_id]
        return node_id.lower() in lower_context or node["label"].lower() in lower_context

    def has_edge(source_id: str, target_id: str) -> bool:
        source = node_by_id[source_id]["label"].lower()
        target = node_by_id[target_id]["label"].lower()

        if "[e]" in lower_context and "[n]" in lower_context:
            parts = lower_context.split("[e]", 1)
            nodes_part = parts[0].split("[n]", 1)[1]
            edges_part = parts[1]
            local_to_label = {}
            for line in nodes_part.splitlines():
                line = line.strip()
                if not line:
                    continue
                node_parts = line.split(None, 1)
                if len(node_parts) == 2:
                    local_to_label[node_parts[0]] = node_parts[1].lower()
            for line in edges_part.splitlines():
                line = line.strip()
                if not line:
                    continue
                edge_parts = line.split()
                if len(edge_parts) == 4:
                    s_local, t_local, rel_id, _w = edge_parts
                    if local_to_label.get(s_local) == source and local_to_label.get(t_local) == target:
                        return True
            return False

        matching = [
            edge for edge in seed["edges"]
            if edge["source"] == source_id and edge["target"] == target_id
        ]
        if not matching:
            return False
        relation = matching[0]["type"].lower()
        relation_aliases = {
            "calls": ["calls", "-calls->"],
            "writes": ["writes", "-writes->", "records", "emits"],
            "reads": ["reads", "-reads->"],
            "checks": ["checks", "-checks->", "refuses", "marks"],
            "uses": ["uses", "-uses->"],
            "reads_claims_from": ["reads_claims_from", "claims", "supplied by"],
            "authorizes_with": ["authorizes_with", "calls", "before privileged"],
            "updates": ["updates", "-updates->", "clear", "updates"],
            "triggers": ["triggers", "-triggers->", "trigger"],
            "stores_state_in": ["stores_state_in", "stores", "lock state"],
            "revokes": ["revokes", "-revokes->", "revokes"],
        }.get(relation, [relation])

        explicit_ids = (
            f"{source_id}|{relation}|{target_id}" in context
            or f"{source_id} -{relation}-> {target_id}" in context
            or f'"source":"{source_id}"' in context and f'"target":"{target_id}"' in context
        )
        if explicit_ids:
            return True

        aliases = [alias.lower() for alias in relation_aliases]
        for line in lower_context.splitlines():
            if source in line and target in line and any(alias in line for alias in aliases):
                return True

        source_heading = f"## {node_by_id[source_id]['label'].lower()} ({source_id.lower()})"
        start = lower_context.find(source_heading)
        if start == -1:
            return False
        next_heading = lower_context.find("\n## ", start + len(source_heading))
        source_block = lower_context[start:] if next_heading == -1 else lower_context[start:next_heading]
        return target in source_block and any(alias in source_block for alias in aliases)

    node_hits = sum(1 for node_id in task["expected_nodes"] if has_node(node_id))
    node_recall = node_hits / len(task["expected_nodes"])

    edge_hits = 0
    for source, target in task["expected_edges"]:
        if has_edge(source, target):
            edge_hits += 1
    edge_recall = edge_hits / len(task["expected_edges"])
    return node_recall, edge_recall


def benchmark(seed: dict, tasks: list[dict]) -> list[dict]:
    rows = []
    tokenizer_name, count_tokens = get_token_counter()
    for task in tasks:
        for strategy_name, strategy in STRATEGIES.items():
            start = time.perf_counter()
            context = strategy(seed, task["question"])
            elapsed_ms = (time.perf_counter() - start) * 1000
            token_count = count_tokens(context)
            node_recall, edge_recall = evidence_metrics(context, task)
            score = ((node_recall * 0.6) + (edge_recall * 0.4)) / math.log10(token_count + 10)
            rows.append(
                {
                    "task": task["id"],
                    "strategy": strategy_name,
                    "tokenizer": tokenizer_name,
                    "latency_ms": round(elapsed_ms, 3),
                    "chars": len(context),
                    "tokens": token_count,
                    "node_recall": round(node_recall, 3),
                    "edge_recall": round(edge_recall, 3),
                    "score": round(score, 4),
                }
            )
    return rows


def write_results(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["strategy"]].append(row)

    tokenizer = rows[0]["tokenizer"]
    lines = ["# Context Graph Benchmark Results", "", f"Tokenizer: `{tokenizer}`", ""]
    lines.append("| Strategy | Avg latency ms | Avg tokens | Avg node recall | Avg edge recall | Avg score |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for strategy in sorted(grouped):
        items = grouped[strategy]
        avg = lambda key: sum(float(item[key]) for item in items) / len(items)
        lines.append(
            f"| {strategy} | {avg('latency_ms'):.3f} | {avg('tokens'):.1f} | "
            f"{avg('node_recall'):.3f} | {avg('edge_recall'):.3f} | {avg('score'):.4f} |"
        )
    lines.append("")
    lines.append("Lower token counts are better when recall is comparable.")
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    seed = load_seed()
    tasks = load_tasks()
    reset_out()
    build_markdown(seed)
    build_graph(seed)
    build_sqlite(seed)
    rows = benchmark(seed, tasks)
    write_results(rows)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
