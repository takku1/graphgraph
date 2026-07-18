from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from .persistence import PLATFORM_STATE_VERSION, append_jsonl, file_lock


@dataclass(frozen=True)
class Episode:
    id: str
    timestamp: str
    kind: str
    summary: str
    actor: str = ""
    related_nodes: tuple[str, ...] = ()
    supersedes: str = ""
    facts: tuple[str, ...] = ()


class TemporalStore:
    """Append-only episode store with graph projection and supersession."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, episode: Episode) -> None:
        append_jsonl(self.path, {"version": PLATFORM_STATE_VERSION, **asdict(episode)})

    def read(self, *, as_of: str = "") -> list[Episode]:
        if not self.path.exists():
            return []
        with file_lock(self.path):
            lines = self.path.read_text(encoding="utf-8").splitlines()
        episodes = []
        for line in lines:
            if not line.strip():
                continue
            data = json.loads(line)
            episode = Episode(
                id=str(data["id"]),
                timestamp=str(data["timestamp"]),
                kind=str(data["kind"]),
                summary=str(data["summary"]),
                actor=str(data.get("actor", "")),
                related_nodes=tuple(str(value) for value in data.get("related_nodes", [])),
                supersedes=str(data.get("supersedes", "")),
                facts=tuple(str(value) for value in data.get("facts", [])),
            )
            if not as_of or _at_or_before(episode.timestamp, as_of):
                episodes.append(episode)
        return episodes

    def project(self, graph: Graph) -> Graph:
        nodes = dict(graph.nodes)
        edges = list(graph.edges)
        episodes = self.read()
        superseded = {episode.supersedes for episode in episodes if episode.supersedes}
        for episode in episodes:
            node_id = f"episode:{episode.id}"
            nodes[node_id] = Node(
                id=node_id,
                label=episode.summary,
                kind="episode",
                summary=episode.summary,
                facts=(f"kind:{episode.kind}",) + episode.facts,
                source=episode.actor,
                active=episode.id not in superseded,
                created_at=episode.timestamp,
                updated_at=episode.timestamp,
            )
            for related in episode.related_nodes:
                if related in nodes:
                    edges.append(Edge(
                        node_id,
                        related,
                        "records",
                        provenance="episode",
                        valid_from=episode.timestamp,
                    ))
            if episode.supersedes and f"episode:{episode.supersedes}" in nodes:
                old_id = f"episode:{episode.supersedes}"
                nodes[old_id] = replace(nodes[old_id], active=False, updated_at=episode.timestamp)
                edges.append(Edge(
                    node_id,
                    old_id,
                    "supersedes",
                    provenance="episode",
                    valid_from=episode.timestamp,
                ))
        return Graph(nodes=nodes, edges=edges, metadata=dict(graph.metadata))


def graph_as_of(graph: Graph, timestamp: str) -> Graph:
    """Return the graph state valid at an ISO-8601 timestamp."""
    nodes = {
        node_id: replace(node, active=True)
        for node_id, node in graph.nodes.items()
        if (not node.created_at or _at_or_before(node.created_at, timestamp))
        and (not node.updated_at or node.active or _at_or_before(timestamp, node.updated_at))
    }
    edges = [
        replace(edge, active=True)
        for edge in graph.edges
        if edge.source in nodes
        and edge.target in nodes
        and (not edge.valid_from or _at_or_before(edge.valid_from, timestamp))
        and (not edge.valid_to or _at_or_before(timestamp, edge.valid_to))
    ]
    metadata = dict(graph.metadata)
    metadata["as_of"] = timestamp
    return Graph(nodes=nodes, edges=edges, metadata=metadata)


def new_episode(
    episode_id: str,
    kind: str,
    summary: str,
    *,
    actor: str = "",
    related_nodes: tuple[str, ...] = (),
    supersedes: str = "",
    facts: tuple[str, ...] = (),
) -> Episode:
    return Episode(
        episode_id,
        datetime.now(timezone.utc).isoformat(),
        kind,
        summary,
        actor,
        related_nodes,
        supersedes,
        facts,
    )


def _at_or_before(left: str, right: str) -> bool:
    try:
        return _parse(left) <= _parse(right)
    except ValueError:
        return left <= right


def _parse(value: str) -> datetime:
    value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
