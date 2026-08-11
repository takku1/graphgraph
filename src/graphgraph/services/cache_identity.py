"""Deterministic cache identities for graph-derived response packets."""

from __future__ import annotations

from pathlib import Path

from ..graph.core import Graph

_GENERATED_ARTIFACT_NAMES = frozenset(
    {
        "kv_cache.json",
        "semantic.json",
        "activation_state.json",
        "memory.json",
        "episodes.jsonl",
        "projects.json",
        "runtime-trace.jsonl",
        "traces.jsonl",
        "trace.jsonl",
    }
)


def packet_dependency_paths(graph: Graph, node_ids: set[str]) -> tuple[str, ...]:
    """Return the sorted source paths that determine a packet."""
    return tuple(
        sorted(
            node.path
            for node_id in node_ids
            if (node := graph.nodes.get(node_id)) is not None and node.path
        )
    )


def is_generated_artifact(path: str) -> bool:
    """Return whether a worktree path is an output of GraphGraph itself."""
    parts = Path(path).parts
    if ".graphgraph" in parts:
        return True
    name = parts[-1] if parts else path
    return name in _GENERATED_ARTIFACT_NAMES or name.endswith(
        (".gg", ".gg.manifest.json")
    )


def worktree_signature(
    start: Path | None = None,
) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint source changes while excluding generated graph artifacts."""
    from ..retrieval.git_utils import get_git_worktree_paths

    signature = []
    root = start.resolve() if start is not None else Path.cwd().resolve()
    changed, deleted = get_git_worktree_paths(root)
    for path in (*changed, *deleted):
        if is_generated_artifact(path):
            continue
        source_path = root / path
        try:
            stat = source_path.stat()
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, 0, 0))
    return tuple(sorted(set(signature)))


def file_signature(path: Path | None) -> tuple[str, int, int] | None:
    """Return a stable filesystem identity for one optional file."""
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


__all__ = [
    "file_signature",
    "is_generated_artifact",
    "packet_dependency_paths",
    "worktree_signature",
]
