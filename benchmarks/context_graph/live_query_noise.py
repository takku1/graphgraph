from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from graphgraph.analysis.eval import estimate_tokens
from graphgraph.io import find_graph_path, load_any
from graphgraph.packets import render_packet
from graphgraph.planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph
from graphgraph.retrieval import retrieve_context

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "live_query_noise"
REPORT_JSON = OUT / "live_query_noise.json"
REPORT_MD = OUT / "live_query_noise.md"

QUERIES = [
    ("native_context_status", "graphgraph current status native context command retrieval smoke tests codex skill", "subsystem_summary"),
    ("retrieval_noise", "subsystem summary retrieval concept doc weak edge noise pruning", "subsystem_summary"),
    ("install_interop", "install codex graphify code-review graph ingest no touch external graph tools", "subsystem_summary"),
    ("doc_usage", "README installation usage graphgraph context", "doc_summary"),
]

DOC_KINDS = {"concept", "section", "markdown", "rst", "html", "text"}
IMPLEMENTATION_EDGE_TYPES = {"calls", "imports", "imports_from", "reads", "writes", "uses", "implements", "returns", "defines", "data_flow", "control_flow"}
GENERATED_PREFIXES = ("graphify-out", ".code-review-graph", "evidence", "artifacts", "scratch")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    graph_path = find_graph_path(ROOT)
    graph = load_any(graph_path)
    rows = []
    for name, query, query_class in QUERIES:
        plan = plan_context(query_class, query)
        result = retrieve_context(graph, query, query_class, hops=plan.hops)
        if result.starts:
            plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, result.nodes, result.edges))
            packet = render_packet(graph, result.nodes, result.edges, plan.packet)
        else:
            packet = ""
        rows.append(measure(name, query, query_class, plan.packet, result.nodes, result.edges, packet, graph))

    payload = {"graph": str(graph_path), "rows": rows}
    REPORT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(payload), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def measure(name: str, query: str, query_class: str, packet: str, nodes: set[str], edges: list[Any], packet_text: str, graph: Any) -> dict[str, Any]:
    kinds = Counter(graph.nodes[nid].kind for nid in nodes if nid in graph.nodes)
    paths = [graph.nodes[nid].path for nid in nodes if nid in graph.nodes and graph.nodes[nid].path]
    generated_paths = [path for path in paths if path.startswith(GENERATED_PREFIXES)]
    doc_nodes = sum(count for kind, count in kinds.items() if kind in DOC_KINDS)
    concept_nodes = kinds.get("concept", 0)
    weak_edges = sum(1 for edge in edges if edge.type in {"mentions", "discusses", "section_of", "references", "links"})
    implementation_edges = sum(1 for edge in edges if edge.type in IMPLEMENTATION_EDGE_TYPES)
    return {
        "name": name,
        "query": query,
        "query_class": query_class,
        "packet": packet,
        "nodes": len(nodes),
        "edges": len(edges),
        "doc_nodes": doc_nodes,
        "concept_nodes": concept_nodes,
        "doc_node_ratio": round(doc_nodes / max(1, len(nodes)), 3),
        "concept_node_ratio": round(concept_nodes / max(1, len(nodes)), 3),
        "weak_edges": weak_edges,
        "weak_edge_ratio": round(weak_edges / max(1, len(edges)), 3),
        "implementation_edges": implementation_edges,
        "implementation_edge_ratio": round(implementation_edges / max(1, len(edges)), 3),
        "generated_path_count": len(generated_paths),
        "token_estimate": estimate_tokens(packet_text),
        "top_kinds": kinds.most_common(8),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Live Query Noise",
        "",
        f"Graph: `{payload['graph']}`",
        "",
        "| Query | Class | Packet | Nodes | Edges | Doc nodes | Concepts | Doc ratio | Impl edges | Weak edges | Generated paths | Tokens |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        lines.append(
            "| {name} | `{query_class}` | `{packet}` | {nodes} | {edges} | {doc_nodes} | {concept_nodes} | {doc_node_ratio:.3f} | {implementation_edges} | {weak_edges} | {generated_path_count} | {token_estimate} |".format(**row)
        )
    lines.extend([
        "",
        "## Read",
        "",
        "- `generated_path_count` should stay at `0` for normal runtime queries.",
        "- Broad `subsystem_summary` packets should keep doc/concept ratios bounded; doc-heavy queries are allowed to use `doc_summary`.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
