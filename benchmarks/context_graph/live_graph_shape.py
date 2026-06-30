from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.io import save_graph  # noqa: E402
from graphgraph.ontology import is_weak_relation  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import profile_graph_shape, recommend_node_budget  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402
from graphgraph.services import render_query_context  # noqa: E402
from graphgraph.validate import validate_packet  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out" / "live"
GRAPH_PATH = OUT / "live_graph_shape.graph.json"
REPORT_JSON = OUT / "live_graph_shape.json"
REPORT_MD = OUT / "live_graph_shape.md"

DEFAULT_SKIP_DIRS = (
    ".code-review-graph",
    ".git",
    ".graphgraph",
    ".pytest_cache",
    "__pycache__",
    "benchmarks/context_graph/out",
    "graphify-out",
    "tmp",
)

DEFAULT_QUERIES = (
    ("planner packet selection edge threshold", "direct_lookup"),
    ("scanner imports relative package", "blast_radius"),
    ("doc code pairing benchmark coverage gaps", "subsystem_summary"),
    ("model reasoning benchmark live scoring", "subsystem_summary"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure live graph shape and packet validity.")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--max-nodes", type=int, default=2200)
    parser.add_argument("--frontend", default="auto", choices=["auto", "regex", "tree_sitter"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo = args.repo.resolve()
    OUT.mkdir(parents=True, exist_ok=True)

    graph = scan_directory(
        repo,
        max_nodes=args.max_nodes,
        skip_dirs=list(DEFAULT_SKIP_DIRS),
        depth="symbols",
        frontend=args.frontend,
        docs=True,
        previous_graph_path=None,
        manifest_path=None,
    )
    save_graph(graph, GRAPH_PATH)

    node_kinds = Counter(node.kind for node in graph.nodes.values())
    relations = Counter(edge.type for edge in graph.edges if edge.active)
    weak_edges = sum(1 for edge in graph.edges if edge.active and is_weak_relation(edge.type))
    source_files = sum(1 for node in graph.nodes.values() if node.kind in {"python", "typescript", "javascript", "rust", "go", "java", "c", "cpp", "header"})
    doc_nodes = sum(1 for node in graph.nodes.values() if node.kind in {"markdown", "rst", "text", "section", "concept"})
    symbol_nodes = sum(1 for node in graph.nodes.values() if node.kind in {"function", "method", "class", "struct", "enum", "trait", "theorem"})
    import_edges = relations.get("imports", 0)
    shape = profile_graph_shape(graph)
    budget_candidates = [
        recommend_node_budget(query_class, "", shape).__dict__
        for query_class in (
            "direct_lookup",
            "reverse_lookup",
            "multi_hop_path",
            "blast_radius",
            "subsystem_summary",
            "negative_query",
        )
    ]

    queries = []
    for query, query_class in DEFAULT_QUERIES:
        packet_text = render_query_context(
            query=query,
            query_class=query_class,
            graph_path=GRAPH_PATH,
            show_anchors=True,
            json_anchors=True,
            cache_namespace="live_shape",
        )
        data = json.loads(packet_text)
        packet = data.get("packet", "")
        validation = validate_packet(packet) if packet else None
        queries.append(
            {
                "query": query,
                "query_class": query_class,
                "anchors": len(data.get("anchors", [])),
                "format": validation.format if validation else "",
                "valid": bool(validation and validation.ok),
                "nodes": validation.node_count if validation else 0,
                "edges": validation.edge_count if validation else 0,
                "packet_chars": len(packet),
            }
        )

    negative_packet = render_packet(graph, {next(iter(graph.nodes))} if graph.nodes else set(), [], "semantic_arrow")
    negative_validation = validate_packet(negative_packet)

    report = {
        "repo": str(repo),
        "graph_path": str(GRAPH_PATH),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "source_files": source_files,
        "symbol_nodes": symbol_nodes,
        "doc_nodes": doc_nodes,
        "import_edges": import_edges,
        "imports_per_source_file": round(import_edges / max(1, source_files), 4),
        "weak_edge_ratio": round(weak_edges / max(1, len(graph.edges)), 4),
        "doc_node_ratio": round(doc_nodes / max(1, len(graph.nodes)), 4),
        "top_node_kinds": node_kinds.most_common(12),
        "top_relations": relations.most_common(12),
        "budget_candidates": budget_candidates,
        "queries": queries,
        "negative_gate": {
            "format": negative_validation.format,
            "valid": negative_validation.ok,
            "nodes": negative_validation.node_count,
            "edges": negative_validation.edge_count,
        },
    }

    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Live Graph Shape",
        "",
        f"- Repo: `{report['repo']}`",
        f"- Graph: `{report['graph_path']}`",
        f"- Nodes: `{report['nodes']}`",
        f"- Edges: `{report['edges']}`",
        f"- Source file nodes: `{report['source_files']}`",
        f"- Symbol nodes: `{report['symbol_nodes']}`",
        f"- Doc-like nodes: `{report['doc_nodes']}`",
        f"- Import edges: `{report['import_edges']}`",
        f"- Imports/source file: `{report['imports_per_source_file']}`",
        f"- Weak edge ratio: `{report['weak_edge_ratio']}`",
        f"- Doc node ratio: `{report['doc_node_ratio']}`",
        "",
        "## Top Node Kinds",
        "",
    ]
    for kind, count in report["top_node_kinds"]:  # type: ignore[index]
        lines.append(f"- `{kind}`: {count}")
    lines.extend(["", "## Top Relations", ""])
    for relation, count in report["top_relations"]:  # type: ignore[index]
        lines.append(f"- `{relation}`: {count}")
    lines.extend([
        "",
        "## Dynamic Budget Candidates",
        "",
        "| Class | Base | Candidate | Mode | Reason |",
        "| --- | ---: | ---: | --- | --- |",
    ])
    for row in report["budget_candidates"]:  # type: ignore[index]
        lines.append(
            f"| `{row['query_class']}` | {row['base_budget']} | {row['recommended_budget']} | "
            f"`{row['mode']}` | {row['reason']} |"
        )
    lines.extend([
        "",
        "## Query Packet Validation",
        "",
        "| Query | Class | Anchors | Format | Valid | Nodes | Edges |",
        "| --- | --- | ---: | --- | --- | ---: | ---: |",
    ])
    for row in report["queries"]:  # type: ignore[index]
        lines.append(
            f"| {row['query']} | `{row['query_class']}` | {row['anchors']} | `{row['format']}` | "
            f"`{row['valid']}` | {row['nodes']} | {row['edges']} |"
        )
    gate = report["negative_gate"]  # type: ignore[index]
    lines.extend([
        "",
        "## Gate Check",
        "",
        f"- Zero-edge packet format: `{gate['format']}`",
        f"- Zero-edge packet valid: `{gate['valid']}`",
        f"- Zero-edge packet edges: `{gate['edges']}`",
        "",
        "## Read",
        "",
        "- Low import/source ratios indicate scanner under-extraction or a docs-heavy scan.",
        "- High weak-edge/doc ratios indicate potential retrieval noise pressure.",
        "- This is a live-code shape probe, not a saved-corpus answerability proof.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
