from __future__ import annotations

import logging
import math
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..graph.core import Graph

logger = logging.getLogger(__name__)

_GIT_DIFF_CACHE_TTL_SECONDS = 1.0
_git_diff_cache: dict[Path, tuple[float, dict[str, int]]] = {}
_git_path_cache: dict[Path, tuple[float, tuple[tuple[str, ...], tuple[str, ...]]]] = {}
_git_ignore_cache: dict[tuple[Path, tuple[str, ...]], tuple[float, tuple[str, ...]]] = {}
_git_tracked_cache: dict[Path, tuple[float, tuple[str, ...]]] = {}


def get_git_modified_files(start: Path | None = None) -> dict[str, int]:
    """Return current worktree change counts with a short repository-local cache.

    Returns a dict mapping relative file path -> total change count (additions + deletions).
    """
    git_root = _find_git_root(start or Path.cwd())
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


def get_git_worktree_paths(start: Path | None = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return changed and deleted worktree paths relative to the Git root.

    This is the cheap project-loop instruction set: Git already knows the
    candidate paths, so callers can hash only those files against the graph
    manifest rather than walking the repository. Rename records contribute
    the new path to ``changed`` and the old path to ``deleted``.
    """
    git_root = _find_git_root(start or Path.cwd())
    if git_root is None:
        return (), ()
    now = time.monotonic()
    cached = _git_path_cache.get(git_root)
    if cached is not None and now - cached[0] < _GIT_DIFF_CACHE_TTL_SECONDS:
        return cached[1]

    changed: set[str] = set()
    deleted: set[str] = set()
    tracked: set[str] = set()
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--name-status", "-z", "--find-renames"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1.5,
            cwd=git_root,
        )
        if result.returncode == 0:
            fields = result.stdout.decode("utf-8", errors="replace").split("\0")
            index = 0
            while index < len(fields) and fields[index]:
                status = fields[index]
                index += 1
                code = status[:1]
                if code in {"R", "C"} and index + 1 < len(fields):
                    old_path = fields[index].replace("\\", "/")
                    new_path = fields[index + 1].replace("\\", "/")
                    index += 2
                    changed.add(new_path)
                    tracked.add(new_path)
                    if code == "R":
                        deleted.add(old_path)
                    continue
                if index >= len(fields):
                    break
                path = fields[index].replace("\\", "/")
                index += 1
                if code == "D":
                    deleted.add(path)
                else:
                    changed.add(path)
                    tracked.add(path)

        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1.5,
            cwd=git_root,
        )
        if untracked.returncode == 0:
            changed.update(
                path.replace("\\", "/")
                for path in untracked.stdout.decode("utf-8", errors="replace").split("\0")
                if path
            )
    except Exception:
        logger.debug("git worktree path lookup failed; automatic graph sync disabled", exc_info=True)

    value = (tuple(sorted(changed - deleted)), tuple(sorted(deleted)))
    _git_path_cache[git_root] = (now, value)
    _git_tracked_cache[git_root] = (now, tuple(sorted(tracked - deleted)))
    return value


def get_git_tracked_changed_paths(start: Path | None = None) -> tuple[str, ...]:
    """Changed paths Git already tracks, as opposed to new untracked files.

    The distinction decides whether ignore rules may be applied. Git's rule
    is that `.gitignore` governs untracked files only -- a tracked file
    listed there still reports its changes -- so filtering the tracked set
    through ignore rules drops real edits and leaves the graph stale while
    reporting fresh. The untracked set needs no such filtering either: it
    comes from `ls-files --exclude-standard`, which git has already applied
    those rules to.
    """
    git_root = _find_git_root(start or Path.cwd())
    if git_root is None:
        return ()
    cached = _git_tracked_cache.get(git_root)
    if cached is None or time.monotonic() - cached[0] >= _GIT_DIFF_CACHE_TTL_SECONDS:
        get_git_worktree_paths(start)
        cached = _git_tracked_cache.get(git_root)
    return cached[1] if cached else ()


def get_git_ignored_paths(paths: tuple[str, ...], start: Path | None = None) -> tuple[str, ...]:
    """Return candidate paths excluded by the repository's current ignore rules."""
    if not paths:
        return ()
    git_root = _find_git_root(start or Path.cwd())
    if git_root is None:
        return ()
    # Same short TTL as the worktree diff above, and for the same reason: a
    # single request inspects freshness more than once, and each miss was
    # paying a `git check-ignore` process spawn. Keyed on the exact path set
    # so a different candidate list is never answered from another's result.
    now = time.monotonic()
    cache_key = (git_root, paths)
    cached = _git_ignore_cache.get(cache_key)
    if cached is not None and now - cached[0] < _GIT_DIFF_CACHE_TTL_SECONDS:
        return cached[1]
    payload = ("\0".join(paths) + "\0").encode("utf-8")
    try:
        result = subprocess.run(
            # No --no-index: that flag makes check-ignore disregard the index,
            # so a *tracked* file listed in .gitignore is reported as ignored
            # and silently dropped from the freshness candidate list -- edit
            # it and the graph stays stale while reporting fresh. Git's own
            # rule is that .gitignore governs untracked files only, and
            # matching that rule is what makes this agree with `git status`.
            ["git", "check-ignore", "-z", "--stdin"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1.5,
            cwd=git_root,
        )
    except Exception:
        logger.debug("git ignore lookup failed; targeted sync kept existing paths", exc_info=True)
        return ()
    if result.returncode not in {0, 1}:
        return ()
    ignored = tuple(
        sorted(
            path.replace("\\", "/")
            for path in result.stdout.decode("utf-8", errors="replace").split("\0")
            if path
        )
    )
    _git_ignore_cache[cache_key] = (now, ignored)
    return ignored


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


def select_modified_context_nodes(
    graph: Graph,
    modified_paths: dict[str, int],
    query: str,
    *,
    exclude: tuple[str, ...] = (),
    limit: int | None = None,
) -> dict[str, int]:
    """Select a compact, query-aware representative set for dirty files.

    A changed file can own dozens of symbol nodes. Treating all of them as
    personalization or traversal seeds spends context budget repeatedly on the
    same file. This chooses at most one representative per path, then grows the
    number of represented paths logarithmically with the dirty set (capped at
    four). The score combines lexical relevance, normalized local degree, and
    change mass; exact query relevance dominates the two topology priors.
    """
    if not modified_paths:
        return {}

    from .text import tokenize

    resolved = resolve_modified_node_ids(graph, modified_paths)
    excluded_paths = {
        graph.nodes[node_id].path.replace("\\", "/")
        for node_id in exclude
        if node_id in graph.nodes and graph.nodes[node_id].path
    }
    query_terms = set(tokenize(query))
    degree = graph.degree()
    max_degree = max((degree.get(node_id, 0) for ids in resolved.values() for node_id in ids), default=1)
    max_changes = max(modified_paths.values(), default=1)
    file_kinds = {
        "file", "python", "typescript", "javascript", "rust", "go", "java",
        "c", "cpp", "header", "csharp", "ruby", "php", "kotlin", "scala", "swift",
    }

    ranked: list[tuple[float, str, str, int]] = []
    for path, change_count in modified_paths.items():
        if path in excluded_paths:
            continue
        candidates = resolved.get(path, ())
        if not candidates:
            continue
        best: tuple[float, str] | None = None
        for node_id in candidates:
            node = graph.nodes[node_id]
            node_terms = set(tokenize(f"{node.label} {node.path}"))
            overlap = len(query_terms & node_terms)
            lexical = overlap / math.sqrt(max(1, len(query_terms) * len(node_terms)))
            structural = math.log1p(degree.get(node_id, 0)) / math.log1p(max(1, max_degree))
            kind_prior = 0.20 if node.kind in file_kinds else 0.05
            score = 4.0 * lexical + 0.65 * structural + kind_prior
            candidate = (score, node_id)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            continue
        change_mass = math.log1p(max(0, change_count)) / math.log1p(max(1, max_changes))
        ranked.append((best[0] + 0.35 * change_mass, path, best[1], change_count))

    if limit is None:
        # One dirty path gets one representative; the budget reaches four only
        # for eight or more paths. This is a bounded coverage prior, not a dump.
        limit = min(4, max(1, math.ceil(math.log2(len(ranked) + 1))))
    selected = sorted(ranked, key=lambda item: (-item[0], item[1], item[2]))[: max(0, limit)]
    return {node_id: change_count for _score, _path, node_id, change_count in selected}
