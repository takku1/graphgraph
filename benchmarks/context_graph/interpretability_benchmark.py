from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from protocol_benchmark import (
    MANIFEST,
    OUT,
    CorpusConfig,
    build_indexes,
    expand,
    get_token_counter,
    make_corpus,
    make_tasks,
    render_packet,
    score_nodes,
    score_nodes_bm25,
    score_packet,
)


RESULTS_CSV = OUT / "interpretability_results.csv"
RESULTS_MD = OUT / "interpretability_summary.md"
PACKET_DIR = OUT / "interpretability_packets"

SCHEMAS = {
    "lowlevel_bare": "",
    "lowlevel_schema": (
        "Decode GG-LL. <r> maps relation_id:relation. <n> maps node_id:label. "
        "<a> rows are source,target,relation_id,weight. Answer using node labels and relation labels."
    ),
    "lowlevel_verbose_schema": (
        "You are given a compact project graph packet. The <r> block defines relation IDs. "
        "The <n> block defines node IDs and names. The <a> block is an adjacency list where "
        "each row has source node id, target node id, relation id, and weight. Use the relation "
        "map to translate edge rows into readable dependencies. Do not invent nodes or edges."
    ),
    "sql_schema": (
        "Read the SQL-style rows. The nodes table is id,label,kind,path. "
        "The edges table is source,target,type,weight."
    ),
    "compact_schema": (
        "Read the compact graph packet. N rows are id|label|kind|path. "
        "E rows are source|type|target|weight."
    ),
    "hybrid_schema": "Use the relationship list and grounding snippets. Do not invent nodes or edges.",
    "semantic_arrow_schema": (
        "Read the semantic arrow graph packet. @nodes maps node_id: label. "
        "@edges rows show dependencies in source -relation-> target (weight) format."
    ),
    "gg_max_schema": (
        "Decode GG-MAX. [r] maps relation_id:relation. [n] maps node_idx node_label. "
        "[e] rows are source_idx target_idx relation_id weight. Answer using node labels and relation labels."
    ),
    "gg_lex_schema": (
        "Decode GG-LEX. [r] maps relation_id:relation. [n] maps unique 8-character lexical tag node_label. "
        "[e] rows are source_tag target_tag relation_id. Answer using node labels and relation labels."
    ),
    "gg_lex_hybrid_schema": "Use the lexical relationship list and grounding snippets. Do not invent nodes or edges.",
}


def starts_for(idx: dict, question: str) -> list[str]:
    return score_nodes_bm25(idx, question, limit=3) or score_nodes(idx, question, limit=3)


def render_variant(idx: dict, nodes: set[str], edges: list[dict], variant: str) -> str:
    if variant.startswith("lowlevel"):
        return render_packet(idx, nodes, edges, mode="lowlevel")
    if variant == "sql_schema":
        return render_packet(idx, nodes, edges, mode="sql")
    if variant == "compact_schema":
        return render_packet(idx, nodes, edges, mode="compact")
    if variant == "hybrid_schema":
        return render_packet(idx, nodes, edges, mode="hybrid")
    if variant == "semantic_arrow_schema":
        return render_packet(idx, nodes, edges, mode="semantic_arrow")
    if variant == "gg_max_schema":
        return render_packet(idx, nodes, edges, mode="gg_max")
    if variant == "gg_lex_schema":
        return render_packet(idx, nodes, edges, mode="gg_lex")
    if variant == "gg_lex_hybrid_schema":
        return render_packet(idx, nodes, edges, mode="gg_lex_hybrid")
    raise ValueError(f"unknown variant {variant}")


def run() -> list[dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seed = int(manifest["seed"])
    tokenizer_name, count_tokens = get_token_counter()
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    rows = []

    for c in manifest["corpora"]:
        cfg = CorpusConfig(**c)
        if not cfg.enabled:
            continue
        corpus = make_corpus(cfg, seed)
        idx = build_indexes(corpus)
        tasks = make_tasks(corpus)
        for task in tasks:
            starts = starts_for(idx, task["question"])
            for hops in [1, 2]:
                packet_nodes, packet_edges = expand(idx, starts, hops=hops)
                metrics = score_packet(task, packet_nodes, packet_edges, len(corpus["nodes"]))
                for variant, schema in SCHEMAS.items():
                    packet = render_variant(idx, packet_nodes, packet_edges, variant)
                    question_prefix = f"Question: {task['question']}\n\n"
                    uncached_prompt = f"{schema}\n\n{question_prefix}{packet}" if schema else f"{question_prefix}{packet}"
                    cached_prompt = f"{question_prefix}{packet}"
                    packet_path = PACKET_DIR / cfg.name / task["class"] / f"{hops}hop_{variant}.txt"
                    packet_path.parent.mkdir(parents=True, exist_ok=True)
                    packet_path.write_text(uncached_prompt, encoding="utf-8")
                    rows.append(
                        {
                            "corpus": cfg.name,
                            "query_class": task["class"],
                            "hops": hops,
                            "variant": variant,
                            "tokenizer": tokenizer_name,
                            "schema_tokens": count_tokens(schema) if schema else 0,
                            "packet_tokens": count_tokens(packet),
                            "uncached_prompt_tokens": count_tokens(uncached_prompt),
                            "cached_prompt_tokens": count_tokens(cached_prompt),
                            "node_recall": metrics["node_recall"],
                            "edge_recall": metrics["edge_recall"],
                            "path_recall": metrics["path_recall"],
                            "irrelevant_context_ratio": metrics["irrelevant_context_ratio"],
                        }
                    )
    return rows


def avg(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / max(1, len(items))


def write(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["corpus"], int(row["hops"]), row["variant"])].append(row)

    lines = [
        "# Interpretability Overhead Benchmark",
        "",
        f"Tokenizer: `{rows[0]['tokenizer']}`",
        "",
        "This measures how much schema/instruction overhead each compact packet needs.",
        "",
        "| Corpus | Hops | Variant | Schema tokens | Packet tokens | Uncached prompt | Cached prompt | Node recall | Edge recall |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (corpus, hops, variant), items in sorted(grouped.items()):
        lines.append(
            f"| {corpus} | {hops} | {variant} | {avg(items, 'schema_tokens'):.1f} | "
            f"{avg(items, 'packet_tokens'):.1f} | {avg(items, 'uncached_prompt_tokens'):.1f} | "
            f"{avg(items, 'cached_prompt_tokens'):.1f} | {avg(items, 'node_recall'):.3f} | "
            f"{avg(items, 'edge_recall'):.3f} |"
        )

    lines.extend([
        "",
        "Read:",
        "",
        "- If schema tokens are cached, low-level packets stay near the token floor.",
        "- If schema tokens are not cached, SQL rows can be competitive because they carry their own semantic labels.",
        "- Live model tests should compare answer accuracy for `lowlevel_schema`, `sql_schema`, and `hybrid_schema`.",
    ])
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

