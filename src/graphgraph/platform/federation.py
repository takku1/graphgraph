from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from ..io import load_any
from .persistence import PLATFORM_STATE_VERSION, atomic_write_json, file_lock


@dataclass(frozen=True)
class ProjectEntry:
    name: str
    root: str
    graph: str
    tags: tuple[str, ...] = ()


class ProjectRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[ProjectEntry]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [ProjectEntry(
            str(item["name"]), str(item["root"]), str(item["graph"]), tuple(item.get("tags", []))
        ) for item in data.get("projects", [])]

    def register(self, name: str, root: Path, graph: Path, *, tags: tuple[str, ...] = ()) -> ProjectEntry:
        entry = ProjectEntry(name, str(root.resolve()), str(graph.resolve()), tags)
        with file_lock(self.path):
            entries = {item.name: item for item in self.list()}
            entries[name] = entry
            atomic_write_json(
                self.path,
                {
                    "version": PLATFORM_STATE_VERSION,
                    "projects": [
                        asdict(item)
                        for item in sorted(entries.values(), key=lambda value: value.name)
                    ],
                },
                lock=False,
            )
        return entry

    def build(self, *, names: tuple[str, ...] = ()) -> Graph:
        entries = [entry for entry in self.list() if not names or entry.name in names]
        return federate_graphs({entry.name: load_any(Path(entry.graph)) for entry in entries})


def federate_graphs(graphs: dict[str, Graph]) -> Graph:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    labels: dict[str, list[str]] = {}
    for project, graph in sorted(graphs.items()):
        project_id = f"project:{project}"
        nodes[project_id] = Node(project_id, project, kind="project", scope=project)
        for node in graph.nodes.values():
            node_id = f"{project}::{node.id}"
            nodes[node_id] = Node(
                id=node_id,
                label=node.label,
                kind=node.kind,
                path=f"{project}/{node.path}" if node.path else "",
                summary=node.summary,
                facts=node.facts,
                scope=project,
                parent=f"{project}::{node.parent}" if node.parent else project_id,
                source=node.source,
                confidence=node.confidence,
                active=node.active,
                created_at=node.created_at,
                updated_at=node.updated_at,
            )
            labels.setdefault(node.label.casefold(), []).append(node_id)
            if node.path and "/" not in node.path.replace("\\", "/"):
                edges.append(Edge(project_id, node_id, "contains", provenance="federation"))
        for edge in graph.edges:
            edges.append(Edge(
                f"{project}::{edge.source}",
                f"{project}::{edge.target}",
                edge.type,
                edge.weight,
                edge.confidence,
                edge.provenance,
                edge.evidence,
                edge.source_location,
                edge.valid_from,
                edge.valid_to,
                edge.active,
            ))
    for ids in labels.values():
        projects = {node_id.split("::", 1)[0] for node_id in ids}
        if len(projects) < 2 or len(ids) > 8:
            continue
        for left, right in zip(sorted(ids), sorted(ids)[1:]):
            if left.split("::", 1)[0] != right.split("::", 1)[0]:
                edges.append(Edge(left, right, "cross_repo", confidence=0.65, provenance="federation", evidence="shared symbol label"))
    return Graph(nodes=nodes, edges=edges, metadata={"projects": ",".join(sorted(graphs))})
