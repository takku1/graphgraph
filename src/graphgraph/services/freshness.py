"""Saved-graph freshness inspection and refresh receipts."""

from __future__ import annotations

from pathlib import Path

from ..io import project_root_for_graph
from ..retrieval.git_utils import (
    get_git_head_revision,
    get_git_revision_paths,
    get_git_sync_paths,
    get_git_tracked_changed_paths,
)
from ..runtime.manifest import Manifest, compute_file_hash
from .lifecycle import GraphBuildStatus, _worktree_sync_candidate, manifest_path_for_graph


def source_root_for_saved_graph(
    output_path: Path,
    *,
    fallback: Path | None = None,
) -> Path:
    """Return the scan root recorded beside a saved graph, without loading it."""
    manifest = Manifest.load(manifest_path_for_graph(output_path))
    if manifest.source_root:
        return Path(manifest.source_root).resolve()
    return (fallback or project_root_for_graph(output_path)).resolve()


def inspect_saved_graph_freshness(*, directory: Path, output_path: Path) -> dict[str, object]:
    """Read-only manifest check for stale Git candidates in O(changed files)."""
    if directory == Path("."):
        directory = project_root_for_graph(output_path)
    directory = source_root_for_saved_graph(output_path, fallback=directory)
    manifest = Manifest.load(manifest_path_for_graph(output_path))
    current_revision = get_git_head_revision(directory)
    changed, deleted, provenance_compatible = get_git_sync_paths(
        manifest.source_revision,
        directory,
    )
    committed_changed: tuple[str, ...] = ()
    if current_revision is not None and manifest.source_revision != current_revision:
        revision_paths = get_git_revision_paths(manifest.source_revision, directory)
        if revision_paths is not None:
            committed_changed = revision_paths[0]
    # Ignore rules apply to untracked candidates only. A tracked file that is
    # also listed in .gitignore still reports its edits to Git, so filtering
    # it out here left the graph stale while freshness reported clean. The
    # untracked half arrives from `ls-files --exclude-standard`, which Git has
    # already filtered, so only non-Git `.ignore` rules remain to apply.
    tracked = set(get_git_tracked_changed_paths(directory)) | set(committed_changed)
    if changed:
        from ..scanner.files import path_ignored_by_rules

    ignored = {
        path
        for path in changed
        if path not in tracked and path_ignored_by_rules(directory, path)
    }
    stale_changed: list[str] = []
    for rel_path in changed:
        if rel_path in ignored or not _worktree_sync_candidate(rel_path):
            continue
        source_path = directory / rel_path
        info = manifest.get_file_info(rel_path)
        old_hash = str(info.get("hash") or "") if info else ""
        if source_path.is_file() and compute_file_hash(source_path) != old_hash:
            stale_changed.append(rel_path)
    stale_deleted = [
        rel_path for rel_path in deleted if manifest.get_file_info(rel_path) is not None
    ]
    extractor_compatible = manifest.compatible
    return {
        "fresh": (
            not stale_changed
            and not stale_deleted
            and extractor_compatible
            and provenance_compatible
        ),
        "changed_count": len(stale_changed),
        "deleted_count": len(stale_deleted),
        "changed_paths": stale_changed[:20],
        "deleted_paths": stale_deleted[:20],
        "measured_at": manifest.updated_at or "unknown",
        "extractor_compatible": extractor_compatible,
        "provenance_compatible": provenance_compatible,
        "source_revision": manifest.source_revision[:12] or "unknown",
        "current_revision": current_revision[:12] if current_revision else "non-git",
        "extractor_identity": (
            manifest.extractor_fingerprint[:12]
            if manifest.extractor_fingerprint
            else "legacy"
        ),
    }


def scope_freshness(
    freshness: dict[str, object],
    requested_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    """Project repository drift into task-scope and unrelated freshness."""
    requested = {
        path.replace("\\", "/").strip("/")
        for path in requested_paths
        if path
    }
    stale_changed = [
        str(path).replace("\\", "/").strip("/")
        for path in freshness.get("changed_paths", ())
    ]
    stale_deleted = [
        str(path).replace("\\", "/").strip("/")
        for path in freshness.get("deleted_paths", ())
    ]
    stale = set((*stale_changed, *stale_deleted))
    repository_fresh = bool(freshness.get("fresh", not stale))
    enriched = dict(freshness)
    enriched.update({
        "requested_scope_fresh": repository_fresh if not requested else not bool(stale & requested),
        "repository_fresh": repository_fresh,
        "requested_paths": sorted(requested),
        "remaining_stale_count": len(stale),
        "unrelated_changed_count": sum(path not in requested for path in stale_changed),
        "unrelated_deleted_count": sum(path not in requested for path in stale_deleted),
    })
    return enriched


def classify_freshness(freshness: dict[str, object], *, scoped: bool = False) -> str:
    """Collapse a freshness mapping into the tri-state label receipts carry.

    ``scoped`` reads ``requested_scope_fresh`` (drift limited to the caller's
    declared paths) instead of repository-wide ``fresh``.

    Incompatibility is checked first, and that ordering is load-bearing rather
    than stylistic. ``fresh`` already folds in ``extractor_compatible``, so for
    the repository-wide case either order agrees. ``requested_scope_fresh`` does
    not: once a caller passes scopes, it is computed purely from whether the
    stale set intersects those paths. Testing freshness first therefore reported
    a graph built by a *different scanner version* as "fresh" whenever the drift
    happened to fall outside the query's scope -- hiding the one condition that
    a refresh cannot repair and only a rebuild can.
    """
    if (
        not freshness.get("extractor_compatible", True)
        or not freshness.get("provenance_compatible", True)
    ):
        return "incompatible"
    key = "requested_scope_fresh" if scoped else "fresh"
    return "fresh" if freshness.get(key) else "stale"


def refresh_receipt(
    status: GraphBuildStatus,
    *,
    mode: str,
    requested_changed_paths: tuple[str, ...] = (),
    requested_deleted_paths: tuple[str, ...] = (),
    attempted: bool = True,
    milliseconds: float | None = None,
) -> dict[str, object]:
    """Encode refresh inputs, work, and graph writes as distinct receipt fields."""
    requested_changed = list(dict.fromkeys(requested_changed_paths))
    requested_deleted = list(dict.fromkeys(requested_deleted_paths))
    refreshed = list(status.changed_paths) if attempted else []
    removed = list(status.deleted_paths) if attempted else []
    graph_write_performed = bool(attempted and status.built)
    receipt: dict[str, object] = {
        "mode": mode,
        "requested_paths": list(dict.fromkeys((*requested_changed, *requested_deleted))),
        "requested_changed_paths": requested_changed,
        "requested_deleted_paths": requested_deleted,
        "refreshed_paths": refreshed,
        "removed_paths": removed,
        "graph_mutations": {
            "write_performed": graph_write_performed,
            "repaired": bool(graph_write_performed and status.repaired),
            "updated_paths": refreshed if graph_write_performed else [],
            "removed_paths": removed if graph_write_performed else [],
            "updated_path_count": len(refreshed) if graph_write_performed else 0,
            "removed_path_count": len(removed) if graph_write_performed else 0,
        },
        # Compatibility aliases. These are paths processed by the refresh,
        # not a post-refresh freshness result.
        "changed_paths": refreshed,
        "deleted_paths": removed,
        "repaired": bool(graph_write_performed and status.repaired),
    }
    if milliseconds is not None:
        receipt["milliseconds"] = milliseconds
    return receipt


__all__ = [
    "classify_freshness",
    "inspect_saved_graph_freshness",
    "refresh_receipt",
    "scope_freshness",
    "source_root_for_saved_graph",
]
