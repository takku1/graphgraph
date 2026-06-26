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


