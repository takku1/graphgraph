from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..graph.core import Graph
from ..io import (
    RemovalMatchedNothing,
    assert_no_catastrophic_shrink,
    find_graph_path,
    load_any,
    project_root_for_graph,
    save_validated_graph,
    validate_graph_file,
)
from ..packets.validation import ValidationResult
from ..retrieval.git_utils import (
    get_git_ignored_paths,
    get_git_worktree_paths,
)
from ..runtime.manifest import Manifest, compute_file_hash
from ..scanner import DEFAULT_SCAN_MAX_NODES, remove_paths, scan_directory, update_paths
from ..scanner.core import _normalize_rels
from ..scanner.files import (
    SKIP_DIRS,
    SKIP_FILE_NAMES,
    SKIP_SUFFIXES,
    path_ignored_by_rules,
)
from ..storage.delta import (
    delta_sidecar_path,
    save_incremental_validated_graph,
)


@dataclass(frozen=True)
class GraphBuildStatus:
    path: Path
    graph: Graph
    built: bool
    repaired: bool = False
    validation: ValidationResult | None = None
    changed_paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()


def manifest_path_for_graph(output_path: Path) -> Path:
    """Bind incremental state to one graph artifact, never a shared directory."""
    return output_path.with_name(f"{output_path.name}.manifest.json")


def _commit_deferred_manifests(sink: list) -> None:
    """Write the manifests the scanner deferred, once the graph is committed.

    The scanner captures ``(manifest, path)`` pairs into a sink instead of
    writing them mid-scan; committing them only after the graph is durably saved
    keeps the manifest from ever describing nodes a failed graph write dropped.
    """
    for manifest, path in sink:
        manifest.save(path)


def _worktree_sync_candidate(rel_path: str) -> bool:
    path = Path(rel_path)
    lower_name = path.name.lower()
    if lower_name in SKIP_FILE_NAMES or lower_name == ".env" or lower_name.startswith(".env."):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return not any(
        part in SKIP_DIRS or part.startswith("target") or part.endswith(".egg-info")
        for part in path.parts[:-1]
    )


def _all_paths_outside_tree(directory: Path, paths: list[str]) -> bool:
    """True only if every requested path resolves outside *directory*.

    The wrong-root signature: the graph lives elsewhere, `--directory` defaults
    to a cwd that is not the scanned repo, and the paths (typically absolute,
    pointing into the real repo) fall outside it. An in-tree path that is merely
    absent from the graph -- excluded, a typo, already deleted -- resolves under
    the tree and is a legitimate idempotent no-op, not a mistake. Purely
    lexical: existence on disk is irrelevant, and a path that cannot be resolved
    is treated as outside.
    """
    root = directory.resolve()
    for raw in paths:
        candidate = Path(raw)
        try:
            resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        except (OSError, ValueError):
            continue
        if resolved.is_relative_to(root):
            return False
    return True


def scan_validated_graph(
    *,
    directory: Path,
    output_path: Path,
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    generic_mentions: bool = False,
    incremental: bool = True,
    force: bool = False,
    progress: Callable[[str, str], None] | None = None,
) -> GraphBuildStatus:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    use_incremental = incremental
    previous_graph_path = output_path if use_incremental else None
    # A clean scan must also replace the manifest. Leaving it untouched made
    # the next targeted update resurrect edges from an older extraction
    # policy even though the graph itself had just been rebuilt.
    manifest_path = manifest_path_for_graph(output_path)

    manifest_sink: list = []
    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=list(skip_dirs),
        include=list(include_dirs),
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=previous_graph_path,
        manifest_path=manifest_path,
        exclude_paths=[output_path, manifest_path, delta_sidecar_path(output_path)],
        progress=progress,
        manifest_sink=manifest_sink,
    )
    try:
        if progress is not None:
            progress("validate", f"path={output_path}")
        # `scan` is the most reachable destructive path, not the least: agent
        # instructions tell tools to run it on sight, and it takes the same
        # wrong-root confusion that broke `update` -- scanning an empty or
        # unrelated directory over a valid graph wrote 0 nodes at exit 0.
        assert_no_catastrophic_shrink(graph, output_path, force=force)
        validation = save_validated_graph(graph, output_path)
        _commit_deferred_manifests(manifest_sink)
        if progress is not None:
            progress("saved", f"path={output_path} bytes={output_path.stat().st_size}")
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        if not incremental:
            raise
        if progress is not None:
            progress("repair", "incremental result invalid; retrying clean scan")

    repair_sink: list = []
    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=list(skip_dirs),
        include=list(include_dirs),
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=None,
        manifest_path=manifest_path_for_graph(output_path),
        exclude_paths=[
            output_path,
            manifest_path_for_graph(output_path),
            delta_sidecar_path(output_path),
        ],
        progress=progress,
        manifest_sink=repair_sink,
    )
    if progress is not None:
        progress("validate", f"path={output_path} clean_rebuild=true")
    assert_no_catastrophic_shrink(graph, output_path, force=force)
    validation = save_validated_graph(graph, output_path)
    _commit_deferred_manifests(repair_sink)
    if progress is not None:
        progress("saved", f"path={output_path} bytes={output_path.stat().st_size}")
    return GraphBuildStatus(output_path, graph, built=True, repaired=True, validation=validation)


def _full_rescan_fallback(
    *,
    directory: Path,
    output_path: Path,
    max_nodes: int,
    depth: str,
    frontend: str,
    docs: bool,
    history: bool,
    force: bool = False,
) -> GraphBuildStatus:
    """Repair path shared by update/remove: promote to a clean full rebuild.

    Mirrors ``scan_validated_graph``'s own incremental-then-repair fallback --
    if the targeted operation produced an invalid graph (e.g. the manifest
    was stale relative to disk), a full non-incremental scan is the safety
    net, same as it is for the ordinary incremental scan path.

    The rebuild scans *directory*, which the CLI defaults to cwd. When the
    graph lives outside the scanned repo that root is wrong, and this "repair"
    quietly replaced a valid graph with an empty one. The shrink guard below
    is what makes the repair safe to attempt.
    """
    fallback_sink: list = []
    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=None,
        manifest_path=manifest_path_for_graph(output_path),
        exclude_paths=[
            output_path,
            manifest_path_for_graph(output_path),
            delta_sidecar_path(output_path),
        ],
        manifest_sink=fallback_sink,
    )
    assert_no_catastrophic_shrink(graph, output_path, force=force)
    validation = save_validated_graph(graph, output_path)
    _commit_deferred_manifests(fallback_sink)
    return GraphBuildStatus(output_path, graph, built=True, repaired=True, validation=validation)


def update_paths_validated_graph(
    *,
    directory: Path,
    output_path: Path,
    paths: list[str],
    deleted_paths: list[str] | None = None,
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    force: bool = False,
) -> GraphBuildStatus:
    """Re-extract *paths* and remove *deleted_paths* in one graph splice.

    Requires a prior ``scan_validated_graph``/``graphgraph scan`` run (needs
    an existing graph + manifest at *output_path*). Falls back to a full
    rebuild if that's missing or the result fails validation.
    """
    manifest_path = manifest_path_for_graph(output_path)
    owned_artifacts = _normalize_rels(
        directory.resolve(),
        [output_path, manifest_path, delta_sidecar_path(output_path)],
    )
    update_candidates = [
        path for path in paths
        if _normalize_rels(directory.resolve(), [path]).isdisjoint(owned_artifacts)
    ]
    authoritative_deletions = list(dict.fromkeys([*(deleted_paths or ()), *owned_artifacts]))
    try:
        previous_graph = load_any(output_path)
        update_sink: list = []
        graph = update_paths(
            directory,
            update_candidates,
            deleted_paths=authoritative_deletions,
            max_nodes=max_nodes,
            depth=depth,
            frontend=frontend,
            docs=docs,
            history=history,
            previous_graph_path=output_path,
            manifest_path=manifest_path,
            manifest_sink=update_sink,
        )
        assert_no_catastrophic_shrink(graph, output_path, force=force)
        validation = save_incremental_validated_graph(
            previous_graph,
            graph,
            output_path,
        )
        _commit_deferred_manifests(update_sink)
        return GraphBuildStatus(
            output_path,
            graph,
            built=True,
            repaired=False,
            validation=validation,
            changed_paths=tuple(paths),
            deleted_paths=tuple(deleted_paths or ()),
        )
    except ValueError:
        status = _full_rescan_fallback(
            directory=directory, output_path=output_path, max_nodes=max_nodes,
            depth=depth, frontend=frontend, docs=docs, history=history,
            force=force,
        )
        return GraphBuildStatus(
            status.path,
            status.graph,
            status.built,
            status.repaired,
            status.validation,
            tuple(paths),
            tuple(deleted_paths or ()),
        )


def refresh_saved_graph(
    *,
    directory: Path,
    output_path: Path,
    changed_paths: list[str] | None = None,
    deleted_paths: list[str] | None = None,
    sync_git: bool = False,
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    depth: str | None = None,
    frontend: str | None = None,
    docs: bool | None = None,
    history: bool | None = None,
) -> GraphBuildStatus:
    """Refresh a saved graph from explicit and/or stale Git worktree paths.

    Git supplies only candidate paths. Manifest hashes then remove candidates
    already represented by the graph, making repeated sync calls idempotent
    without a repository walk.
    """
    if directory == Path("."):
        directory = project_root_for_graph(output_path)
    directory = directory.resolve()
    current_graph = load_any(output_path)
    changed = list(dict.fromkeys(changed_paths or ()))
    deleted = list(dict.fromkeys(deleted_paths or ()))

    if sync_git:
        git_changed, git_deleted = get_git_worktree_paths(directory)
        manifest = Manifest.load(manifest_path_for_graph(output_path))
        default_excluded = {
            rel_path for rel_path in manifest.files if not _worktree_sync_candidate(rel_path)
        }
        deleted.extend(default_excluded)
        # A graph can predate its current ignore rules (for example, a local
        # investigation directory was indexed and later added to .gitignore).
        # One batched git check over manifest paths reconciles that state
        # without reading or hashing the repository's files.
        deleted.extend(get_git_ignored_paths(tuple(manifest.files), directory))
        deleted.extend(path for path in manifest.files if path_ignored_by_rules(directory, path))
        ignored_candidates = set(get_git_ignored_paths(git_changed, directory))
        ignored_candidates.update(path for path in git_changed if path_ignored_by_rules(directory, path))
        for rel_path in git_changed:
            if rel_path in ignored_candidates or not _worktree_sync_candidate(rel_path):
                continue
            source_path = directory / rel_path
            info = manifest.get_file_info(rel_path)
            old_hash = str(info.get("hash") or "") if info else ""
            if source_path.is_file() and compute_file_hash(source_path) != old_hash:
                changed.append(rel_path)
        for rel_path in git_deleted:
            if manifest.get_file_info(rel_path) is not None:
                deleted.append(rel_path)

    changed = list(dict.fromkeys(path for path in changed if path not in deleted))
    deleted = list(dict.fromkeys(deleted))
    if not changed and not deleted:
        return GraphBuildStatus(output_path, current_graph, built=False)

    metadata = current_graph.metadata
    resolved_depth = depth or str(metadata.get("scan_depth") or "symbols")
    resolved_frontend = frontend or str(metadata.get("frontend") or "auto")
    if resolved_frontend not in {"auto", "regex", "tree_sitter"}:
        resolved_frontend = "auto"
    resolved_docs = docs if docs is not None else metadata.get("docs") == "true"
    resolved_history = history if history is not None else metadata.get("history") == "true"
    return update_paths_validated_graph(
        directory=directory,
        output_path=output_path,
        paths=changed,
        deleted_paths=deleted,
        max_nodes=max_nodes,
        depth=resolved_depth,
        frontend=resolved_frontend,
        docs=resolved_docs,
        history=resolved_history,
    )


def remove_paths_validated_graph(
    *,
    directory: Path,
    output_path: Path,
    paths: list[str],
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    force: bool = False,
) -> GraphBuildStatus:
    """Drop *paths* (deleted/renamed-away files) from the existing graph.

    Requires a prior ``scan_validated_graph``/``graphgraph scan`` run. Falls
    back to a full rebuild if that's missing or the result fails validation.
    """
    manifest_path = manifest_path_for_graph(output_path)
    previous_graph = None
    prior_nodes = None
    if output_path.exists():
        try:
            previous_graph = load_any(output_path)
            prior_nodes = len(previous_graph.nodes)
        except Exception:  # noqa: BLE001 - a corrupt prior graph is handled below
            prior_nodes = None
    try:
        remove_sink: list = []
        graph = remove_paths(
            directory,
            paths,
            max_nodes=max_nodes,
            depth=depth,
            frontend=frontend,
            docs=docs,
            history=history,
            previous_graph_path=output_path,
            manifest_path=manifest_path,
            manifest_sink=remove_sink,
        )
        # Ordering matters: check destruction before no-op. A wrong-root remove
        # can either match nothing (no-op) or match everything (destruction),
        # and the second is the dangerous one.
        assert_no_catastrophic_shrink(graph, output_path, force=force)
        # A removal that changed nothing is only an *error* when the requested
        # paths all resolve outside the scanned tree -- the wrong-root mistake,
        # where `remove` used to report "Removed N file(s)" at exit 0 while the
        # graph kept serving files already gone from disk. An in-tree path that
        # simply is not in the graph (excluded, typo, or already dropped) is a
        # legitimate idempotent no-op, and erroring on it broke batch cleanups
        # that included one untracked path. Distinguish the two by location.
        if (
            prior_nodes is not None
            and paths
            and len(graph.nodes) == prior_nodes
            and _all_paths_outside_tree(directory, paths)
        ):
            raise RemovalMatchedNothing(
                f"Removed nothing from {output_path}: none of the {len(paths)} requested "
                f"path(s) matched a file the graph knows about (graph still has "
                f"{prior_nodes} nodes). This usually means --directory does not point "
                "at the repo the graph was scanned from, so the paths resolved outside "
                "it. Re-run with --directory set to the scanned repo."
            )
        validation = save_incremental_validated_graph(
            previous_graph if previous_graph is not None else Graph(),
            graph,
            output_path,
        )
        _commit_deferred_manifests(remove_sink)
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        return _full_rescan_fallback(
            directory=directory, output_path=output_path, max_nodes=max_nodes,
            depth=depth, frontend=frontend, docs=docs, history=history,
            force=force,
        )


def ensure_native_graph(
    *,
    directory: Path = Path("."),
    output_path: Path = Path(".graphgraph/graph.gg"),
    rebuild: bool = False,
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    generic_mentions: bool = False,
    incremental: bool = True,
    discover_existing: bool = True,
) -> GraphBuildStatus:
    """Return an existing native graph, or scan one with production defaults."""
    if not rebuild:
        graph_path = output_path
        try:
            if not graph_path.exists() and discover_existing:
                graph_path = find_graph_path()
            validation = validate_graph_file(graph_path)
            if validation.ok:
                return GraphBuildStatus(graph_path, load_any(graph_path), built=False)
        except FileNotFoundError:
            pass

    return scan_validated_graph(
        directory=directory,
        output_path=output_path,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=skip_dirs,
        include_dirs=include_dirs,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        incremental=incremental and not rebuild,
    )


