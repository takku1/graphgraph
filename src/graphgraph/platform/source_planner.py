from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from ..io import load_any_cached
from ..retrieval import search_nodes
from ..retrieval.anchors import explicit_query_identifiers
from .federation import ProjectRegistry
from .memory import MemoryRecord, MemoryStore
from .semantic import SemanticIndex
from .temporal import Episode, TemporalStore
from .tracing import ingest_runtime_trace

_TOKENS = re.compile(r"[A-Za-z0-9_]{2,}")
_RUNTIME_TERMS = {"runtime", "trace", "observed", "production", "execute", "execution", "call"}
_FEDERATION_TERMS = {"repository", "repositories", "repo", "repos", "project", "projects", "federated", "cross"}


@dataclass(frozen=True)
class SourcePlannerReceipt:
    mode: str
    lexical_strength: float
    exact_fast_path: bool = False
    semantic_seeds: int = 0
    semantic_rebuilt: bool = False
    memories: int = 0
    episodes: int = 0
    federated_projects: int = 0
    federated_nodes: int = 0
    trace_edges: int = 0
    seed_ids: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourcePlan:
    graph: Graph
    seed_ids: tuple[str, ...] = ()
    receipt: SourcePlannerReceipt = field(
        default_factory=lambda: SourcePlannerReceipt("off", 0.0)
    )
    preferred_paths: tuple[str, ...] = ()


class QuerySourcePlanner:
    """Project bounded auxiliary evidence into the native query graph."""

    def __init__(self, directory: Path, *, graph_path: Path | None = None) -> None:
        self.directory = directory
        self.graph_path = graph_path.resolve() if graph_path else None

    def plan(
        self,
        graph: Graph,
        query: str,
        *,
        mode: str = "auto",
        memory_scopes: tuple[str, ...] = ("project", "session"),
        max_semantic: int = 6,
        max_memories: int = 6,
        max_episodes: int = 6,
        max_projects: int = 3,
        max_foreign_nodes: int = 18,
    ) -> SourcePlan:
        if mode not in {"auto", "off", "all"}:
            raise ValueError(f"unknown source planner mode: {mode}")
        # An agent asks "what calls normalize_rust", not "normalize_rust", so
        # matching the fast path against the whole phrase always misses and
        # falls through to a full lexical scan -- which builds the search
        # index (~930ms on a 14.5k-node graph) purely to rediscover the one
        # symbol the query already named. The anchor layer resolves this by
        # extracting explicit identifiers; do the same here before paying for
        # the index.
        base_matches: tuple = ()
        if mode == "auto":
            identifiers = explicit_query_identifiers(query)
            if len(identifiers) == 1:
                base_matches = search_nodes(
                    graph,
                    identifiers[0],
                    limit=1,
                    personalize=False,
                    exact_fast_path=True,
                    exact_only=True,
                )
        if not base_matches:
            base_matches = search_nodes(
                graph,
                query,
                limit=12,
                personalize=False,
                exact_fast_path=mode == "auto",
            )
        preferred_paths = tuple(dict.fromkeys(
            match.node.path.replace("\\", "/")
            for match in base_matches
            if match.node.path
        ))
        lexical_strength = base_matches[0].score if base_matches else 0.0
        if mode == "off":
            return SourcePlan(
                graph,
                receipt=SourcePlannerReceipt(mode, lexical_strength),
                preferred_paths=preferred_paths,
            )
        if (
            mode == "auto"
            and len(base_matches) == 1
            and "exact_fast_path" in base_matches[0].reasons
        ):
            return SourcePlan(
                graph,
                receipt=SourcePlannerReceipt(
                    mode="exact_fast_path",
                    lexical_strength=lexical_strength,
                    exact_fast_path=True,
                    sources=("exact_lexical",),
                ),
                preferred_paths=preferred_paths,
            )

        current = graph
        seeds: list[str] = []
        sources: list[str] = []
        warnings: list[str] = []
        semantic_count = 0
        semantic_rebuilt = False
        memory_count = 0
        episode_count = 0
        federated_projects = 0
        federated_nodes = 0
        trace_edges = 0
        weak_lexical = _weak_lexical(base_matches)

        semantic_path = self.directory / "semantic.json"
        if mode == "all" or weak_lexical:
            try:
                semantic = SemanticIndex.load(semantic_path) if semantic_path.exists() else SemanticIndex(semantic_path)
                if not semantic.is_current(graph):
                    semantic.build(graph)
                    semantic_rebuilt = True
                semantic_ids = [
                    node_id
                    for node_id, _score in semantic.query(query, limit=max_semantic)
                    if node_id in current.nodes and current.nodes[node_id].active
                ]
                seeds.extend(semantic_ids)
                semantic_count = len(semantic_ids)
                if semantic_ids:
                    sources.append("semantic")
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"semantic:{type(exc).__name__}")

        memory_path = self.directory / "memory.json"
        if memory_path.exists():
            try:
                memories = MemoryStore(memory_path).search(
                    query,
                    scopes=memory_scopes,
                    limit=max_memories,
                )
                current, memory_ids = _project_memories(current, memories)
                seeds.extend(memory_ids)
                memory_count = len(memory_ids)
                if memory_ids:
                    sources.append("memory")
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"memory:{type(exc).__name__}")

        episode_path = self.directory / "episodes.jsonl"
        if episode_path.exists():
            try:
                episodes = _search_episodes(
                    TemporalStore(episode_path).read(),
                    query,
                    limit=max_episodes,
                )
                current, episode_ids = _project_episodes(current, episodes)
                seeds.extend(episode_ids)
                episode_count = len(episode_ids)
                if episode_ids:
                    sources.append("temporal")
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"temporal:{type(exc).__name__}")

        query_terms = set(_tokens(query))
        registry_path = self.directory / "projects.json"
        if registry_path.exists() and (mode == "all" or weak_lexical or query_terms & _FEDERATION_TERMS):
            try:
                current, foreign_ids, project_count = _project_federation(
                    current,
                    ProjectRegistry(registry_path),
                    query,
                    current_graph_path=self.graph_path,
                    max_projects=max_projects,
                    max_nodes=max_foreign_nodes,
                )
                seeds.extend(foreign_ids)
                federated_projects = project_count
                federated_nodes = len(foreign_ids)
                if foreign_ids:
                    sources.append("federation")
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"federation:{type(exc).__name__}")

        trace_path = _trace_path(self.directory)
        if trace_path and (mode == "all" or query_terms & _RUNTIME_TERMS):
            try:
                before = len(current.edges)
                current, trace_receipt = ingest_runtime_trace(current, trace_path)
                trace_edges = len(current.edges) - before
                seeds.extend(_trace_seed_ids(current, query, max_semantic))
                if trace_receipt.get("events"):
                    sources.append("runtime_trace")
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"runtime_trace:{type(exc).__name__}")

        unique_seeds = tuple(dict.fromkeys(node_id for node_id in seeds if node_id in current.nodes))[:12]
        receipt = SourcePlannerReceipt(
            mode=mode,
            lexical_strength=round(lexical_strength, 4),
            semantic_seeds=semantic_count,
            semantic_rebuilt=semantic_rebuilt,
            memories=memory_count,
            episodes=episode_count,
            federated_projects=federated_projects,
            federated_nodes=federated_nodes,
            trace_edges=trace_edges,
            seed_ids=unique_seeds,
            sources=tuple(dict.fromkeys(sources)),
            warnings=tuple(warnings),
        )
        return SourcePlan(
            current,
            seed_ids=unique_seeds,
            receipt=receipt,
            preferred_paths=preferred_paths,
        )


def source_state_signature(directory: Path) -> str:
    digest = hashlib.sha256()
    paths = [
        directory / "semantic.json",
        directory / "memory.json",
        directory / "episodes.jsonl",
        directory / "projects.json",
        *[directory / name for name in ("runtime-trace.jsonl", "traces.jsonl", "trace.jsonl")],
    ]
    for path in paths:
        if path.exists():
            stat = path.stat()
            digest.update(f"{path.name}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode("utf-8"))
    registry_path = directory / "projects.json"
    if registry_path.exists():
        try:
            for entry in ProjectRegistry(registry_path).list():
                graph_path = Path(entry.graph)
                if graph_path.exists():
                    stat = graph_path.stat()
                    digest.update(
                        f"project\0{entry.name}\0{graph_path.resolve()}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode(
                            "utf-8"
                        )
                    )
        except (OSError, ValueError, KeyError):
            digest.update(b"projects:unreadable\n")
    return digest.hexdigest()[:16]


def receipt_data(plan: SourcePlan) -> dict[str, object]:
    return asdict(plan.receipt)


def _weak_lexical(matches) -> bool:
    if not matches:
        return True
    top = matches[0]
    targeted = any(
        reason.startswith(("label_exact", "path_exact", "qualified", "id_exact"))
        for reason in top.reasons
    )
    return top.score < 8.0 and not targeted


def _project_memories(graph: Graph, records: list[MemoryRecord]) -> tuple[Graph, tuple[str, ...]]:
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    ids: list[str] = []
    for record in records:
        node_id = f"memory:{record.id}"
        nodes[node_id] = Node(
            node_id,
            record.content[:80],
            kind=f"memory_{record.kind}",
            summary=record.content,
            scope=record.scope,
            source=record.source,
            created_at=record.created_at,
            updated_at=record.created_at,
        )
        ids.append(node_id)
        for related in record.related_nodes:
            if related in nodes:
                edges.append(Edge(node_id, related, "remembers", provenance="memory"))
    return Graph(nodes, edges, dict(graph.metadata)), tuple(ids)


def _search_episodes(episodes: list[Episode], query: str, *, limit: int) -> list[Episode]:
    query_terms = set(_tokens(query))
    scored: list[tuple[float, str, Episode]] = []
    for episode in episodes:
        terms = set(_tokens(" ".join((episode.kind, episode.summary, *episode.facts))))
        overlap = len(query_terms & terms)
        if overlap:
            scored.append((overlap / max(1, len(query_terms | terms)), episode.timestamp, episode))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [episode for _score, _timestamp, episode in scored[:limit]]


def _project_episodes(graph: Graph, episodes: list[Episode]) -> tuple[Graph, tuple[str, ...]]:
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    ids: list[str] = []
    selected = {episode.id for episode in episodes}
    superseded = {episode.supersedes for episode in episodes if episode.supersedes}
    for episode in episodes:
        node_id = f"episode:{episode.id}"
        nodes[node_id] = Node(
            node_id,
            episode.summary,
            kind="episode",
            summary=episode.summary,
            facts=(f"kind:{episode.kind}",) + episode.facts,
            source=episode.actor,
            active=episode.id not in superseded,
            created_at=episode.timestamp,
            updated_at=episode.timestamp,
        )
        ids.append(node_id)
        for related in episode.related_nodes:
            if related in nodes:
                edges.append(Edge(node_id, related, "records", provenance="episode"))
        if episode.supersedes in selected:
            edges.append(Edge(node_id, f"episode:{episode.supersedes}", "supersedes", provenance="episode"))
    return Graph(nodes, edges, dict(graph.metadata)), tuple(ids)


def _project_federation(
    graph: Graph,
    registry: ProjectRegistry,
    query: str,
    *,
    current_graph_path: Path | None,
    max_projects: int,
    max_nodes: int,
) -> tuple[Graph, tuple[str, ...], int]:
    candidates: list[tuple[float, str, Graph, tuple[str, ...]]] = []
    for entry in registry.list():
        entry_path = Path(entry.graph).resolve()
        if current_graph_path and entry_path == current_graph_path:
            continue
        foreign = load_any_cached(entry_path)
        matches = search_nodes(foreign, query, limit=4, personalize=False)
        if not matches:
            continue
        candidates.append((matches[0].score, entry.name, foreign, tuple(match.node.id for match in matches)))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    seed_ids: list[str] = []
    base_labels: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        if node.label:
            base_labels.setdefault(node.label.casefold(), []).append(node.id)
    remaining = max_nodes
    projects = 0
    for _score, project, foreign, starts in candidates[:max_projects]:
        if remaining <= 0:
            break
        selected = set(starts)
        for edge in foreign.edges:
            if edge.source in selected or edge.target in selected:
                selected.update((edge.source, edge.target))
            if len(selected) >= remaining:
                break
        ordered = list(dict.fromkeys((*starts, *sorted(selected - set(starts)))))
        selected = set(ordered[:remaining])
        if not selected:
            continue
        project_id = f"project:{project}"
        nodes.setdefault(project_id, Node(project_id, project, kind="project", scope=project))
        for node_id in selected:
            node = foreign.nodes[node_id]
            foreign_id = f"{project}::{node_id}"
            nodes[foreign_id] = Node(
                foreign_id,
                node.label,
                node.kind,
                f"{project}/{node.path}" if node.path else "",
                node.summary,
                node.facts,
                project,
                project_id,
                node.source,
                node.confidence,
                node.active,
                node.created_at,
                node.updated_at,
            )
            edges.append(Edge(project_id, foreign_id, "contains", provenance="federation"))
            for local_id in base_labels.get(node.label.casefold(), ()):
                edges.append(Edge(local_id, foreign_id, "cross_repo", confidence=0.65, provenance="federation"))
        for edge in foreign.edges:
            if edge.source in selected and edge.target in selected:
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
        seed_ids.extend(f"{project}::{node_id}" for node_id in starts if node_id in selected)
        remaining -= len(selected)
        projects += 1
    return Graph(nodes, edges, dict(graph.metadata)), tuple(seed_ids), projects


def _trace_path(directory: Path) -> Path | None:
    for name in ("runtime-trace.jsonl", "traces.jsonl", "trace.jsonl"):
        path = directory / name
        if path.exists():
            return path
    return None


def _trace_seed_ids(graph: Graph, query: str, limit: int) -> tuple[str, ...]:
    observed = {
        endpoint
        for edge in graph.edges
        if edge.type == "observed_calls"
        for endpoint in (edge.source, edge.target)
    }
    matches = search_nodes(graph, query, limit=max(limit * 2, 1), personalize=False)
    return tuple(match.node.id for match in matches if match.node.id in observed)[:limit]


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKENS.findall(value))
