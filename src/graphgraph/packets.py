from __future__ import annotations

from .core import Edge, Graph
from .ontology import DEFAULT_RELATIONS


DEFAULT_RELATION_ORDER = tuple(DEFAULT_RELATIONS)


def render_lowlevel(graph: Graph, nodes: set[str], edges: list[Edge], relations: tuple[str, ...] = DEFAULT_RELATION_ORDER) -> str:
    relation_ids = _relation_ids(edges, relations)
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
    relations: tuple[str, ...] = DEFAULT_RELATION_ORDER,
    hybrid: bool = False,
) -> str:
    relation_ids = _relation_ids(edges, relations)
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


def _relation_ids(edges: list[Edge], relations: tuple[str, ...]) -> dict[str, int]:
    edge_types = {edge.type for edge in edges}
    ordered = [rel for rel in relations if rel in edge_types]
    seen = set(ordered)
    for edge in sorted(edges, key=lambda e: e.type):
        if edge.type not in seen:
            seen.add(edge.type)
            ordered.append(edge.type)
    return {rel: i + 1 for i, rel in enumerate(ordered)}


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


def render_doc_summary(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    """Compact grounded notes for documentation-style summary questions.

    This intentionally omits topology. For docs questions the useful payload is
    usually the matched section/file labels plus short grounded facts, not every
    `section_of` or `discusses` edge around them.
    """
    lines = ["[d]"]
    for node_id in sorted(nodes, key=lambda nid: (graph.nodes[nid].path, graph.nodes[nid].label, nid)):
        node = graph.nodes[node_id]
        if node.kind == "concept" and not node.facts:
            continue
        parts = [node.label]
        if node.kind and node.kind != "unknown":
            parts.append(f"[{node.kind}]")
        if node.path:
            parts.append(node.path)
        if node.summary:
            parts.append(node.summary)
        lines.append(" ".join(parts))
        for fact in node.facts[:2]:
            lines.append(f" {fact}")
    return "\n".join(lines)


def render_tensor_array(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    node_to_idx = {node_id: i for i, node_id in enumerate(sorted(nodes))}
    kinds = ["file", "module", "class", "function", "struct", "method", "concept", "section", "policy", "decision_trace"]
    kind_to_id = {k: i for i, k in enumerate(kinds)}
    
    relations = list(DEFAULT_RELATION_ORDER)
    for edge in edges:
        if edge.type not in relations:
            relations.append(edge.type)
    rel_to_id = {r: i for i, r in enumerate(relations)}
    
    lines = []
    lines.append("@types")
    lines.append("[" + ", ".join(f"{idx}: {k}" for k, idx in kind_to_id.items()) + "]")
    lines.append("@relations")
    lines.append("[" + ", ".join(f"{idx}: {r}" for r, idx in rel_to_id.items()) + "]")
    lines.append("")
    
    lines.append("@v")
    for node_id, idx in node_to_idx.items():
        node = graph.nodes[node_id]
        kind_id = kind_to_id.get(node.kind, len(kinds))
        size = len(node.facts) * 10 + len(node.summary or "")
        lines.append(f"[{idx}, {node.label}, {kind_id}, {size}]")
    lines.append("")
    
    lines.append("@a")
    for edge in edges:
        src_idx = node_to_idx.get(edge.source)
        tgt_idx = node_to_idx.get(edge.target)
        if src_idx is not None and tgt_idx is not None:
            rel_id = rel_to_id.get(edge.type)
            lines.append(f"[{src_idx}, {tgt_idx}, {rel_id}, {edge.weight:g}]")
            
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
    if packet == "doc_summary":
        return render_doc_summary(graph, nodes, edges)
    if packet in {"tensor", "csr_arrays"}:
        return render_tensor_array(graph, nodes, edges)
    raise ValueError(f"unknown packet format: {packet}")
