from __future__ import annotations

import csv
import json
import math
import random
import re
import shutil
import sqlite3
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "benchmark_manifest.json"
OUT = ROOT / "out" / "protocol"
PACKETS = OUT / "packets"
RESULTS_CSV = OUT / "protocol_results.csv"
SUMMARY_MD = OUT / "protocol_summary.md"
PROMPTS_JSONL = OUT / "saved_prompts.jsonl"

RELATIONS = ["calls", "imports", "reads", "writes", "uses", "tests", "configures"]
KINDS = ["service", "component", "data", "workflow", "policy", "ui", "test", "config"]
STOPWORDS = {
    "a", "an", "and", "are", "as", "be", "by", "can", "for", "from", "how",
    "if", "in", "is", "it", "of", "on", "or", "the", "to", "what", "when",
    "where", "which", "with", "would"
}


@dataclass(frozen=True)
class CorpusConfig:
    name: str
    nodes: int
    extra_edges_per_node: float
    noise_ratio: float
    enabled: bool


def get_token_counter() -> tuple[str, Callable[[str], int]]:
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return "tiktoken:cl100k_base", lambda text: len(enc.encode(text))
    except Exception:
        return "approx:ceil(chars/4)", lambda text: max(1, math.ceil(len(text) / 4))


def tokenize(text: str) -> list[str]:
    return [
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)
        if t.lower() not in STOPWORDS
    ]


def node_label(i: int) -> str:
    anchors = [
        "AuthService", "Database", "TokenGen", "UserStore", "SessionStore",
        "PermissionService", "AuditLog", "AdminPanel", "LockoutPolicy",
        "PasswordResetFlow", "EmailLinkSigner", "SigningKeyRing",
    ]
    if i <= len(anchors):
        return anchors[i - 1]
    groups = ["Billing", "Search", "Notify", "Import", "Export", "Profile", "Report", "Policy"]
    suffixes = ["Service", "Store", "Worker", "Controller", "Adapter", "Validator", "Flow", "Client"]
    return f"{groups[i % len(groups)]}{suffixes[(i // len(groups)) % len(suffixes)]}{i:04d}"


def make_corpus(config: CorpusConfig, seed: int) -> dict:
    rng = random.Random(seed + config.nodes + int(config.extra_edges_per_node * 100))
    nodes = []
    for i in range(1, config.nodes + 1):
        node_id = f"N{i:05d}"
        label = node_label(i)
        kind = KINDS[i % len(KINDS)]
        path = f"{kind}s/{label}.md"
        summary = f"{label} is a {kind} module in subsystem {i % 17}."
        facts = [
            f"{label} owns operation op_{i % 31} and emits event evt_{i % 23}.",
            f"{label} is maintained by team_{i % 11} and has risk tier {1 + (i % 4)}.",
        ]
        if rng.random() < config.noise_ratio:
            facts.append(f"{label} note: unrelated planning tag noise_{rng.randint(1, 999)}.")
        nodes.append({"id": node_id, "label": label, "kind": kind, "path": path, "summary": summary, "facts": facts})

    edges = []
    for i in range(1, config.nodes):
        edges.append(edge(i, i + 1, RELATIONS[i % len(RELATIONS)], 0.80))
    for i in range(1, min(config.nodes - 3, 40), 4):
        edges.append(edge(i, i + 3, "calls", 0.93))

    extra_count = int(config.nodes * config.extra_edges_per_node)
    seen = {(e["source"], e["target"], e["type"]) for e in edges}
    while len(edges) < config.nodes - 1 + extra_count:
        src = rng.randint(1, config.nodes)
        jump = rng.randint(2, min(40, max(2, config.nodes - 1)))
        tgt = ((src + jump - 1) % config.nodes) + 1
        rel = rng.choice(RELATIONS)
        key = (nid(src), nid(tgt), rel)
        if key in seen or src == tgt:
            continue
        seen.add(key)
        edges.append(edge(src, tgt, rel, round(0.45 + rng.random() * 0.50, 2)))

    return {"name": config.name, "nodes": nodes, "edges": edges}


def nid(i: int) -> str:
    return f"N{i:05d}"


def edge(src: int, tgt: int, rel: str, weight: float) -> dict:
    return {"source": nid(src), "target": nid(tgt), "type": rel, "weight": weight}


def build_indexes(corpus: dict) -> dict:
    nodes = {n["id"]: n for n in corpus["nodes"]}
    outgoing: dict[str, list[dict]] = defaultdict(list)
    incoming: dict[str, list[dict]] = defaultdict(list)
    for e in corpus["edges"]:
        outgoing[e["source"]].append(e)
        incoming[e["target"]].append(e)
    doc_text = {}
    for n in corpus["nodes"]:
        doc_text[n["id"]] = " ".join([n["label"], n["kind"], n["summary"], " ".join(n["facts"])])
    return {"nodes": nodes, "outgoing": outgoing, "incoming": incoming, "doc_text": doc_text}


def make_tasks(corpus: dict) -> list[dict]:
    idx = build_indexes(corpus)
    nodes = list(idx["nodes"])
    tasks = []

    direct = first_node_with_edges(idx["outgoing"], nodes)
    reverse = first_node_with_edges(idx["incoming"], nodes)
    path = find_path(idx, nodes[0], nodes[min(len(nodes) - 1, 6)], max_depth=6) or nodes[:4]
    blast = direct
    summary = nodes[min(len(nodes) - 1, 8)]
    negative_pair = [nodes[0], nodes[-1]]

    tasks.append(task_direct(idx, direct))
    tasks.append(task_reverse(idx, reverse))
    tasks.append(task_path(idx, path))
    tasks.append(task_blast(idx, blast))
    tasks.append(task_summary(idx, summary))
    tasks.append({
        "id": "negative_query",
        "class": "negative_query",
        "question": f"Is {idx['nodes'][negative_pair[0]]['label']} directly connected to {idx['nodes'][negative_pair[1]]['label']}?",
        "expected_nodes": negative_pair,
        "expected_edges": [],
        "expected_path": [],
        "negative": True,
    })
    return tasks


def first_node_with_edges(edge_index: dict[str, list[dict]], nodes: list[str]) -> str:
    for n in nodes:
        if edge_index.get(n):
            return n
    return nodes[0]


def task_direct(idx: dict, node_id: str) -> dict:
    edges = idx["outgoing"][node_id][:3]
    label = idx["nodes"][node_id]["label"]
    return {
        "id": "direct_lookup",
        "class": "direct_lookup",
        "question": f"What does {label} directly depend on or call?",
        "expected_nodes": [node_id] + [e["target"] for e in edges],
        "expected_edges": [(e["source"], e["target"], e["type"]) for e in edges],
        "expected_path": [],
        "negative": False,
    }


def task_reverse(idx: dict, node_id: str) -> dict:
    edges = idx["incoming"][node_id][:3]
    label = idx["nodes"][node_id]["label"]
    return {
        "id": "reverse_lookup",
        "class": "reverse_lookup",
        "question": f"What modules depend on {label}?",
        "expected_nodes": [node_id] + [e["source"] for e in edges],
        "expected_edges": [(e["source"], e["target"], e["type"]) for e in edges],
        "expected_path": [],
        "negative": False,
    }


def task_path(idx: dict, path_nodes: list[str]) -> dict:
    labels = idx["nodes"][path_nodes[0]]["label"], idx["nodes"][path_nodes[-1]]["label"]
    edge_triples = []
    for a, b in zip(path_nodes, path_nodes[1:]):
        match = next((e for e in idx["outgoing"][a] if e["target"] == b), None)
        if match:
            edge_triples.append((a, b, match["type"]))
    return {
        "id": "multi_hop_path",
        "class": "multi_hop_path",
        "question": f"What path connects {labels[0]} to {labels[1]}?",
        "expected_nodes": path_nodes,
        "expected_edges": edge_triples,
        "expected_path": path_nodes,
        "negative": False,
    }


def task_blast(idx: dict, node_id: str) -> dict:
    node_ids, edges = expand(idx, [node_id], hops=2)
    label = idx["nodes"][node_id]["label"]
    return {
        "id": "blast_radius",
        "class": "blast_radius",
        "question": f"If {label} changes, what is the two-hop blast radius?",
        "expected_nodes": sorted(node_ids)[:20],
        "expected_edges": [(e["source"], e["target"], e["type"]) for e in edges[:30]],
        "expected_path": [],
        "negative": False,
    }


def task_summary(idx: dict, node_id: str) -> dict:
    node_ids, edges = expand(idx, [node_id], hops=1)
    label = idx["nodes"][node_id]["label"]
    return {
        "id": "subsystem_summary",
        "class": "subsystem_summary",
        "question": f"Summarize the local subsystem around {label}.",
        "expected_nodes": sorted(node_ids),
        "expected_edges": [(e["source"], e["target"], e["type"]) for e in edges],
        "expected_path": [],
        "negative": False,
    }


def find_path(idx: dict, start: str, target: str, max_depth: int) -> list[str] | None:
    queue = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        if len(path) > max_depth:
            continue
        cur = path[-1]
        if cur == target:
            return path
        for e in idx["outgoing"].get(cur, []):
            nxt = e["target"]
            if nxt not in seen:
                seen.add(nxt)
                queue.append(path + [nxt])
    return None


def expand(idx: dict, starts: list[str], hops: int) -> tuple[set[str], list[dict]]:
    node_ids = set(starts)
    edges = []
    frontier = set(starts)
    for _ in range(hops):
        next_frontier = set()
        for n in frontier:
            for e in idx["outgoing"].get(n, []) + idx["incoming"].get(n, []):
                edges.append(e)
                if e["source"] not in node_ids:
                    next_frontier.add(e["source"])
                if e["target"] not in node_ids:
                    next_frontier.add(e["target"])
        node_ids |= next_frontier
        frontier = next_frontier
    return node_ids, dedupe_edges(edges)


def dedupe_edges(edges: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for e in edges:
        key = (e["source"], e["target"], e["type"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def render_markdown_docs(corpus: dict, path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    count = 0
    for node in corpus["nodes"]:
        doc = path / node["path"]
        doc.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {node['label']}",
            "",
            f"ID: {node['id']}",
            f"Kind: {node['kind']}",
            f"Summary: {node['summary']}",
            "",
            "Facts:",
            *[f"- {fact}" for fact in node["facts"]],
        ]
        doc.write_text("\n".join(lines), encoding="utf-8")
        count += 1
    return count


def render_sqlite(corpus: dict, path: Path) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        drop table if exists nodes;
        drop table if exists edges;
        create table nodes(id text primary key, label text, kind text, path text, summary text, facts text);
        create table edges(source text, target text, type text, weight real);
        """
    )
    for n in corpus["nodes"]:
        cur.execute("insert into nodes values (?, ?, ?, ?, ?, ?)", (n["id"], n["label"], n["kind"], n["path"], n["summary"], "\n".join(n["facts"])))
    for e in corpus["edges"]:
        cur.execute("insert into edges values (?, ?, ?, ?)", (e["source"], e["target"], e["type"], e["weight"]))
    con.commit()
    con.close()


def score_nodes(idx: dict, question: str, limit: int) -> list[str]:
    q = Counter(tokenize(question))
    scored = []
    for node_id, text in idx["doc_text"].items():
        tokens = Counter(tokenize(text))
        score = sum(q[t] * tokens[t] for t in q)
        if score:
            scored.append((score, node_id))
    scored.sort(reverse=True)
    return [node_id for _, node_id in scored[:limit]]


def score_nodes_bm25(idx: dict, question: str, limit: int) -> list[str]:
    q = tokenize(question)
    docs = {node_id: tokenize(text) for node_id, text in idx["doc_text"].items()}
    avgdl = sum(len(toks) for toks in docs.values()) / max(1, len(docs))
    df = Counter(t for toks in docs.values() for t in set(toks))
    n_docs = len(docs)
    scored = []
    for node_id, toks in docs.items():
        tf = Counter(toks)
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + 1.2 * (1 - 0.75 + 0.75 * len(toks) / avgdl)
            score += idf * ((tf[term] * 2.2) / denom)
        if score:
            scored.append((score, node_id))
    scored.sort(reverse=True)
    return [node_id for _, node_id in scored[:limit]]


def packet_full_markdown(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    nodes = set(idx["nodes"])
    return render_packet(idx, nodes, corpus["edges"], mode="markdown_full"), nodes, corpus["edges"]


def packet_keyword(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    nodes = set(score_nodes(idx, task["question"], limit=8))
    return render_packet(idx, nodes, edges_between(corpus, nodes), mode="markdown"), nodes, edges_between(corpus, nodes)


def packet_bm25(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    nodes = set(score_nodes_bm25(idx, task["question"], limit=8))
    return render_packet(idx, nodes, edges_between(corpus, nodes), mode="markdown"), nodes, edges_between(corpus, nodes)


def packet_graph_1hop(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="compact"), nodes, edges


def packet_graph_1hop_lowlevel(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="lowlevel"), nodes, edges


def packet_graph_1hop_sql(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="sql"), nodes, edges


def packet_graph_2hop(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="compact"), nodes, edges


def packet_graph_2hop_lowlevel(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="lowlevel"), nodes, edges


def packet_graph_2hop_sql(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="sql"), nodes, edges


def packet_hybrid(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = set(score_nodes_bm25(idx, task["question"], limit=5) + score_nodes(idx, task["question"], limit=5))
    nodes, edges = expand(idx, list(starts), hops=1)
    return render_packet(idx, nodes, edges, mode="hybrid"), nodes, edges


def packet_hierarchical(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=6)
    groups: dict[str, list[str]] = defaultdict(list)
    for node_id in starts:
        groups[idx["nodes"][node_id]["kind"]].append(node_id)
    lines = ["# Hierarchical Summary Packet"]
    nodes = set(starts)
    for kind, ids in sorted(groups.items()):
        lines.append(f"## {kind}")
        labels = ", ".join(idx["nodes"][i]["label"] for i in ids)
        lines.append(f"Relevant nodes: {labels}")
        for i in ids[:3]:
            lines.append(f"- {idx['nodes'][i]['id']} {idx['nodes'][i]['summary']}")
    edges = edges_between(corpus, nodes)
    for e in edges:
        lines.append(f"- {e['source']} -{e['type']}-> {e['target']}")
    return "\n".join(lines), nodes, edges


def packet_graph_1hop_semantic_arrow(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="semantic_arrow"), nodes, edges


def packet_graph_2hop_semantic_arrow(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="semantic_arrow"), nodes, edges


def packet_graph_1hop_gg_max(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="gg_max"), nodes, edges


def packet_graph_2hop_gg_max(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="gg_max"), nodes, edges


def packet_graph_1hop_gg_max_hybrid(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="gg_max_hybrid"), nodes, edges


def packet_graph_2hop_gg_max_hybrid(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="gg_max_hybrid"), nodes, edges


def packet_graph_1hop_gg_lex(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="gg_lex"), nodes, edges


def packet_graph_2hop_gg_lex(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="gg_lex"), nodes, edges


def packet_graph_1hop_gg_lex_hybrid(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=1)
    return render_packet(idx, nodes, edges, mode="gg_lex_hybrid"), nodes, edges


def packet_graph_2hop_gg_lex_hybrid(corpus: dict, idx: dict, task: dict) -> tuple[str, set[str], list[dict]]:
    starts = score_nodes_bm25(idx, task["question"], limit=3) or score_nodes(idx, task["question"], limit=3)
    nodes, edges = expand(idx, starts, hops=2)
    return render_packet(idx, nodes, edges, mode="gg_lex_hybrid"), nodes, edges


STRATEGIES: dict[str, Callable[[dict, dict, dict], tuple[str, set[str], list[dict]]]] = {
    "full_markdown": packet_full_markdown,
    "keyword_markdown": packet_keyword,
    "bm25_markdown": packet_bm25,
    "graph_1hop": packet_graph_1hop,
    "graph_1hop_lowlevel": packet_graph_1hop_lowlevel,
    "graph_1hop_sql": packet_graph_1hop_sql,
    "graph_1hop_semantic_arrow": packet_graph_1hop_semantic_arrow,
    "graph_1hop_gg_max": packet_graph_1hop_gg_max,
    "graph_1hop_gg_max_hybrid": packet_graph_1hop_gg_max_hybrid,
    "graph_1hop_gg_lex": packet_graph_1hop_gg_lex,
    "graph_1hop_gg_lex_hybrid": packet_graph_1hop_gg_lex_hybrid,
    "graph_2hop": packet_graph_2hop,
    "graph_2hop_lowlevel": packet_graph_2hop_lowlevel,
    "graph_2hop_sql": packet_graph_2hop_sql,
    "graph_2hop_semantic_arrow": packet_graph_2hop_semantic_arrow,
    "graph_2hop_gg_max": packet_graph_2hop_gg_max,
    "graph_2hop_gg_max_hybrid": packet_graph_2hop_gg_max_hybrid,
    "graph_2hop_gg_lex": packet_graph_2hop_gg_lex,
    "graph_2hop_gg_lex_hybrid": packet_graph_2hop_gg_lex_hybrid,
    "graph_keyword_hybrid": packet_hybrid,
    "hierarchical_summary": packet_hierarchical,
}


def edges_between(corpus: dict, nodes: set[str]) -> list[dict]:
    return [e for e in corpus["edges"] if e["source"] in nodes and e["target"] in nodes]


def render_packet(idx: dict, nodes: set[str], edges: list[dict], mode: str) -> str:
    if mode == "lowlevel":
        relation_ids = {rel: i + 1 for i, rel in enumerate(RELATIONS)}
        lines = ["<g>", "<r>"]
        for rel, rel_id in relation_ids.items():
            lines.append(f"{rel_id}:{rel}")
        lines.append("</r>")
        lines.append("<n>")
        for node_id in sorted(nodes):
            n = idx["nodes"][node_id]
            lines.append(f"{node_id}:{n['label']}")
        lines.append("</n>")
        lines.append("<a>")
        for e in edges:
            lines.append(f"{e['source']},{e['target']},{relation_ids[e['type']]},{e['weight']}")
        lines.extend(["</a>", "</g>"])
        return "\n".join(lines)

    if mode == "sql":
        node_rows = []
        for node_id in sorted(nodes):
            n = idx["nodes"][node_id]
            node_rows.append(f"{node_id},{n['label']},{n['kind']},{n['path']}")
        edge_rows = [f"{e['source']},{e['target']},{e['type']},{e['weight']}" for e in edges]
        return (
            "TABLE nodes: id,label,kind,path | "
            + " | ".join(node_rows)
            + "\nTABLE edges: source,target,type,weight | "
            + " | ".join(edge_rows)
        )

    if mode == "compact":
        lines = ["# Compact Graph Packet", "N:"]
        for node_id in sorted(nodes):
            n = idx["nodes"][node_id]
            lines.append(f"{node_id}|{n['label']}|{n['kind']}|{n['path']}")
        lines.append("E:")
        for e in edges:
            lines.append(f"{e['source']}|{e['type']}|{e['target']}|{e['weight']}")
        return "\n".join(lines)

    if mode == "semantic_arrow":
        lines = ["@nodes"]
        for node_id in sorted(nodes):
            n = idx["nodes"][node_id]
            lines.append(f"{node_id}: {n['label']}")
        lines.append("")
        lines.append("@edges")
        for e in edges:
            lines.append(f"{e['source']} -{e['type']}-> {e['target']} ({e['weight']})")
        return "\n".join(lines)

    if mode in {"gg_max", "gg_max_hybrid", "gg_lex", "gg_lex_hybrid"}:
        relation_ids = {rel: i + 1 for i, rel in enumerate(RELATIONS)}
        lines = ["[r]"]
        for rel, rel_id in relation_ids.items():
            lines.append(f"{rel_id}:{rel}")
        lines.append("[n]")
        
        is_lex = "gg_lex" in mode
        if is_lex:
            seen = set()
            node_to_idx = {}
            for node_id in sorted(nodes):
                n = idx["nodes"][node_id]
                label = n["label"]
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
                node_to_idx[node_id] = candidate
        else:
            node_to_idx = {node_id: str(i + 1) for i, node_id in enumerate(sorted(nodes))}

        for node_id, idx_str in node_to_idx.items():
            n = idx["nodes"][node_id]
            if "hybrid" in mode:
                lines.append(f"{idx_str} {n['label']} [{n['kind']}] {n['path']} summary: {n['summary']}")
                for fact in n["facts"][:2]:
                    lines.append(f"  - {fact}")
            else:
                lines.append(f"{idx_str} {n['label']}")
        lines.append("[e]")
        for e in edges:
            rel_id = relation_ids[e["type"]]
            src_idx = node_to_idx[e["source"]]
            tgt_idx = node_to_idx[e["target"]]
            w = float(e["weight"])
            if abs(w - 1.0) > 1e-9:
                lines.append(f"{src_idx} {tgt_idx} {rel_id} {e['weight']}")
            else:
                lines.append(f"{src_idx} {tgt_idx} {rel_id}")
        return "\n".join(lines)

    lines = ["# Context Packet", "", "Nodes:"]
    for node_id in sorted(nodes):
        n = idx["nodes"][node_id]
        lines.append(f"- {node_id} {n['label']} [{n['kind']}] {n['path']}: {n['summary']}")
        if mode in {"markdown_full", "hybrid"}:
            for fact in n["facts"][:2]:
                lines.append(f"  - {fact}")
    lines.append("")
    lines.append("Edges:")
    for e in edges:
        lines.append(f"- {e['source']} -{e['type']}-> {e['target']} ({e['weight']})")
    return "\n".join(lines)


def score_packet(task: dict, packet_nodes: set[str], packet_edges: list[dict], total_nodes: int) -> dict:
    expected_nodes = set(task["expected_nodes"])
    expected_edges = {tuple(e) for e in task["expected_edges"]}
    packet_edge_keys = {(e["source"], e["target"], e["type"]) for e in packet_edges}

    node_recall = len(expected_nodes & packet_nodes) / max(1, len(expected_nodes))
    edge_recall = len(expected_edges & packet_edge_keys) / max(1, len(expected_edges)) if expected_edges else 1.0
    path_recall = 1.0
    if task["expected_path"]:
        path_recall = len(set(task["expected_path"]) & packet_nodes) / len(task["expected_path"])
    irrelevant = len(packet_nodes - expected_nodes) / max(1, len(packet_nodes))
    negative_ok = 1.0
    negative_direct_edge_count = 0
    if task.get("negative"):
        negative_direct_edge_count = count_edges_between(packet_edge_keys, expected_nodes)
        negative_ok = 1.0 if negative_direct_edge_count == 0 else 0.0
    return {
        "node_recall": node_recall,
        "edge_recall": edge_recall,
        "path_recall": path_recall,
        "irrelevant_context_ratio": irrelevant,
        "negative_ok": negative_ok,
        "negative_direct_edge_count": negative_direct_edge_count,
        "retrieved_nodes": len(packet_nodes),
        "retrieved_edges": len(packet_edges),
        "corpus_coverage": len(packet_nodes) / max(1, total_nodes),
    }


def count_edges_between(edges: set[tuple[str, str, str]], nodes: set[str]) -> int:
    if len(nodes) < 2:
        return len([edge for edge in edges if edge[0] in nodes or edge[1] in nodes])
    return sum(1 for source, target, _kind in edges if source in nodes and target in nodes)


def storage_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def simulate_incremental_update(corpus: dict) -> float:
    start = time.perf_counter()
    nodes = list(corpus["nodes"])
    edges = list(corpus["edges"])
    next_num = len(nodes) + 1
    new_node = {
        "id": nid(next_num),
        "label": node_label(next_num),
        "kind": "component",
        "path": f"components/{node_label(next_num)}.md",
        "summary": f"{node_label(next_num)} is an incrementally added component.",
        "facts": [f"{node_label(next_num)} was added during update simulation."],
    }
    nodes.append(new_node)
    edges.append({"source": nid(max(1, next_num - 1)), "target": new_node["id"], "type": "uses", "weight": 0.72})
    _ = build_indexes({"name": corpus["name"], "nodes": nodes, "edges": edges})
    return (time.perf_counter() - start) * 1000


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_protocol() -> list[dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seed = int(manifest["seed"])
    tokenizer_name, count_tokens = get_token_counter()
    rows = []
    if OUT.exists():
        shutil.rmtree(OUT)
    PACKETS.mkdir(parents=True, exist_ok=True)

    prompt_log = PROMPTS_JSONL.open("w", encoding="utf-8")
    for c in manifest["corpora"]:
        cfg = CorpusConfig(**c)
        if not cfg.enabled:
            continue
        corpus_dir = OUT / "corpora" / cfg.name
        md_dir = corpus_dir / "md"
        corpus_dir.mkdir(parents=True, exist_ok=True)

        build_start = time.perf_counter()
        corpus = make_corpus(cfg, seed)
        idx = build_indexes(corpus)
        tasks = make_tasks(corpus)
        build_ms = (time.perf_counter() - build_start) * 1000

        write_json(corpus_dir / "graph.json", corpus)
        write_json(corpus_dir / "tasks_answer_key.json", tasks)
        render_start = time.perf_counter()
        render_markdown_docs(corpus, md_dir)
        render_sqlite(corpus, corpus_dir / "context_graph.db")
        render_ms = (time.perf_counter() - render_start) * 1000
        update_ms = simulate_incremental_update(corpus)
        graph_bytes = storage_size(corpus_dir / "graph.json")
        md_bytes = storage_size(md_dir)
        db_bytes = storage_size(corpus_dir / "context_graph.db")

        for task in tasks:
            for strategy_name in manifest["strategies"]:
                strategy = STRATEGIES[strategy_name]
                start = time.perf_counter()
                packet, packet_nodes, packet_edges = strategy(corpus, idx, task)
                latency_ms = (time.perf_counter() - start) * 1000
                metrics = score_packet(task, packet_nodes, packet_edges, len(corpus["nodes"]))
                tokens = count_tokens(packet)
                packet_path = PACKETS / cfg.name / task["class"] / f"{strategy_name}.txt"
                packet_path.parent.mkdir(parents=True, exist_ok=True)
                packet_path.write_text(packet, encoding="utf-8")
                prompt_log.write(json.dumps({
                    "corpus": cfg.name,
                    "task": task["class"],
                    "strategy": strategy_name,
                    "question": task["question"],
                    "packet_path": str(packet_path.relative_to(ROOT)).replace("\\", "/"),
                    "prompt": f"Answer using only this packet.\n\nQuestion: {task['question']}\n\n{packet}",
                }, ensure_ascii=False) + "\n")

                rel_items = max(1, len(task["expected_nodes"]) + len(task["expected_edges"]))
                rows.append({
                    "corpus": cfg.name,
                    "query_class": task["class"],
                    "strategy": strategy_name,
                    "tokenizer": tokenizer_name,
                    "nodes": len(corpus["nodes"]),
                    "edges": len(corpus["edges"]),
                    "tokens": tokens,
                    "latency_ms": round(latency_ms, 3),
                    "build_ms": round(build_ms, 3),
                    "render_ms": round(render_ms, 3),
                    "update_ms": round(update_ms, 3),
                    "graph_json_bytes": graph_bytes,
                    "markdown_bytes": md_bytes,
                    "sqlite_bytes": db_bytes,
                    "tokens_per_relevant_item": round(tokens / rel_items, 3),
                    **{k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
                })
    prompt_log.close()
    return rows


def write_results(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    thresholds = manifest["thresholds"]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_query: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["corpus"], row["strategy"])].append(row)
        by_query[(row["query_class"], row["strategy"])].append(row)

    lines = ["# Protocol Benchmark Summary", "", f"Tokenizer: `{rows[0]['tokenizer']}`", ""]
    lines.append("| Corpus | Strategy | Avg tokens | Node recall | Edge recall | Path recall | Irrelevant ratio | Latency ms |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for (corpus, strategy), items in sorted(grouped.items()):
        avg = lambda key: sum(float(i[key]) for i in items) / len(items)
        lines.append(
            f"| {corpus} | {strategy} | {avg('tokens'):.1f} | {avg('node_recall'):.3f} | "
            f"{avg('edge_recall'):.3f} | {avg('path_recall'):.3f} | "
            f"{avg('irrelevant_context_ratio'):.3f} | {avg('latency_ms'):.3f} |"
        )
    lines.append("")
    lines.append("## Query Class Breakdown")
    lines.append("")
    lines.append("| Query class | Strategy | Avg tokens | Node recall | Edge recall | Path recall | Irrelevant ratio |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for (query_class, strategy), items in sorted(by_query.items()):
        avg = lambda key: sum(float(i[key]) for i in items) / len(items)
        lines.append(
            f"| {query_class} | {strategy} | {avg('tokens'):.1f} | {avg('node_recall'):.3f} | "
            f"{avg('edge_recall'):.3f} | {avg('path_recall'):.3f} | {avg('irrelevant_context_ratio'):.3f} |"
        )
    lines.append("")
    lines.append("## Threshold Check")
    lines.append("")
    lines.append("| Corpus | Strategy | Status | Reason |")
    lines.append("| --- | --- | --- | --- |")
    for (corpus, strategy), items in sorted(grouped.items()):
        avg = lambda key: sum(float(i[key]) for i in items) / len(items)
        failures = []
        if avg("node_recall") < thresholds["min_node_recall"]:
            failures.append(f"node_recall {avg('node_recall'):.3f} < {thresholds['min_node_recall']}")
        if avg("edge_recall") < thresholds["min_edge_recall"]:
            failures.append(f"edge_recall {avg('edge_recall'):.3f} < {thresholds['min_edge_recall']}")
        if avg("irrelevant_context_ratio") > thresholds["max_irrelevant_context_ratio"]:
            failures.append(f"irrelevant {avg('irrelevant_context_ratio'):.3f} > {thresholds['max_irrelevant_context_ratio']}")
        status = "PASS" if not failures else "FAIL"
        reason = "; ".join(failures) if failures else "meets configured thresholds"
        lines.append(f"| {corpus} | {strategy} | {status} | {reason} |")
    lines.append("")
    lines.append("Artifacts:")
    lines.append(f"- CSV: `{RESULTS_CSV.relative_to(ROOT)}`")
    lines.append(f"- Saved context packets: `{PACKETS.relative_to(ROOT)}`")
    lines.append(f"- Saved prompts: `{PROMPTS_JSONL.relative_to(ROOT)}`")
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run_protocol()
    write_results(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
