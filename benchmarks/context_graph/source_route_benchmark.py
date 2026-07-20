from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

from protocol_benchmark import (
    MANIFEST,
    OUT,
    ROOT,
    CorpusConfig,
    build_indexes,
    expand,
    get_token_counter,
    make_corpus,
    make_tasks,
    render_packet,
    render_sqlite,
    score_nodes,
    score_nodes_bm25,
    score_packet,
)

SOURCE_OUT = OUT / "source_routes"
RESULTS_CSV = SOURCE_OUT / "source_route_results.csv"
SUMMARY_MD = SOURCE_OUT / "source_route_summary.md"

PACKET_MODES = ["lowlevel", "sql", "hybrid", "semantic_arrow", "gg_max"]
HOPS = [1, 2]


def write_wiki_docs(corpus: dict, path: Path, include_edges: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for edge in corpus["edges"]:
        outgoing[edge["source"]].append(edge)

    node_by_id = {node["id"]: node for node in corpus["nodes"]}
    for node in corpus["nodes"]:
        doc = path / node["path"]
        doc.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "---",
            f"id: {node['id']}",
            f"kind: {node['kind']}",
            f"path: {node['path']}",
            "---",
            "",
            f"# {node['label']}",
            "",
            f"Summary: {node['summary']}",
            "",
            "Facts:",
            *[f"- {fact}" for fact in node["facts"]],
        ]
        if include_edges:
            lines.extend(["", "Relationships:"])
            for edge in outgoing.get(node["id"], []):
                target = node_by_id[edge["target"]]
                lines.append(f"- {edge['type']} -> [[{target['id']}|{target['label']}]] ({edge['weight']})")
        doc.write_text("\n".join(lines), encoding="utf-8")


def write_prose_docs(corpus: dict, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for edge in corpus["edges"]:
        outgoing[edge["source"]].append(edge)

    node_by_id = {node["id"]: node for node in corpus["nodes"]}
    for node in corpus["nodes"]:
        doc = path / node["path"]
        doc.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {node['label']}",
            "",
            f"Stable ID: {node['id']}",
            f"Kind: {node['kind']}",
            f"Path: {node['path']}",
            "",
            node["summary"],
            "",
            "Operational notes:",
            *[f"- {fact}" for fact in node["facts"]],
        ]
        if outgoing.get(node["id"]):
            lines.extend(["", "Dependency narrative:"])
            for edge in outgoing[node["id"]]:
                target = node_by_id[edge["target"]]
                lines.append(
                    f"- {node['label']} {edge['type']} {target['label']} "
                    f"with observed weight {edge['weight']}."
                )
        doc.write_text("\n".join(lines), encoding="utf-8")


def write_noisy_prose_docs(corpus: dict, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for edge in corpus["edges"]:
        outgoing[edge["source"]].append(edge)

    node_by_id = {node["id"]: node for node in corpus["nodes"]}
    for node in corpus["nodes"]:
        doc = path / node["path"]
        doc.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {node['label']}",
            "",
            f"Stable ID: {node['id']}",
            f"Kind: {node['kind']}",
            f"Path: {node['path']}",
            "",
            node["summary"],
            "",
            "Operational notes:",
            *[f"- {fact}" for fact in node["facts"]],
            f"- Planning note: {node['label']} was mentioned during a migration review, but this is not a dependency.",
        ]
        if outgoing.get(node["id"]):
            lines.extend(["", "Dependency narrative:"])
            for i, edge in enumerate(outgoing[node["id"]]):
                target = node_by_id[edge["target"]]
                if i % 3 == 0:
                    lines.append(
                        f"- {node['label']} {edge['type']} {target['label']} "
                        f"with observed weight {edge['weight']}."
                    )
                elif i % 3 == 1:
                    lines.append(
                        f"- {node['label']} has a {edge['type']} relationship to "
                        f"{target['label']}; weight={edge['weight']}."
                    )
                else:
                    lines.append(
                        f"- {node['label']} may need {edge['type']} access near "
                        f"{target['label']}; confidence was around {edge['weight']}."
                    )
        doc.write_text("\n".join(lines), encoding="utf-8")


def parse_wiki_docs(path: Path, name: str) -> dict:
    nodes = []
    edges = []
    for doc in sorted(path.rglob("*.md")):
        text = doc.read_text(encoding="utf-8")
        node_id = find_field(text, "id")
        kind = find_field(text, "kind")
        stored_path = find_field(text, "path") or str(doc.relative_to(path)).replace("\\", "/")
        title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        summary_match = re.search(r"^Summary:\s+(.+)$", text, flags=re.MULTILINE)
        if not node_id or not title_match:
            continue
        facts = re.findall(r"^-\s+(.+)$", text, flags=re.MULTILINE)
        relation_facts = [fact for fact in facts if " -> [[" in fact]
        facts = [fact for fact in facts if fact not in relation_facts]
        nodes.append(
            {
                "id": node_id,
                "label": title_match.group(1).strip(),
                "kind": kind or "document",
                "path": stored_path,
                "summary": summary_match.group(1).strip() if summary_match else "",
                "facts": facts,
            }
        )
        for rel, target, weight in re.findall(r"^-\s+([A-Za-z_]+)\s+->\s+\[\[(N\d+)\|[^\]]+\]\]\s+\(([0-9.]+)\)", text, flags=re.MULTILINE):
            edges.append({"source": node_id, "target": target, "type": rel, "weight": float(weight)})
    return {"name": name, "nodes": nodes, "edges": edges}


def parse_prose_docs(path: Path, name: str, include_relationship_variant: bool = False) -> dict:
    docs = sorted(path.rglob("*.md"))
    nodes = []
    raw_docs: list[tuple[str, str]] = []
    label_to_id = {}

    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        node_id = find_field(text, "Stable ID")
        kind = find_field(text, "Kind")
        stored_path = find_field(text, "Path") or str(doc.relative_to(path)).replace("\\", "/")
        title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        if not node_id or not title_match:
            continue
        label = title_match.group(1).strip()
        summary = first_summary_sentence(text)
        facts = re.findall(r"^-\s+(.+)$", text, flags=re.MULTILINE)
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "kind": kind or "document",
                "path": stored_path,
                "summary": summary,
                "facts": facts,
            }
        )
        label_to_id[label] = node_id
        raw_docs.append((node_id, text))

    labels_pattern = "|".join(re.escape(label) for label in sorted(label_to_id, key=len, reverse=True))
    relation_pattern = "calls|imports|reads|writes|uses|tests|configures"
    edge_re = re.compile(
        rf"\b(?P<src>{labels_pattern})\s+(?P<rel>{relation_pattern})\s+"
        rf"(?P<tgt>{labels_pattern})\s+with observed weight\s+(?P<weight>[0-9.]+)",
        flags=re.IGNORECASE,
    )
    relationship_re = re.compile(
        rf"\b(?P<src>{labels_pattern})\s+has a\s+(?P<rel>{relation_pattern})\s+relationship to\s+"
        rf"(?P<tgt>{labels_pattern});\s+weight=(?P<weight>[0-9.]+)",
        flags=re.IGNORECASE,
    )

    edges = []
    seen = set()
    for _, text in raw_docs:
        matches = list(edge_re.finditer(text))
        if include_relationship_variant:
            matches.extend(relationship_re.finditer(text))
        for match in matches:
            src_label = resolve_label(match.group("src"), label_to_id)
            tgt_label = resolve_label(match.group("tgt"), label_to_id)
            if not src_label or not tgt_label:
                continue
            edge = {
                "source": label_to_id[src_label],
                "target": label_to_id[tgt_label],
                "type": match.group("rel").lower(),
                "weight": float(match.group("weight").rstrip(".")),
            }
            key = (edge["source"], edge["target"], edge["type"])
            if key not in seen:
                seen.add(key)
                edges.append(edge)
    return {"name": name, "nodes": nodes, "edges": edges}


def resolve_label(value: str, label_to_id: dict[str, str]) -> str:
    folded = value.lower()
    for label in label_to_id:
        if label.lower() == folded:
            return label
    return ""


def first_summary_sentence(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-") and ":" not in line:
            return line
    return ""


def find_field(text: str, field: str) -> str:
    match = re.search(rf"^{re.escape(field)}:\s*(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_sqlite(path: Path, name: str) -> dict:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    nodes = [
        {
            "id": row["id"],
            "label": row["label"],
            "kind": row["kind"],
            "path": row["path"],
            "summary": row["summary"],
            "facts": row["facts"].splitlines() if row["facts"] else [],
        }
        for row in con.execute("select id, label, kind, path, summary, facts from nodes")
    ]
    edges = [
        {"source": row["source"], "target": row["target"], "type": row["type"], "weight": row["weight"]}
        for row in con.execute("select source, target, type, weight from edges")
    ]
    con.close()
    return {"name": name, "nodes": nodes, "edges": edges}


def edge_keys(corpus: dict) -> set[tuple[str, str, str]]:
    return {(edge["source"], edge["target"], edge["type"]) for edge in corpus["edges"]}


def node_ids(corpus: dict) -> set[str]:
    return {node["id"] for node in corpus["nodes"]}


def extraction_metrics(original: dict, parsed: dict) -> dict:
    original_nodes = node_ids(original)
    parsed_nodes = node_ids(parsed)
    original_edges = edge_keys(original)
    parsed_edges = edge_keys(parsed)
    matched_edges = original_edges & parsed_edges
    return {
        "extract_node_recall": len(original_nodes & parsed_nodes) / max(1, len(original_nodes)),
        "extract_edge_recall": len(matched_edges) / max(1, len(original_edges)),
        "extract_edge_precision": len(matched_edges) / max(1, len(parsed_edges)),
        "extract_extra_edges": len(parsed_edges - original_edges),
    }


def starts_for(idx: dict, question: str) -> list[str]:
    return score_nodes_bm25(idx, question, limit=3) or score_nodes(idx, question, limit=3)


def run() -> list[dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seed = int(manifest["seed"])
    tokenizer_name, count_tokens = get_token_counter()

    if SOURCE_OUT.exists():
        shutil.rmtree(SOURCE_OUT)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    for raw_cfg in manifest["corpora"]:
        cfg = CorpusConfig(**raw_cfg)
        if not cfg.enabled:
            continue
        original = make_corpus(cfg, seed)
        route_dir = SOURCE_OUT / cfg.name
        wiki_edge_dir = route_dir / "wiki_with_edges"
        wiki_plain_dir = route_dir / "wiki_plain"
        wiki_prose_dir = route_dir / "wiki_prose_relations"
        wiki_noisy_prose_dir = route_dir / "wiki_noisy_prose"
        sqlite_path = route_dir / "context_graph.db"
        write_wiki_docs(original, wiki_edge_dir, include_edges=True)
        write_wiki_docs(original, wiki_plain_dir, include_edges=False)
        write_prose_docs(original, wiki_prose_dir)
        write_noisy_prose_docs(original, wiki_noisy_prose_dir)
        render_sqlite(original, sqlite_path)

        routes = {
            "code_graph_direct": original,
            "wiki_with_edges": parse_wiki_docs(wiki_edge_dir, "wiki_with_edges"),
            "wiki_prose_relations": parse_prose_docs(wiki_prose_dir, "wiki_prose_relations"),
            "wiki_noisy_prose": parse_prose_docs(wiki_noisy_prose_dir, "wiki_noisy_prose", include_relationship_variant=True),
            "wiki_plain_no_edges": parse_wiki_docs(wiki_plain_dir, "wiki_plain_no_edges"),
            "sqlite_rows": parse_sqlite(sqlite_path, "sqlite_rows"),
        }
        tasks = make_tasks(original)
        for route_name, route_corpus in routes.items():
            idx = build_indexes(route_corpus)
            extract = extraction_metrics(original, route_corpus)
            for task in tasks:
                starts = starts_for(idx, task["question"])
                for hops in HOPS:
                    packet_nodes, packet_edges = expand(idx, starts, hops=hops)
                    metrics = score_packet(task, packet_nodes, packet_edges, len(route_corpus["nodes"]))
                    for mode in PACKET_MODES:
                        packet = render_packet(idx, packet_nodes, packet_edges, mode=mode)
                        rows.append(
                            {
                                "corpus": cfg.name,
                                "source_route": route_name,
                                "query_class": task["class"],
                                "hops": hops,
                                "packet_mode": mode,
                                "tokenizer": tokenizer_name,
                                "tokens": count_tokens(packet),
                                "nodes": len(route_corpus["nodes"]),
                                "edges": len(route_corpus["edges"]),
                                **{k: round(v, 4) if isinstance(v, float) else v for k, v in extract.items()},
                                **{k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
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

    grouped: dict[tuple[str, str, int, str], list[dict]] = defaultdict(list)
    route_extract: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["corpus"], row["source_route"], int(row["hops"]), row["packet_mode"])].append(row)
        route_extract[(row["corpus"], row["source_route"])].append(row)

    lines = [
        "# Source Route Benchmark",
        "",
        f"Tokenizer: `{rows[0]['tokenizer']}`",
        "",
        "This compares source routes that compile into the same node/edge/document IR before packet rendering.",
        "",
        "## Extraction Coverage",
        "",
        "| Corpus | Source route | Nodes | Edges | Node recall | Edge recall | Edge precision | Extra edges |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (corpus, route), items in sorted(route_extract.items()):
        sample = items[0]
        lines.append(
            f"| {corpus} | {route} | {sample['nodes']} | {sample['edges']} | "
            f"{sample['extract_node_recall']:.3f} | {sample['extract_edge_recall']:.3f} | "
            f"{sample['extract_edge_precision']:.3f} | {sample['extract_extra_edges']} |"
        )

    lines.extend(
        [
            "",
            "## Packet Results",
            "",
            "| Corpus | Source route | Hops | Packet | Avg tokens | Node recall | Edge recall | Path recall | Irrelevant ratio |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for (corpus, route, hops, mode), items in sorted(grouped.items()):
        lines.append(
            f"| {corpus} | {route} | {hops} | {mode} | {avg(items, 'tokens'):.1f} | "
            f"{avg(items, 'node_recall'):.3f} | {avg(items, 'edge_recall'):.3f} | "
            f"{avg(items, 'path_recall'):.3f} | {avg(items, 'irrelevant_context_ratio'):.3f} |"
        )

    lines.extend(
        [
            "",
            "Read:",
            "",
            "- `wiki_plain_no_edges` is the control for prose-only docs. It should recover nodes but not structural edge evidence.",
            "- `wiki_prose_relations` is the harder document-native route: edges are embedded in normal sentences and recovered by a deterministic parser.",
            "- `wiki_noisy_prose` mixes supported relation sentences, unsupported relation phrasing, and irrelevant notes to measure parser robustness.",
            "- `wiki_with_edges`, `sqlite_rows`, and `code_graph_direct` should match on extraction if the parsers are lossless.",
            "- Packet differences after extraction are caused by the encoder, not the source route.",
            "",
            f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
