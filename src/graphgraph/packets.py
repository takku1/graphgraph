from __future__ import annotations

from .core import Edge, Graph


DEFAULT_RELATIONS = ("calls", "imports", "reads", "writes", "uses", "tests", "configures")


def render_lowlevel(graph: Graph, nodes: set[str], edges: list[Edge], relations: tuple[str, ...] = DEFAULT_RELATIONS) -> str:
    relation_ids = {rel: i + 1 for i, rel in enumerate(relations)}
    lines = ["<g>", "<r>"]
    for rel, rel_id in relation_ids.items():
        lines.append(f"{rel_id}:{rel}")
    lines.append("</r>")
    lines.append("<n>")
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        lines.append(f"{node_id}:{node.label}")
    lines.append("</n>")
    lines.append("<a>")
    for edge in edges:
        rel_id = relation_ids.get(edge.type, edge.type)
        lines.append(f"{edge.source},{edge.target},{rel_id},{edge.weight:g}")
    lines.extend(["</a>", "</g>"])
    return "\n".join(lines)


def render_sql(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    node_rows = []
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        node_rows.append(f"{node.id},{node.label},{node.kind},{node.path}")
    edge_rows = [f"{edge.source},{edge.target},{edge.type},{edge.weight:g}" for edge in edges]
    return (
        "TABLE nodes: id,label,kind,path | "
        + " | ".join(node_rows)
        + "\nTABLE edges: source,target,type,weight | "
        + " | ".join(edge_rows)
    )


def render_hybrid(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    lines = ["# Context Packet", "", "Nodes:"]
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        lines.append(f"- {node.id} {node.label} [{node.kind}] {node.path}: {node.summary}")
        for fact in node.facts[:2]:
            lines.append(f"  - {fact}")
    lines.extend(["", "Edges:"])
    for edge in edges:
        lines.append(f"- {edge.source} -{edge.type}-> {edge.target} ({edge.weight:g})")
    return "\n".join(lines)


def render_semantic_arrow(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    lines = ["@nodes"]
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        lines.append(f"{node_id}: {node.label}")
    lines.append("")
    lines.append("@edges")
    for edge in edges:
        lines.append(f"{edge.source} -{edge.type}-> {edge.target} ({edge.weight:g})")
    return "\n".join(lines)


def render_gg_max(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    relations: tuple[str, ...] = DEFAULT_RELATIONS,
    hybrid: bool = False,
) -> str:
    relation_ids = {rel: i + 1 for i, rel in enumerate(relations)}
    lines = ["[r]"]
    for rel, rel_id in relation_ids.items():
        lines.append(f"{rel_id}:{rel}")
    lines.append("[n]")
    node_to_idx = {node_id: str(i + 1) for i, node_id in enumerate(sorted(nodes))}
    for node_id, idx in node_to_idx.items():
        node = graph.nodes[node_id]
        if hybrid:
            # Only emit metadata tokens that actually exist — fall back to plain label if none.
            meta_parts = []
            if node.kind and node.kind != "unknown":
                meta_parts.append(f"[{node.kind}]")
            if node.summary:
                meta_parts.append(node.summary)
            if meta_parts:
                lines.append(f"{idx} {node.label} {' '.join(meta_parts)}")
            else:
                lines.append(f"{idx} {node.label}")
            for fact in node.facts[:3]:
                lines.append(f" {fact}")
        else:
            lines.append(f"{idx} {node.label}")
    lines.append("[e]")
    for edge in edges:
        rel_id = relation_ids.get(edge.type, edge.type)
        src_idx = node_to_idx[edge.source]
        tgt_idx = node_to_idx[edge.target]
        lines.append(f"{src_idx} {tgt_idx} {rel_id} {edge.weight:g}")
    return "\n".join(lines)


def render_svo(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    """Subject-verb-object triples — self-describing, zero schema overhead.

    Format: Label -type-> Label (weight)
    An LLM understands this cold with no instructions. Best for small 1-hop
    queries where the schema preamble of gg_max would cost more than the savings.
    Omits weight when 1.0 (implicit default).
    """
    node_labels = {nid: graph.nodes[nid].label for nid in nodes if nid in graph.nodes}
    lines = []
    for edge in edges:
        src = node_labels.get(edge.source, edge.source)
        tgt = node_labels.get(edge.target, edge.target)
        if edge.weight != 1.0:
            lines.append(f"{src} -{edge.type}-> {tgt} ({edge.weight:g})")
        else:
            lines.append(f"{src} -{edge.type}-> {tgt}")
    return "\n".join(lines)


def render_packet(graph: Graph, nodes: set[str], edges: list[Edge], packet: str) -> str:
    if packet == "lowlevel":
        return render_lowlevel(graph, nodes, edges)
    if packet == "sql":
        return render_sql(graph, nodes, edges)
    if packet == "hybrid":
        return render_hybrid(graph, nodes, edges)
    if packet == "semantic_arrow":
        return render_semantic_arrow(graph, nodes, edges)
    if packet == "gg_max":
        return render_gg_max(graph, nodes, edges)
    if packet == "gg_max_hybrid":
        return render_gg_max(graph, nodes, edges, hybrid=True)
    if packet == "svo":
        return render_svo(graph, nodes, edges)
    raise ValueError(f"unknown packet format: {packet}")
