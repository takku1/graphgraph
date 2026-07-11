from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..graph.core import Graph

logger = logging.getLogger(__name__)

_GIT_DIFF_CACHE_TTL_SECONDS = 1.0
_git_diff_cache: dict[Path, tuple[float, dict[str, int]]] = {}


def get_git_modified_files() -> dict[str, int]:
    """Return current worktree change counts with a short repository-local cache.

    Returns a dict mapping relative file path -> total change count (additions + deletions).
    """
    git_root = _find_git_root(Path.cwd())
    if git_root is None:
        return {}
    now = time.monotonic()
    cached = _git_diff_cache.get(git_root)
    if cached is not None and now - cached[0] < _GIT_DIFF_CACHE_TTL_SECONDS:
        return cached[1]

    changes: dict[str, int] = {}
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD", "--numstat"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.5,
            cwd=git_root,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) >= 3:
                    added_str, deleted_str, file_path = parts[0], parts[1], parts[2]
                    added = int(added_str) if added_str.isdigit() else 0
                    deleted = int(deleted_str) if deleted_str.isdigit() else 0
                    file_path = file_path.replace("\\", "/")
                    changes[file_path] = added + deleted

        res_untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.5,
            cwd=git_root,
        )
        if res_untracked.returncode == 0:
            for line in res_untracked.stdout.splitlines():
                file_path = line.strip().replace("\\", "/")
                if file_path and file_path not in changes:
                    changes[file_path] = 1
    except Exception:
        logger.debug("git-modified-files lookup failed; session weighting disabled", exc_info=True)

    _git_diff_cache[git_root] = (now, changes)
    return changes


def _find_git_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_modified_node_ids(graph: Graph, modified_paths: dict[str, int]) -> dict[str, list[str]]:
    """Map each git-modified file path to the active node id(s) it matches.

    A path can match more than one active node (e.g. several symbol nodes in
    the same file all carry that file's path), so this preserves a full list
    per path rather than a single id. Builds a path/id -> node ids index once
    (O(nodes)) instead of the O(paths * nodes) nested scan that used to be
    duplicated independently in search.py and context.py.
    """
    index: dict[str, list[str]] = {}
    for node_id, node in graph.nodes.items():
        if not node.active:
            continue
        index.setdefault(node_id, []).append(node_id)
        if node.path:
            index.setdefault(node.path.replace("\\", "/"), []).append(node_id)

    return {path: index[path] for path in modified_paths if path in index}
