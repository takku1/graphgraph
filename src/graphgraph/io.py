from __future__ import annotations

import json
from pathlib import Path

from .core import Edge, Graph, Node, Policy


def load_graph(path: Path) -> Graph:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = {
        item["id"]: Node(
            id=item["id"],
            label=item.get("label") or item.get("name") or item["id"],
            kind=item.get("kind") or item.get("file_type") or item.get("type") or "unknown",
            path=item.get("path") or item.get("source_file") or "",
            summary=item.get("summary") or item.get("properties", {}).get("description") or "",
            facts=tuple(item.get("facts") or []),
        )
        for item in data["nodes"]
    }
    edges_data = data.get("edges") or data.get("links") or []
    edges = [
        Edge(
            source=item["source"],
            target=item["target"],
            type=item.get("type") or item.get("relation") or "dependency",
            weight=float(item.get("weight") if item.get("weight") is not None else 1.0),
        )
        for item in edges_data
    ]
    return Graph(nodes=nodes, edges=edges)


def load_policies(path: Path) -> list[Policy]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Policy(
            id=item["id"],
            kind=item["kind"],
            priority=item["priority"],
            applies_to=tuple(item.get("applies_to", [])),
            task_tags=tuple(item.get("task_tags", [])),
            compact=item["compact"],
            content=item.get("content", ""),
        )
        for item in data
    ]


def save_graph(graph: Graph, path: Path) -> None:
    data = {
        "nodes": [
            {
                "id": node.id,
                "label": node.label,
                "kind": node.kind,
                "path": node.path,
                "summary": node.summary,
                "facts": list(node.facts),
            }
            for node in graph.nodes.values()
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "weight": edge.weight,
            }
            for edge in graph.edges
        ],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_graphify(base: Graph, overlay: Graph) -> Graph:
    """Merge an overlay graph (e.g. from graphify) into a base (scanned) graph.

    - Nodes whose path matches an existing base node: enrich summary/facts from overlay.
    - Overlay-only nodes: added verbatim.
    - Overlay edges: added if both endpoints resolve into the merged node set.
    """
    path_to_base_id: dict[str, str] = {
        n.path.lstrip("/").replace("\\", "/"): nid
        for nid, n in base.nodes.items()
        if n.path
    }

    new_nodes: dict[str, Node] = dict(base.nodes)
    overlay_id_map: dict[str, str] = {}  # overlay_node_id -> merged_node_id

    for ov_id, ov_node in overlay.nodes.items():
        norm = ov_node.path.lstrip("/").replace("\\", "/")
        if norm in path_to_base_id:
            base_id = path_to_base_id[norm]
            base_node = new_nodes[base_id]
            new_nodes[base_id] = Node(
                id=base_node.id,
                label=base_node.label,
                kind=base_node.kind,
                path=base_node.path,
                summary=ov_node.summary or base_node.summary,
                facts=ov_node.facts if ov_node.facts else base_node.facts,
            )
            overlay_id_map[ov_id] = base_id
        else:
            new_nodes[ov_id] = ov_node
            overlay_id_map[ov_id] = ov_id

    seen_edges: set[tuple[str, str, str]] = {(e.source, e.target, e.type) for e in base.edges}
    new_edges: list[Edge] = list(base.edges)
    for edge in overlay.edges:
        src = overlay_id_map.get(edge.source, edge.source)
        tgt = overlay_id_map.get(edge.target, edge.target)
        if src in new_nodes and tgt in new_nodes:
            key = (src, tgt, edge.type)
            if key not in seen_edges:
                seen_edges.add(key)
                new_edges.append(Edge(source=src, target=tgt, type=edge.type, weight=edge.weight))

    return Graph(nodes=new_nodes, edges=new_edges)


_GRAPHIFY_CANDIDATES = [
    "graphify-out/graph.json",
    ".graphify/graph.json",
    "graphify/graph.json",
]


def find_graphify_path(workspace_root: Path = Path(".")) -> Path | None:
    for c in _GRAPHIFY_CANDIDATES:
        p = workspace_root / c
        if p.exists():
            return p
    return None


def find_graph_path(workspace_root: Path = Path(".")) -> Path:
    candidates = [
        workspace_root / ".graphgraph" / "graph.json",
        workspace_root / "graphify-out" / "graph.json",
        workspace_root / ".code-review-graph" / "graph.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Could not find a codebase graph file in default paths: "
        f"{[str(c) for c in candidates]}. Please specify the path explicitly."
    )


def find_policies_path(workspace_root: Path = Path(".")) -> Path | None:
    candidates = [
        workspace_root / ".graphgraph" / "policies.json",
        workspace_root / "policies.json",
        workspace_root / ".code-review-graph" / "policies.json",
        workspace_root / ".agents" / "policies.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


