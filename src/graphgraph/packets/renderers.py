from __future__ import annotations

from ..graph.core import Edge, Graph
from ..graph.ontology import DEFAULT_RELATIONS

DEFAULT_RELATION_ORDER = tuple(DEFAULT_RELATIONS)


def render_lowlevel(graph: Graph, nodes: set[str], edges: list[Edge], relations: tuple[str, ...] = DEFAULT_RELATION_ORDER) -> str:
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
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
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
    # Use short integer handles as the node ``id`` so edge rows do not repeat the
    # full qualified node ids. Qualified ids can be long (e.g.
    # ``pkg_module_py__Class_method``); repeating them on every edge made this
    # format scale badly on real repos. The integer ``id`` column is the join key
    # for edges; ``path`` still carries the source location for traceability.
    node_to_idx = {node_id: i + 1 for i, node_id in enumerate(sorted(nodes))}
    node_rows = []
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        node_rows.append(f"{node_to_idx[node_id]},{node.label},{node.kind},{node.path}")
    edge_rows = []
    for edge in edges:
        source = node_to_idx.get(edge.source)
        target = node_to_idx.get(edge.target)
        if source is None or target is None:
            continue
        edge_rows.append(f"{source},{target},{edge.type},{edge.weight:g}")
    return (
        "TABLE nodes: id,label,kind,path | "
        + " | ".join(node_rows)
        + "\nTABLE edges: source,target,type,weight | "
        + " | ".join(edge_rows)
    )


def render_hybrid(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
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
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
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
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
    relation_ids = _relation_ids(edges, relations)
    lines = ["[r]"]
    for rel, rel_id in relation_ids.items():
        lines.append(f"{rel_id}:{rel}")
    lines.append("[n]")
    node_to_idx = {node_id: str(i + 1) for i, node_id in enumerate(sorted(nodes))}
    grouped = _group_nodes_by_subsystem(nodes, graph)
    for sub, sub_nodes in grouped:
        for node_id in sub_nodes:
            idx = node_to_idx[node_id]
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
    for rel_id, rel_edges in _group_edges_by_relation(edges, relation_ids):
        lines.append(f"{rel_id}:")
        for edge in rel_edges:
            src_idx = node_to_idx[edge.source]
            tgt_idx = node_to_idx[edge.target]
            if abs(edge.weight - 1.0) > 1e-9:
                lines.append(f"{src_idx} {tgt_idx} {edge.weight:g}")
            else:
                lines.append(f"{src_idx} {tgt_idx}")
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


def _group_edges_by_relation(edges: list[Edge], relation_ids: dict[str, int]) -> list[tuple[str, list[Edge]]]:
    groups: dict[str, list[Edge]] = {}
    order: list[str] = []
    for edge in edges:
        rel_id = str(relation_ids.get(edge.type, edge.type))
        if rel_id not in groups:
            groups[rel_id] = []
            order.append(rel_id)
        groups[rel_id].append(edge)
    return [(rel_id, groups[rel_id]) for rel_id in order]


def _existing_nodes(graph: Graph, nodes: set[str]) -> set[str]:
    return {node_id for node_id in nodes if node_id in graph.nodes}


def _existing_edges(nodes: set[str], edges: list[Edge]) -> list[Edge]:
    return [edge for edge in edges if edge.source in nodes and edge.target in nodes]


def _subsystem_name(path: str) -> str:
    if not path:
        return "unknown"
    p = path.replace("\\", "/").strip("/")
    parts = p.split("/")
    if len(parts) > 1:
        # Detect common workspace folders that are just transparent wrappers.
        # For these we look one level deeper for the actual subsystem name.
        TRANSPARENT_WRAPPERS = {
            "crates", "packages", "apps", "libs", "modules", "src", "subprojects",
            "source", "sources", "lib", "pkg", "internal", "cmd", "service",
            "services", "core", "common", "shared", "api", "server", "client",
        }
        if parts[0] in TRANSPARENT_WRAPPERS and len(parts) > 2:
            return parts[1]
        if parts[0] in TRANSPARENT_WRAPPERS:
            return parts[1]
        return parts[0]
    return "root"


def _group_nodes_by_subsystem(nodes: set[str], graph: Graph) -> list[tuple[str, list[str]]]:
    subsystems: dict[str, list[str]] = {}
    for node_id in sorted(nodes):
        node = graph.nodes.get(node_id)
        if not node:
            continue
        sub = _subsystem_name(node.path)
        subsystems.setdefault(sub, []).append(node_id)

    def sub_key(item: tuple[str, list[str]]) -> tuple[int, str]:
        name = item[0]
        if name == "root":
            return (0, "")
        if name == "unknown":
            return (2, "")
        return (1, name)

    return sorted(subsystems.items(), key=sub_key)


def render_svo(graph: Graph, nodes: set[str], edges: list[Edge]) -> str:
    """Subject-verb-object triples — self-describing, zero schema overhead.

    Format: Label -type-> Label (weight)
    An LLM understands this cold with no instructions. Best for small 1-hop
    queries where the schema preamble of gg_max would cost more than the savings.
    Omits weight when 1.0 (implicit default).
    """
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
    node_labels = {nid: graph.nodes[nid].label for nid in nodes}
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
    nodes = _existing_nodes(graph, nodes)
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
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
    node_to_idx = {node_id: i for i, node_id in enumerate(sorted(nodes))}
    kinds = ["file", "module", "class", "function", "struct", "method", "concept", "section", "policy", "decision_trace", "commit"]
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
            
    # Calculate geodesic shortest path distance matrix (Spatial Bias Tensor)
    import collections
    adj = collections.defaultdict(set)
    for edge in edges:
        src_idx = node_to_idx.get(edge.source)
        tgt_idx = node_to_idx.get(edge.target)
        if src_idx is not None and tgt_idx is not None:
            adj[src_idx].add(tgt_idx)
            adj[tgt_idx].add(src_idx)
            
    n = len(node_to_idx)
    shortest_paths = [[99] * n for _ in range(n)]
    for i in range(n):
        shortest_paths[i][i] = 0
        queue = collections.deque([(i, 0)])
        visited = {i}
        while queue:
            curr, dist = queue.popleft()
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    shortest_paths[i][neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))
                    
    lines.append("")
    lines.append("@s")
    for row in shortest_paths:
        lines.append("[" + ",".join(str(val) for val in row) + "]")
        
    return "\n".join(lines)


def _lexical_ids(nodes: set[str], graph: Graph) -> dict[str, str]:
    seen = set()
    node_to_id = {}
    for node_id in sorted(nodes):
        node = graph.nodes[node_id]
        label = node.label or node_id
        # Normalize: keep alphanumeric and lowercase
        base = "".join(c.lower() for c in label if c.isalnum())
        if not base:
            base = "node"
        # Truncate to 8 chars
        candidate = base[:8]
        # Disambiguate collisions
        if candidate in seen:
            suffix = 2
            while f"{candidate[:6]}{suffix}" in seen:
                suffix += 1
            candidate = f"{candidate[:6]}{suffix}"
        seen.add(candidate)
        node_to_id[node_id] = candidate
    return node_to_id


def render_gg_lex(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    relations: tuple[str, ...] = DEFAULT_RELATION_ORDER,
    hybrid: bool = False,
) -> str:
    nodes = _existing_nodes(graph, nodes)
    edges = _existing_edges(nodes, edges)
    relation_ids = _relation_ids(edges, relations)
    lines = ["[r]"]
    for rel, rel_id in relation_ids.items():
        lines.append(f"{rel_id}:{rel}")
    lines.append("[n]")
    node_to_id = _lexical_ids(nodes, graph)
    grouped = _group_nodes_by_subsystem(nodes, graph)
    for sub, sub_nodes in grouped:
        for node_id in sub_nodes:
            node = graph.nodes[node_id]
            lex_id = node_to_id[node_id]
            if hybrid:
                meta_parts = []
                if node.kind and node.kind != "unknown":
                    meta_parts.append(f"[{node.kind}]")
                if node.summary:
                    meta_parts.append(node.summary)
                if meta_parts:
                    lines.append(f"{lex_id} {node.label} {' '.join(meta_parts)}")
                else:
                    lines.append(f"{lex_id} {node.label}")
                for fact in node.facts[:3]:
                    lines.append(f" {fact}")
            else:
                lines.append(f"{lex_id} {node.label}")
    lines.append("[e]")
    for rel_id, rel_edges in _group_edges_by_relation(edges, relation_ids):
        lines.append(f"{rel_id}:")
        for edge in rel_edges:
            src_id = node_to_id[edge.source]
            tgt_id = node_to_id[edge.target]
            if abs(edge.weight - 1.0) > 1e-9:
                lines.append(f"{src_id} {tgt_id} {edge.weight:g}")
            else:
                lines.append(f"{src_id} {tgt_id}")
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
    if packet == "gg_lex":
        return render_gg_lex(graph, nodes, edges)
    if packet == "gg_lex_hybrid":
        return render_gg_lex(graph, nodes, edges, hybrid=True)
    if packet == "svo":
        return render_svo(graph, nodes, edges)
    if packet == "doc_summary":
        return render_doc_summary(graph, nodes, edges)
    if packet in {"tensor", "csr_arrays"}:
        return render_tensor_array(graph, nodes, edges)
    raise ValueError(f"unknown packet format: {packet}")
