from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..concepts import (
    INTERPRETATION_CONCEPT_IDS,
    SOURCE_CONCEPT_RELATIONS,
    link_source_interpretation_concepts,
)
from ..concepts.terms import term_key
from ..graph.core import Edge, Graph, Node
from .doc import DocumentInput, extract_document_context
from .files import (
    DEFAULT_SCAN_MAX_NODES,
    DOC_SUFFIXES,
    EXT_KIND,
    SOURCE_SUFFIXES,
    collect_files,
    node_id,
)
from .frontends import SourceFile, select_extractor
from .frontends.persistent_facts import (
    AffectedTypeFactFiles,
    PersistentPythonTypeIndex,
    PythonProjectTypeFacts,
    python_file_type_snapshot,
)
from .history import extract_commit_history, repository_history_start
from .imports import add_file_edges
from .rust_references import filter_rust_reference_edges

logger = logging.getLogger(__name__)
ScanProgress = Callable[[str, str], None]
_MEMBER_CALL_TELEMETRY_VERSION = "2"
_MEMBER_CALL_TELEMETRY_FIELDS = (
    "resolved",
    "ambiguous",
    "unknown_receiver",
    "unresolved",
    "external_resolved",
    "unmatched",
)


def _emit_progress(progress: ScanProgress | None, phase: str, detail: str) -> None:
    if progress is not None:
        progress(phase, detail)


def _get_git_metadata(root: Path) -> tuple[set[str], dict[str, int]]:
    dirty_files: set[str] = set()
    churn_counts: dict[str, int] = {}
    try:
        # `-z` disables git's core.quotepath escaping (which otherwise wraps
        # any path containing a space or non-ASCII byte in double quotes with
        # C-style/octal escapes, e.g. "caf\303\251.py" for "café.py") and
        # NUL-terminates each field instead. Parsing the quoted/escaped text
        # form directly (the previous approach) left the literal quote
        # characters and escape sequences in the path, so such files never
        # matched their real on-disk relative path and were silently dropped.
        res_status = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False
        )
        if res_status.returncode == 0:
            tokens = res_status.stdout.split("\0")
            i = 0
            while i < len(tokens):
                entry = tokens[i]
                i += 1
                if len(entry) > 3:
                    status_code = entry[:2]
                    rel_path = Path(entry[3:]).as_posix()
                    dirty_files.add(rel_path)
                    if "R" in status_code or "C" in status_code:
                        # Renamed/copied entries are followed by an extra
                        # NUL-terminated token holding the original path.
                        i += 1

        res_log = subprocess.run(
            ["git", "log", "-n", "100", "--name-only", "--format="],
            cwd=root,
            capture_output=True,
            text=True,
            check=False
        )
        if res_log.returncode == 0:
            for line in res_log.stdout.splitlines():
                line = line.strip()
                if line:
                    rel_path = Path(line).as_posix()
                    churn_counts[rel_path] = churn_counts.get(rel_path, 0) + 1
    except Exception:
        logger.debug("git metadata lookup failed; scan priority/churn signals disabled", exc_info=True)
    return dirty_files, churn_counts


def _load_manifest_and_graph(
    manifest_path: Path | None,
    previous_graph_path: Path | None,
    previous_graph: Graph | None = None,
):
    from ..io import load_any
    from ..runtime.manifest import Manifest

    manifest = Manifest.load(manifest_path) if manifest_path else None
    if previous_graph is None and previous_graph_path and previous_graph_path.exists():
        try:
            previous_graph = load_any(previous_graph_path)
        except Exception:
            previous_graph = None
    return manifest, previous_graph


# ── main entry point ─────────────────────────────────────────────────────────

def scan_directory(
    root: Path,
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    generic_mentions: bool = False,
    skip_dirs: list[str] | None = None,
    depth: str = "files",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    max_history_commits: int = 300,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
    include: list[str] | None = None,
    exclude_paths: list[str] | list[Path] | None = None,
    progress: ScanProgress | None = None,
    manifest_sink: list | None = None,
) -> Graph:
    """Scan *root* and build a Graph of file-level (and optionally symbol-level) nodes.

    Handles: Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby,
             Markdown links, RST includes, HTML hrefs.

    This is the full-discovery path: it walks the whole tree and hashes every
    file to figure out what changed. For an agent loop that already knows
    exactly which files it just edited, ``update_paths``/``remove_paths``
    below skip that discovery entirely and are much cheaper on large repos.
    """
    root = root.resolve()
    extra_skip = frozenset(skip_dirs) if skip_dirs else frozenset()
    include_set = frozenset(include) if include else frozenset()
    excluded_rels = frozenset(_normalize_rels(root, exclude_paths or []))

    _emit_progress(progress, "discover", f"root={root}")
    # Gather git metadata early so staged files get scan priority.
    dirty_git, churn_git = _get_git_metadata(root)

    collected = collect_files(
        root,
        max_nodes,
        extra_skip,
        git_staged=dirty_git,
        include=include_set,
        exclude_paths=excluded_rels,
    )
    files = collected.files
    _emit_progress(
        progress,
        "discover",
        f"selected={len(files)} matched={collected.total_matched} "
        f"ignore_files={len(collected.ignore_files)} ignored_files={collected.ignored_by_rules} "
        f"ignored_dirs={len(collected.rule_pruned_dirs)} default_pruned_dirs={len(collected.default_pruned_dirs)}",
    )

    file_map: dict[str, str] = {}   # rel_posix -> node_id
    for f in files:
        rel = f.relative_to(root).as_posix()
        nid = node_id(f, root)
        file_map[rel] = nid

    manifest, previous_graph = _load_manifest_and_graph(manifest_path, previous_graph_path)
    if manifest is not None and not manifest.compatible:
        # Extraction semantics are part of the manifest contract. Reusing
        # unchanged files from an older manifest would preserve stale node
        # shapes (for example, one node for an entire Markdown table) after an
        # extractor upgrade. A normal full scan therefore starts a compatible
        # empty manifest and rebuilds every file.
        from ..runtime.manifest import Manifest
        manifest = Manifest()
        previous_graph = None
    from ..runtime.manifest import compute_file_hash

    skipped_files: list[tuple[Path, str, str]] = []
    dirty_files: list[tuple[Path, str, str]] = []

    _emit_progress(progress, "hash", f"files={len(files)} incremental={bool(manifest and previous_graph)}")
    if manifest and previous_graph:
        for f in files:
            rel = f.relative_to(root).as_posix()
            info = manifest.get_file_info(rel)
            current_hash = compute_file_hash(f)
            if (info and info.get("hash") == current_hash and
                info.get("depth") == depth and
                info.get("frontend") == frontend and
                info.get("docs") == docs):
                skipped_files.append((f, rel, current_hash))
            else:
                dirty_files.append((f, rel, current_hash))
    else:
        for f in files:
            rel = f.relative_to(root).as_posix()
            current_hash = compute_file_hash(f)
            dirty_files.append((f, rel, current_hash))

    active_rels = {f.relative_to(root).as_posix() for f in files}

    # Files that vanished since the last scan take their nodes with them, so
    # anything still referencing them must be re-extracted rather than
    # restored verbatim -- otherwise a rename drops callers that a clean
    # rebuild keeps (GG10-LC-008).
    if manifest and previous_graph:
        removed_rels = set(manifest.files.keys()) - active_rels
        rebind_rels = _referrer_rels(root, previous_graph, removed_rels)
        if rebind_rels:
            promoted = [entry for entry in skipped_files if entry[1] in rebind_rels]
            if promoted:
                skipped_files = [entry for entry in skipped_files if entry[1] not in rebind_rels]
                dirty_files.extend(promoted)

    (
        dirty_files,
        skipped_files,
        python_fact_snapshots,
        type_fact_update,
        python_type_context,
        type_index_data,
    ) = _promote_type_fact_dependents(
        root,
        manifest,
        dirty_files,
        skipped_files,
        active_rels,
        enabled=depth == "symbols",
    )
    _emit_progress(progress, "hash", f"dirty={len(dirty_files)} restored={len(skipped_files)}")

    # Git status is gathered before collection for priority ordering, but only
    # paths admitted by the same scan/ignore policy may enter graph metadata.
    # Otherwise an ignored dirty packet dump leaks into the serialized graph
    # even though it correctly has no node.
    dirty_git.intersection_update(active_rels)
    churn_git = {rel: count for rel, count in churn_git.items() if rel in active_rels}

    return _build_graph_from_split(
        root=root,
        file_map=file_map,
        dirty_files=dirty_files,
        skipped_files=skipped_files,
        active_rels=active_rels,
        dirty_git=dirty_git,
        churn_git=churn_git,
        manifest=manifest,
        previous_graph=previous_graph,
        manifest_path=manifest_path,
        manifest_sink=manifest_sink,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        max_history_commits=max_history_commits,
        files_truncated=collected.truncated,
        files_total_matched=collected.total_matched,
        ignore_files=collected.ignore_files,
        ignored_by_rules=collected.ignored_by_rules,
        rule_pruned_dirs=collected.rule_pruned_dirs,
        default_pruned_dirs=collected.default_pruned_dirs,
        python_fact_snapshots=python_fact_snapshots,
        type_fact_update=type_fact_update,
        python_type_context=python_type_context,
        type_index_data=type_index_data,
        progress=progress,
    )


def _normalize_rels(root: Path, paths: list[str] | list[Path]) -> set[str]:
    rels: set[str] = set()
    for p in paths:
        p = Path(p)
        p = p if p.is_absolute() else (root / p)
        try:
            rel = p.resolve().relative_to(root).as_posix()
        except ValueError:
            # Not under root; fall back to treating it as already-relative.
            rel = Path(p).as_posix()
        rels.add(rel)
    return rels


def _node_rel(node) -> str:
    """Repo-relative posix path a node belongs to, or "" when it has none.

    Matches the form produced by :func:`_normalize_rels` so node ownership
    and caller-supplied paths compare directly.
    """
    path = getattr(node, "path", "") or ""
    return Path(path).as_posix() if path else ""


def _referrer_rels(root: Path, previous_graph, removed_rels: set[str]) -> set[str]:
    """Files that must be re-extracted because *removed_rels* disappeared.

    A file whose edges point into a removed file cannot be restored verbatim
    from the manifest: its edges reference nodes that no longer exist, so the
    reference dies with them instead of rebinding to wherever the definition
    moved. Renaming a file would then silently drop callers that a clean
    rebuild keeps (GG10-LC-008).

    Returns only rels that still exist on disk and are not themselves removed.
    """
    if not removed_rels or previous_graph is None:
        return set()
    removed_node_ids = {
        nid
        for nid, node in previous_graph.nodes.items()
        if _node_rel(node) in removed_rels
    }
    if not removed_node_ids:
        return set()
    referrer_ids: set[str] = set()
    for edge in previous_graph.edges:
        if edge.target in removed_node_ids:
            referrer_ids.add(edge.source)
        elif edge.source in removed_node_ids:
            referrer_ids.add(edge.target)
    return {
        rel
        for nid in referrer_ids
        if (node := previous_graph.nodes.get(nid)) is not None
        and (rel := _node_rel(node))
        and rel not in removed_rels
        and (root / rel).exists()
    }


def _manifest_type_fact_snapshots(
    manifest,
    rels: set[str],
) -> dict[str, dict]:
    if manifest is None:
        return {}
    result: dict[str, dict] = {}
    for rel in rels:
        info = manifest.get_file_info(rel)
        snapshot = info.get("type_facts", {}) if info else {}
        if isinstance(snapshot, dict) and snapshot:
            result[rel] = snapshot
    return result


def _effective_update_rels(
    root: Path,
    manifest,
    existing_rels: set[str],
    removed_rels: set[str],
    *,
    depth: str,
    frontend: str,
    docs: bool,
) -> tuple[set[str], set[str]]:
    """Partition requested paths into content/config changes and removals.

    A manifest is an admissible oracle only when it is bound to this source
    root. With that precondition, the partition is a set operation over tracked
    paths plus one hash/config equality check per existing candidate. Without
    it, retain every request so the normal repair and shrink guards decide.
    """
    from ..runtime.manifest import compute_file_hash

    try:
        manifest_root_matches = bool(manifest.source_root) and Path(
            manifest.source_root
        ).resolve() == root
    except (OSError, ValueError):
        manifest_root_matches = False
    if not manifest_root_matches:
        return set(existing_rels), set(removed_rels)

    changed = {
        rel
        for rel in existing_rels
        if (
            (info := manifest.get_file_info(rel)) is None
            or info.get("hash") != compute_file_hash(root / rel)
            or info.get("depth") != depth
            or info.get("frontend") != frontend
            or info.get("docs") != docs
        )
    }
    return changed, removed_rels.intersection(manifest.files)


def _promote_type_fact_dependents(
    root: Path,
    manifest,
    dirty_files: list[tuple[Path, str, str]],
    skipped_files: list[tuple[Path, str, str]],
    active_rels: set[str],
    *,
    enabled: bool,
) -> tuple[
    list[tuple[Path, str, str]],
    list[tuple[Path, str, str]],
    dict[str, dict],
    AffectedTypeFactFiles,
    PythonProjectTypeFacts,
    dict,
]:
    """Promote unchanged consumers selected by the project fact delta.

    Work is one parse per explicitly dirty Python file, a finite join over the
    forward-reachable re-export delta, then reverse-index membership over
    obligations.
    No unchanged source file is opened merely to decide whether it is affected.
    """
    if not enabled:
        return (
            dirty_files,
            skipped_files,
            {},
            AffectedTypeFactFiles(),
            PythonProjectTypeFacts({}, {}, {}),
            {},
        )
    dirty_rels = {rel for _path, rel, _hash in dirty_files}
    manifest_rels = set(manifest.files) if manifest is not None else set()
    removed_rels = manifest_rels - active_rels
    changed_rels = dirty_rels | removed_rels
    old_snapshots = _manifest_type_fact_snapshots(manifest, changed_rels)
    new_snapshots: dict[str, dict] = {}
    for path, rel, _file_hash in dirty_files:
        if path.suffix.casefold() != ".py":
            new_snapshots.pop(rel, None)
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
        new_snapshots[rel] = python_file_type_snapshot(source, rel)

    index_data = getattr(manifest, "type_index", {}) if manifest is not None else {}
    index = PersistentPythonTypeIndex.from_data(index_data)
    if (
        manifest_rels
        and (
            not isinstance(index_data, dict)
            or "project" not in index_data
        )
    ):
        index = PersistentPythonTypeIndex.from_snapshots(
            _manifest_type_fact_snapshots(manifest, manifest_rels)
        )
    changed_keys = index.update(
        old_snapshots,
        new_snapshots,
        changed_rels,
    )
    affected = index.affected_files(
        changed_keys,
        excluded_files=changed_rels,
    )
    if affected.files:
        promoted = [entry for entry in skipped_files if entry[1] in affected.files]
        promoted_rels = {entry[1] for entry in promoted}
        if promoted:
            dirty_files = [*dirty_files, *promoted]
            skipped_files = [
                entry for entry in skipped_files if entry[1] not in promoted_rels
            ]
    selected_snapshots = {
        **new_snapshots,
        **_manifest_type_fact_snapshots(manifest, set(affected.files)),
    }
    context = index.context_for_files(
        selected_snapshots,
        dirty_rels | set(affected.files),
    )
    return (
        dirty_files,
        skipped_files,
        selected_snapshots,
        affected,
        context,
        index.to_data(),
    )


def update_paths(
    root: Path,
    paths: list[str],
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    generic_mentions: bool = False,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    max_history_commits: int = 300,
    previous_graph_path: Path | None = None,
    previous_graph: Graph | None = None,
    manifest_path: Path | None = None,
    deleted_paths: list[str] | None = None,
    manifest_sink: list | None = None,
) -> Graph:
    """Re-extract exactly *paths* and splice the result into the existing graph.

    Unlike ``scan_directory``, this never walks the directory tree or hashes
    any file the caller didn't name -- every other previously-tracked file is
    trusted as unchanged and restored verbatim from the manifest + previous
    graph. This is the primitive an edit/test/measure loop should call after
    touching a known set of files: cost is proportional to ``len(paths)``,
    not to repo size.

    Requires an existing manifest and graph (run ``scan_directory`` once
    first). A changed path that no longer exists on disk is treated as a
    removal. ``deleted_paths`` are removed authoritatively even if a stale
    copy still exists on disk, allowing changed and deleted files to be
    applied in one graph splice.
    """
    root = root.resolve()
    if not manifest_path or not previous_graph_path:
        raise ValueError("update_paths requires manifest_path and previous_graph_path from a prior scan")
    manifest, previous_graph = _load_manifest_and_graph(
        manifest_path,
        previous_graph_path,
        previous_graph,
    )
    if manifest is None or not manifest.compatible or previous_graph is None:
        raise ValueError(
            f"no existing graph/manifest at {previous_graph_path} -- run scan_directory once before update_paths"
        )

    changed_target_rels = _normalize_rels(root, paths)
    explicit_removed_rels = _normalize_rels(root, deleted_paths or [])
    existing_target_rels = {
        rel
        for rel in changed_target_rels - explicit_removed_rels
        if (root / rel).exists()
    }
    removed_target_rels = explicit_removed_rels | (changed_target_rels - existing_target_rels)

    # Exact-path refreshes are assertions that these paths *may* have changed,
    # not instructions to re-extract identical bytes. Re-running a file through
    # only the incremental context can be both expensive and semantically lossy
    # when a global extraction pass supplied evidence the targeted pass cannot
    # reconstruct. The manifest already contains the content/configuration
    # identity needed to reject that work exactly.
    effective_changed_rels, effective_removed_rels = _effective_update_rels(
        root,
        manifest,
        existing_target_rels,
        removed_target_rels,
        depth=depth,
        frontend=frontend,
        docs=docs,
    )

    # History is graph-global rather than file-owned. Do not classify an
    # otherwise identical request as a no-op when it asks for a different
    # history projection.
    graph_options_unchanged = (
        previous_graph.metadata.get("history") == str(bool(history)).lower()
        and previous_graph.metadata.get("generic_mentions")
        == str(bool(generic_mentions)).lower()
        and previous_graph.metadata.get("scan_max_nodes") == str(max_nodes)
    )
    if not effective_changed_rels and not effective_removed_rels and graph_options_unchanged:
        return previous_graph

    existing_target_rels = effective_changed_rels
    removed_target_rels = effective_removed_rels

    existing_target_rels |= _referrer_rels(root, previous_graph, removed_target_rels)

    known_rels = (set(manifest.files.keys()) | existing_target_rels) - removed_target_rels
    active_rels = known_rels

    from ..runtime.manifest import compute_file_hash

    dirty_files: list[tuple[Path, str, str]] = []
    for rel in existing_target_rels:
        f = root / rel
        dirty_files.append((f, rel, compute_file_hash(f)))

    skipped_files: list[tuple[Path, str, str]] = []
    for rel in active_rels - existing_target_rels:
        info = manifest.get_file_info(rel)
        file_hash = info.get("hash", "") if info else ""
        skipped_files.append((root / rel, rel, file_hash))

    (
        dirty_files,
        skipped_files,
        python_fact_snapshots,
        type_fact_update,
        python_type_context,
        type_index_data,
    ) = _promote_type_fact_dependents(
        root,
        manifest,
        dirty_files,
        skipped_files,
        active_rels,
        enabled=depth == "symbols",
    )
    file_map = {rel: node_id(root / rel, root) for rel in active_rels}
    dirty_git, churn_git = _get_git_metadata(root)

    return _build_graph_from_split(
        root=root,
        file_map=file_map,
        dirty_files=dirty_files,
        skipped_files=skipped_files,
        active_rels=active_rels,
        dirty_git=dirty_git,
        churn_git=churn_git,
        manifest=manifest,
        previous_graph=previous_graph,
        manifest_path=manifest_path,
        manifest_sink=manifest_sink,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        max_history_commits=max_history_commits,
        scope_concepts_to_dirty=True,
        python_fact_snapshots=python_fact_snapshots,
        type_fact_update=type_fact_update,
        python_type_context=python_type_context,
        type_index_data=type_index_data,
    )


def remove_paths(
    root: Path,
    paths: list[str],
    max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    generic_mentions: bool = False,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    max_history_commits: int = 300,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
    manifest_sink: list | None = None,
) -> Graph:
    """Drop *paths* (deleted/renamed-away files) from the graph, no re-extraction.

    Every node/edge owned by *paths* is dropped; everything else is restored
    verbatim from the manifest + previous graph. No directory walk, no
    hashing, no symbol extraction -- this is pure removal.
    """
    root = root.resolve()
    if not manifest_path or not previous_graph_path:
        raise ValueError("remove_paths requires manifest_path and previous_graph_path from a prior scan")
    manifest, previous_graph = _load_manifest_and_graph(manifest_path, previous_graph_path)
    if manifest is None or not manifest.compatible or previous_graph is None:
        raise ValueError(
            f"no existing graph/manifest at {previous_graph_path} -- run scan_directory once before remove_paths"
        )

    target_rels = _normalize_rels(root, paths)
    active_rels = set(manifest.files.keys()) - target_rels

    skipped_files: list[tuple[Path, str, str]] = []
    for rel in active_rels:
        info = manifest.get_file_info(rel)
        file_hash = info.get("hash", "") if info else ""
        skipped_files.append((root / rel, rel, file_hash))

    (
        dirty_files,
        skipped_files,
        python_fact_snapshots,
        type_fact_update,
        python_type_context,
        type_index_data,
    ) = _promote_type_fact_dependents(
        root,
        manifest,
        [],
        skipped_files,
        active_rels,
        enabled=depth == "symbols",
    )
    file_map = {rel: node_id(root / rel, root) for rel in active_rels}

    return _build_graph_from_split(
        root=root,
        file_map=file_map,
        dirty_files=dirty_files,
        skipped_files=skipped_files,
        active_rels=active_rels,
        dirty_git=set(),
        churn_git={},
        manifest=manifest,
        previous_graph=previous_graph,
        manifest_path=manifest_path,
        manifest_sink=manifest_sink,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        max_history_commits=max_history_commits,
        scope_concepts_to_dirty=True,
        python_fact_snapshots=python_fact_snapshots,
        type_fact_update=type_fact_update,
        python_type_context=python_type_context,
        type_index_data=type_index_data,
    )


def _merge_new_edges(edges: list[Edge], new_edges: list[Edge]) -> None:
    """Append edges whose (source, target, type) is not already present.

    Several extraction stages (symbols, docs, history, concepts) each produce a
    batch of edges that must be unioned into the running list without creating
    duplicate relations. This is that de-duplicating merge, factored out of the
    four identical inline copies so the dedup key lives in exactly one place.
    """
    existing = {(e.source, e.target, e.type) for e in edges}
    for edge in new_edges:
        key = (edge.source, edge.target, edge.type)
        if key not in existing:
            existing.add(key)
            edges.append(edge)


def _symbol_extraction_metadata(
    extraction,
    *,
    scope_concepts_to_dirty: bool,
    dirty_count: int,
    active_count: int,
) -> dict[str, str]:
    """Build the member-call + frontend-diagnostics metadata for one extraction.

    Pure function of the extraction result (plus the scope inputs that decide
    whether this is a full-scan snapshot): it computes strings only and touches
    no nodes or edges, so it is lifted verbatim out of the pipeline body. The
    caller ``metadata.update()``s the result, preserving insertion order.
    """
    meta: dict[str, str] = {}
    meta["frontend"] = extraction.frontend
    meta["member_calls_resolved"] = str(extraction.resolved_member_calls)
    meta["member_calls_ambiguous"] = str(extraction.ambiguous_member_calls)
    meta["member_calls_unknown_receiver"] = str(extraction.unknown_receiver_member_calls)
    meta["member_calls_unresolved"] = str(extraction.unresolved_member_calls)
    meta["member_calls_external_resolved"] = str(extraction.external_resolved_member_calls)
    meta["member_calls_unmatched"] = str(extraction.unmatched_member_calls)
    language_calls = {
        language: {
            "resolved": resolved,
            "ambiguous": ambiguous,
            "unknown_receiver": unknown_receiver,
            "external_resolved": external_resolved,
            "unmatched": unmatched,
        }
        for (
            language,
            resolved,
            ambiguous,
            unknown_receiver,
            external_resolved,
            unmatched,
        ) in extraction.member_calls_by_language
    }
    encoded_language_calls = json.dumps(
        language_calls,
        sort_keys=True,
        separators=(",", ":"),
    )
    meta["member_calls_by_language"] = encoded_language_calls
    meta["member_call_telemetry_version"] = _MEMBER_CALL_TELEMETRY_VERSION
    telemetry_scope = (
        "full_scan"
        if not scope_concepts_to_dirty and dirty_count == active_count
        else "changed_files"
    )
    meta["member_call_telemetry_scope"] = telemetry_scope
    for name, value in (
        ("resolved", extraction.resolved_member_calls),
        ("ambiguous", extraction.ambiguous_member_calls),
        ("unknown_receiver", extraction.unknown_receiver_member_calls),
        ("unresolved", extraction.unresolved_member_calls),
        ("external_resolved", extraction.external_resolved_member_calls),
        ("unmatched", extraction.unmatched_member_calls),
    ):
        meta[f"member_calls_last_update_{name}"] = str(value)
        if telemetry_scope == "full_scan":
            meta[f"member_calls_global_{name}"] = str(value)
    # Histogram of *why* receivers went untyped, not just how
    # many. A single opaque total says a resolver pass is
    # needed without saying which one, and inferring the shapes
    # from source patterns has produced wrong priorities more
    # than once.
    if extraction.unknown_receiver_classes:
        meta["member_calls_unknown_receiver_classes"] = ",".join(
            f"{name}:{count}" for name, count in extraction.unknown_receiver_classes
        )
        if telemetry_scope == "full_scan":
            meta["member_calls_global_unknown_receiver_classes"] = meta[
                "member_calls_unknown_receiver_classes"
            ]
    meta["member_calls_last_update_scope"] = telemetry_scope
    meta["member_calls_last_update_version"] = _MEMBER_CALL_TELEMETRY_VERSION
    meta["member_calls_last_update_by_language"] = encoded_language_calls
    if telemetry_scope == "full_scan":
        meta["member_calls_global_scope"] = "full_scan_snapshot"
        meta["member_calls_global_version"] = _MEMBER_CALL_TELEMETRY_VERSION
        # Stamp what this snapshot actually covered. An incremental
        # scan carries these global counts forward verbatim, so
        # without provenance `status` reports a months-old resolver's
        # numbers as if they were current -- which silently hides the
        # effect of any resolver change, since that affects every
        # file rather than only the changed ones.
        meta["member_calls_global_scanned_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        meta["member_calls_global_scanned_files"] = str(active_count)
        meta["member_calls_global_by_language"] = encoded_language_calls
    meta["frontend_fallback_count"] = str(len(extraction.fallback_files))
    meta["frontend_fallback_files"] = ",".join(extraction.fallback_files)
    meta["frontend_unsupported_count"] = str(len(extraction.unsupported_files))
    meta["frontend_unsupported_files"] = ",".join(extraction.unsupported_files)
    meta["frontend_grammar_error_count"] = str(len(extraction.grammar_errors))
    meta["frontend_grammar_errors"] = ",".join(extraction.grammar_errors)
    meta["frontend_timeout_count"] = str(len(extraction.timeout_files))
    meta["frontend_timeout_files"] = ",".join(extraction.timeout_files)
    meta["frontend_parse_error_count"] = str(len(extraction.parse_error_files))
    meta["frontend_parse_error_files"] = ",".join(extraction.parse_error_files)
    if extraction.failed_files:
        meta["frontend_failure_count"] = str(len(extraction.failed_files))
        meta["frontend_failures"] = ",".join(extraction.failed_files)
    return meta


def _source_concept_scan_metadata(
    *,
    candidate_count: int,
    eligible_count: int,
    interpretation_edges: list[Edge],
    concepts_ms: float,
    scope_concepts_to_dirty: bool,
) -> dict[str, str]:
    """Build the per-scan source-concept telemetry from this scan's linking pass.

    A pure function of the counts and the edges just produced by the
    interpretation-concept loop; the caller ``metadata.update()``s the result.
    The global full-graph snapshot is a separate recompute (see below).
    """
    meta: dict[str, str] = {}
    meta["source_concepts_profile_ms"] = f"{concepts_ms:.3f}"
    meta["source_concepts_candidates"] = str(candidate_count)
    meta["source_concepts_eligible"] = str(eligible_count)
    meta["source_concepts_links"] = str(len(interpretation_edges))
    linked_source_nodes = {edge.source for edge in interpretation_edges}
    meta["source_concepts_linked_nodes"] = str(len(linked_source_nodes))
    meta["source_concepts_coverage_ratio"] = (
        f"{len(linked_source_nodes) / max(1, eligible_count):.6f}"
    )
    typed_fact_links = sum(
        edge.provenance == "interpretation_registry_fact"
        for edge in interpretation_edges
    )
    exact_alias_links = len(interpretation_edges) - typed_fact_links
    meta["source_concepts_typed_fact_links"] = str(typed_fact_links)
    meta["source_concepts_exact_alias_links"] = str(exact_alias_links)
    meta["source_concepts_linked_concepts"] = str(len({
        edge.target for edge in interpretation_edges
    }))
    meta["source_concepts_mode"] = "closed_registry_typed_fact_or_exact_alias_v2"
    meta["source_concepts_rejected_excluded_kind"] = str(candidate_count - eligible_count)
    meta["source_concepts_rejected_no_registry_alias"] = str(
        eligible_count - len(linked_source_nodes)
    )
    meta["source_concepts_rejected_no_evidence"] = meta[
        "source_concepts_rejected_no_registry_alias"
    ]
    for field in (
        "candidates",
        "eligible",
        "links",
        "linked_nodes",
        "coverage_ratio",
        "typed_fact_links",
        "exact_alias_links",
        "linked_concepts",
        "rejected_excluded_kind",
        "rejected_no_registry_alias",
        "rejected_no_evidence",
    ):
        meta[f"source_concepts_last_update_{field}"] = meta[f"source_concepts_{field}"]
    meta["source_concepts_last_update_scope"] = (
        "changed_files" if scope_concepts_to_dirty else "full_scan"
    )
    return meta


def _global_source_concept_metadata(
    nodes: dict[str, Node],
    edges: list[Edge],
    excluded_concept_kinds: set[str],
) -> dict[str, str]:
    """Recompute the full-graph source-concept snapshot over the final graph.

    Unlike the per-scan pass (which may be scoped to dirty files), this measures
    the whole assembled graph so ``status`` reports coverage for what was
    actually persisted. Pure function of the final nodes/edges.
    """
    global_eligible_concept_nodes = {
        node_id
        for node_id, node in nodes.items()
        if node.active
        and node.kind not in excluded_concept_kinds
        and node_id not in INTERPRETATION_CONCEPT_IDS
    }
    global_interpretation_edges = [
        edge
        for edge in edges
        if edge.active
        and edge.type in SOURCE_CONCEPT_RELATIONS
        and edge.source in global_eligible_concept_nodes
    ]
    global_linked_source_nodes = {
        edge.source for edge in global_interpretation_edges
    }
    return {
        "source_concepts_candidates": str(len(nodes)),
        "source_concepts_eligible": str(len(global_eligible_concept_nodes)),
        "source_concepts_links": str(len(global_interpretation_edges)),
        "source_concepts_linked_nodes": str(len(global_linked_source_nodes)),
        "source_concepts_coverage_ratio": (
            f"{len(global_linked_source_nodes) / max(1, len(global_eligible_concept_nodes)):.6f}"
        ),
        "source_concepts_typed_fact_links": str(sum(
            edge.provenance == "interpretation_registry_fact"
            for edge in global_interpretation_edges
        )),
        "source_concepts_exact_alias_links": str(sum(
            edge.provenance == "interpretation_registry"
            for edge in global_interpretation_edges
        )),
        "source_concepts_linked_concepts": str(len({
            edge.target for edge in global_interpretation_edges
        })),
        "source_concepts_rejected_excluded_kind": str(
            len(nodes) - len(global_eligible_concept_nodes)
        ),
        "source_concepts_rejected_no_registry_alias": str(
            len(global_eligible_concept_nodes) - len(global_linked_source_nodes)
        ),
        "source_concepts_rejected_no_evidence": str(
            len(global_eligible_concept_nodes) - len(global_linked_source_nodes)
        ),
        "source_concepts_scope": "full_graph_snapshot",
    }


def _persist_scan_manifest(
    manifest,
    *,
    file_map: dict[str, str],
    dirty_files: list[tuple[Path, str, str]],
    active_rels: set[str],
    nodes: dict[str, Node],
    edges: list[Edge],
    depth: str,
    frontend: str,
    docs: bool,
    root: Path,
    python_fact_snapshots: dict[str, dict],
    type_index_data: dict,
    manifest_path: Path | None,
    manifest_sink: list | None,
    progress: ScanProgress | None,
) -> None:
    """Record per-file node/edge ownership into the manifest for dirty files.

    Terminal side-effect stage: the pipeline never reads manifest state back, so
    this consumes the finished graph and writes (or defers, via ``manifest_sink``)
    the manifest. One linear pass indexes graph ownership by path so each dirty
    file's manifest row is a direct lookup rather than a full O(N+E) rescan.
    """
    _emit_progress(progress, "manifest", f"dirty_files={len(dirty_files)} active_files={len(active_rels)}")
    # Clean up deleted files from manifest
    keys_to_delete = [k for k in manifest.files if k not in active_rels]
    for k in keys_to_delete:
        del manifest.files[k]

    file_rel_by_node_id = {node_id: rel for rel, node_id in file_map.items()}

    def owner_path_of(node_id: str) -> str | None:
        if node_id in nodes:
            return nodes[node_id].path
        return file_rel_by_node_id.get(node_id)

    # Decode graph ownership once, then reuse the indexed projections for every
    # dirty file. The previous formulation rescanned all E edges and N nodes for
    # each of F files: O(F * (N + E)). These maps are the manifest equivalent of
    # register decoding -- one linear pass converts graph state into direct
    # per-file operands.
    owned_nodes_by_path: dict[str, set[str]] = defaultdict(set)
    edges_by_path: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    endpoint_nodes_by_path: dict[str, set[str]] = defaultdict(set)
    for nid, node in nodes.items():
        if node.path:
            owned_nodes_by_path[node.path].add(nid)
    for edge in edges:
        owner_path = owner_path_of(edge.source)
        if not owner_path:
            continue
        edge_row = (edge.source, edge.target, edge.type)
        edges_by_path[owner_path].append(edge_row)
        if edge.source in nodes:
            endpoint_nodes_by_path[owner_path].add(edge.source)
        if edge.target in nodes:
            endpoint_nodes_by_path[owner_path].add(edge.target)

    for f, rel, fhash in dirty_files:
        file_edges = edges_by_path.get(rel, [])
        file_nodes = sorted(owned_nodes_by_path.get(rel, set()) | endpoint_nodes_by_path.get(rel, set()))
        manifest.update_file(
            rel_path=rel,
            file_hash=fhash,
            depth=depth,
            frontend=frontend,
            docs=docs,
            nodes=file_nodes,
            edges=file_edges,
            type_facts=python_fact_snapshots.get(rel, {}),
        )
    manifest.type_index = type_index_data
    if manifest_path is not None:
        manifest.source_root = str(root)
        if manifest_sink is not None:
            # Defer the write so the lifecycle can commit the manifest only
            # after the graph is durably persisted. Writing it here left the
            # manifest describing nodes a failed graph write never committed.
            manifest_sink.append((manifest, manifest_path))
        else:
            manifest.save(manifest_path)


def _build_graph_from_split(
    *,
    root: Path,
    file_map: dict[str, str],
    dirty_files: list[tuple[Path, str, str]],
    skipped_files: list[tuple[Path, str, str]],
    active_rels: set[str],
    dirty_git: set[str],
    churn_git: dict[str, int],
    manifest,
    previous_graph,
    manifest_path: Path | None,
    max_nodes: int,
    generic_mentions: bool,
    depth: str,
    frontend: str,
    docs: bool,
    history: bool,
    max_history_commits: int,
    scope_concepts_to_dirty: bool = False,
    files_truncated: bool = False,
    files_total_matched: int = 0,
    ignore_files: tuple[str, ...] = (),
    ignored_by_rules: int = 0,
    rule_pruned_dirs: tuple[str, ...] = (),
    default_pruned_dirs: tuple[str, ...] = (),
    python_fact_snapshots: dict[str, dict] | None = None,
    type_fact_update: AffectedTypeFactFiles = AffectedTypeFactFiles(),
    python_type_context: PythonProjectTypeFacts = PythonProjectTypeFacts({}, {}, {}),
    type_index_data: dict | None = None,
    progress: ScanProgress | None = None,
    manifest_sink: list | None = None,
) -> Graph:
    """Shared body: given a dirty/skip split (however it was determined),
    build the resulting Graph. Used by both the full-discovery
    ``scan_directory`` and the targeted ``update_paths``/``remove_paths``.
    """
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    dirty_rels = {rel for _f, rel, _fhash in dirty_files}

    skipped_edges: list[tuple[str, str, str, Edge | None]] = []
    context_symbol_nodes: dict[str, Node] = {}

    # Index previous edges once by (source, target, type) so restoring skipped
    # files' edges is O(1) per lookup instead of a linear scan over the whole
    # previous graph. On a large repo with mostly-unchanged files, that linear
    # scan was effectively O(edges^2) -- e.g. ~87k edges made a no-op rescan
    # of locus take over 80s here even though nothing had changed.
    previous_edge_index: dict[tuple[str, str, str], Edge] = {}
    if previous_graph is not None:
        for pe in previous_graph.edges:
            previous_edge_index.setdefault((pe.source, pe.target, pe.type), pe)

    # Load skipped nodes. Do not restore nodes owned by files that will be
    # rescanned below; those symbols must come from the current source text.
    for f, rel, fhash in skipped_files:
        info = manifest.get_file_info(rel)
        if info is None:
            continue
        for nid in info.get("nodes", []):
            if nid in previous_graph.nodes:
                previous_node = previous_graph.nodes[nid]
                # Manifest node lists intentionally include edge endpoints so
                # pathless shared concepts survive targeted updates. A file
                # node referenced by another file is also such an endpoint,
                # though, and restoring it after its owning path was removed
                # resurrects the exact base-node leak seen in `remove`.
                # Path-bearing nodes are owned by that path; only active paths
                # may restore them. Pathless semantic nodes remain shared.
                owns_active_path = not previous_node.path or previous_node.path in active_rels
                if previous_node.path not in dirty_rels and owns_active_path:
                    nodes[nid] = previous_node
                    if _context_symbol_node(previous_node):
                        context_symbol_nodes[nid] = previous_node
        for src, tgt, etype in info.get("edges", []):
            matching_edge = previous_edge_index.get((src, tgt, etype))
            skipped_edges.append((src, tgt, etype, matching_edge))

    # Create file nodes for dirty files
    for f, rel, fhash in dirty_files:
        nid = file_map[rel]
        facts = []
        if "/" not in rel and "\\" not in rel:
            facts.append(f"project:{root.name.lower()}")
        if rel in dirty_git:
            facts.append("git:dirty")
            facts.append("git:modified")
        churn = churn_git.get(rel, 0)
        if churn > 0:
            facts.append(f"git:churn-{churn}")
            if churn >= 5:
                facts.append("git:high-churn")
                facts.append("git:frequent")

        nodes[nid] = Node(
            id=nid,
            label=f.name,
            kind=EXT_KIND.get(f.suffix.lower(), "file"),
            path=rel,
            facts=tuple(facts),
        )

    # Module hierarchy: add directory nodes and contains edges for every file
    # node, regardless of language-specific kind.
    import re
    for _rel, file_nid in file_map.items():
        file_node = nodes.get(file_nid)
        if not file_node:
            continue
        rel_path = Path(file_node.path)
        parent = rel_path.parent
        if parent == Path('.'):
            continue
        dir_rel = parent.as_posix()
        dir_id = f"dir_{re.sub(r'[^A-Za-z0-9_]', '_', dir_rel)}"
        if dir_id not in nodes:
            dir_node = Node(
                id=dir_id,
                label=parent.name,
                kind="package",
                path=dir_rel,
                facts=(),
            )
            nodes[dir_id] = dir_node
        edges.append(Edge(
            source=dir_id,
            target=file_nid,
            type="contains",
            weight=1.0,
            confidence=0.9,
            provenance="hierarchy",
            source_location="",
        ))

    _emit_progress(progress, "file_edges", f"dirty_files={len(dirty_files)}")
    add_file_edges(
        dirty_files=dirty_files,
        root=root,
        file_map=file_map,
        edges=edges,
        seen=seen,
        generic_mentions=generic_mentions,
    )

    metadata = {
        "scan_depth": depth,
        "scan_max_nodes": str(max_nodes),
        # Default the label from the prior graph on an incremental refresh, so a
        # scan that preserves previously-extracted symbols (no dirty files this
        # round) does not reset `frontend` to "files" and misreport itself as a
        # file-level graph. Fresh symbol extraction below overwrites this with
        # the real extractor id.
        "frontend": str(previous_graph.metadata.get("frontend", "files")) if previous_graph is not None else "files",
        "docs": str(bool(docs)).lower(),
        "history": str(bool(history)).lower(),
        "generic_mentions": str(bool(generic_mentions)).lower(),
        "git_dirty": ",".join(dirty_git),
        "git_high_churn": ",".join(rel for rel, churn in churn_git.items() if churn >= 5),
        "ignore_rule_files": ",".join(ignore_files),
        "ignore_rule_file_count": str(len(ignore_files)),
        "ignored_by_rules": str(ignored_by_rules),
        "ignore_pruned_dir_count": str(len(rule_pruned_dirs)),
        "ignore_pruned_dirs": ",".join(rule_pruned_dirs[:20]),
        "default_pruned_dir_count": str(len(default_pruned_dirs)),
        "default_pruned_dirs": ",".join(default_pruned_dirs[:20]),
        "incremental_type_facts_changed": str(type_fact_update.changed_facts),
        "incremental_type_obligations_affected": str(
            type_fact_update.affected_obligations
        ),
        "incremental_type_files_promoted": str(len(type_fact_update.files)),
    }
    if previous_graph is not None:
        for name in _MEMBER_CALL_TELEMETRY_FIELDS:
            prior = previous_graph.metadata.get(
                f"member_calls_global_{name}",
                previous_graph.metadata.get(f"member_calls_{name}", ""),
            )
            if prior:
                metadata[f"member_calls_global_{name}"] = prior
        metadata["member_calls_global_version"] = previous_graph.metadata.get(
            "member_calls_global_version",
            previous_graph.metadata.get("member_call_telemetry_version", "1"),
        )
        prior_scope = previous_graph.metadata.get(
            "member_calls_global_scope",
            previous_graph.metadata.get("member_call_telemetry_scope", ""),
        )
        if prior_scope:
            metadata["member_calls_global_scope"] = prior_scope
        # Provenance travels with the carried-forward counts, or the age of
        # the snapshot becomes unknowable after the first incremental scan.
        for provenance in ("scanned_at", "scanned_files", "unknown_receiver_classes"):
            prior_value = previous_graph.metadata.get(f"member_calls_global_{provenance}", "")
            if prior_value:
                metadata[f"member_calls_global_{provenance}"] = prior_value
        prior_languages = previous_graph.metadata.get("member_calls_global_by_language", "")
        if prior_languages:
            metadata["member_calls_global_by_language"] = prior_languages
    if files_truncated:
        # collect_files() hit max_nodes before covering every matched file --
        # some real files were never even read, let alone symbol-extracted.
        # Silent by default before this fix; now surfaced so a scan of a
        # large real codebase doesn't quietly produce an incomplete graph.
        metadata["files_truncated"] = "true"
        metadata["files_total_matched"] = str(files_total_matched)
        metadata["files_scanned"] = str(len(active_rels))

    python_fact_snapshots = dict(python_fact_snapshots or {})
    if depth == "symbols" and dirty_files:
        source_files: list[SourceFile] = []
        for f, rel, fhash in dirty_files:
            suffix = f.suffix.lower()
            if suffix not in SOURCE_SUFFIXES:
                continue
            file_nid = file_map[rel]
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            source_files.append(SourceFile(f, rel, file_nid, text))
            if suffix == ".py" and rel not in python_fact_snapshots:
                python_fact_snapshots[rel] = python_file_type_snapshot(text, rel)

        if source_files:
            # Raised from *5 (10,000 symbols at the old max_nodes=2000 default)
            # after real usage on a large C codebase (tens of thousands of
            # functions) silently truncated mid-scan with no indication --
            # a real function 469 call sites deep didn't even get a node.
            # Still bounded (not unlimited) to protect against pathological
            # repos, but now the truncation itself is never silent (below).
            max_syms = max(500, max_nodes * 20)
            _emit_progress(progress, "symbols", f"files={len(source_files)} cap={max_syms} frontend={frontend}")
            extractor = select_extractor(frontend)
            extraction_kwargs = {
                "files": source_files,
                "max_total_symbols": max_syms,
                "context_nodes": context_symbol_nodes,
            }
            if getattr(extractor, "accepts_type_fact_context", False):
                extraction_kwargs["type_fact_context"] = python_type_context
            extraction = extractor.extract_symbols(**extraction_kwargs)
            metadata.update(
                _symbol_extraction_metadata(
                    extraction,
                    scope_concepts_to_dirty=scope_concepts_to_dirty,
                    dirty_count=len(dirty_rels),
                    active_count=len(active_rels),
                )
            )
            nodes.update(extraction.nodes)
            _merge_new_edges(edges, extraction.edges)
            _emit_progress(
                progress,
                "symbols",
                f"frontend={extraction.frontend} nodes={len(extraction.nodes)} edges={len(extraction.edges)} "
                f"fallbacks={len(extraction.fallback_files)} failures={len(extraction.failed_files)} "
                f"member_calls={extraction.resolved_member_calls}/{extraction.ambiguous_member_calls}/"
                f"{extraction.unknown_receiver_member_calls}/{extraction.unresolved_member_calls} "
                "resolved/ambiguous/unknown-receiver/external-or-unmatched",
            )
            if extraction.truncated:
                # Symbol extraction hit max_total_symbols before every
                # collected file's definitions could be recorded -- some
                # files may have zero symbols (whichever were processed
                # after the cap), producing an incomplete graph silently
                # unless surfaced here.
                metadata["symbols_truncated"] = "true"
                metadata["symbols_cap"] = str(max_syms)

    if docs and dirty_files:
        doc_inputs: list[DocumentInput] = []
        for f, rel, fhash in dirty_files:
            if f.suffix.lower() not in DOC_SUFFIXES:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            doc_inputs.append(DocumentInput(f, rel, file_map[rel], text))
        if doc_inputs:
            _emit_progress(progress, "docs", f"files={len(doc_inputs)}")
            docs_started = time.perf_counter()
            doc_profiles: list[tuple[str, float, int, int, bool]] = []
            symbol_map: dict[str, str] = {}
            for nid, node in nodes.items():
                if node.kind in {"file", "concept", "section", "paragraph"}:
                    continue
                for alias in _symbol_aliases(node):
                    symbol_map.setdefault(alias, nid)
            doc_nodes, doc_edges = extract_document_context(
                doc_inputs,
                file_map,
                symbol_map=symbol_map,
                profile=lambda rel, elapsed, sections, paragraphs, truncated: doc_profiles.append(
                    (rel, elapsed, sections, paragraphs, truncated)
                ),
            )
            nodes.update(doc_nodes)
            _merge_new_edges(edges, doc_edges)
            docs_ms = (time.perf_counter() - docs_started) * 1000.0
            slowest = sorted(doc_profiles, key=lambda item: item[1], reverse=True)[:8]
            truncated_docs = [item[0] for item in doc_profiles if item[4]]
            metadata["docs_profile_ms"] = f"{docs_ms:.3f}"
            metadata["docs_profile_files"] = str(len(doc_profiles))
            metadata["docs_profile_slowest"] = json.dumps(
                [
                    {"path": rel, "ms": round(elapsed, 3), "sections": sections, "paragraphs": paragraphs}
                    for rel, elapsed, sections, paragraphs, _truncated in slowest
                ],
                separators=(",", ":"),
            )
            metadata["docs_truncated_count"] = str(len(truncated_docs))
            metadata["docs_truncated_files"] = ",".join(truncated_docs[:20])
            _emit_progress(
                progress,
                "docs",
                f"completed_ms={docs_ms:.1f} nodes={len(doc_nodes)} edges={len(doc_edges)} "
                f"truncated={len(truncated_docs)} slowest="
                + ",".join(f"{rel}:{elapsed:.1f}ms" for rel, elapsed, *_rest in slowest[:3]),
            )

    if history:
        _emit_progress(progress, "history", f"max_commits={max_history_commits}")
        history_nodes, history_edges = extract_commit_history(root, file_map, max_commits=max_history_commits)
        history_valid_from = repository_history_start(root)
        if history_valid_from:
            metadata["history_valid_from"] = history_valid_from
            metadata["temporal_coverage"] = "current_snapshot_bounded_by_repository_creation"
        if history_nodes or history_edges:
            nodes.update(history_nodes)
            _merge_new_edges(edges, history_edges)

    # Interpretation-concept linking is a pure function of a node's own
    # fields (label/kind/path/facts) -- deterministic and independent of
    # other files. For the full-discovery scan it's cheap enough (relative
    # to everything else) to just run over every node. For targeted
    # update/remove on a large graph, only the dirty side needs it: a
    # skipped node's concept edges were already captured in its owning
    # file's manifest entry the last time it was dirty (via the
    # endpoint_nodes side-channel below) and get restored through
    # skipped_edges/nodes exactly like any other edge type.
    concept_source_nodes = (
        tuple(n for n in nodes.values() if n.path in dirty_rels)
        if scope_concepts_to_dirty
        else tuple(nodes.values())
    )
    excluded_concept_kinds = {
        "concept", "section", "paragraph", "markdown", "rst", "html", "text", "unknown", "commit",
    }
    eligible_concept_nodes = tuple(
        node
        for node in concept_source_nodes
        if node.kind not in excluded_concept_kinds
        and node.id not in INTERPRETATION_CONCEPT_IDS
    )
    interpretation_nodes: dict[str, Node] = {}
    interpretation_edges: list[Edge] = []
    concepts_started = time.perf_counter()
    _emit_progress(progress, "concepts", f"candidate_nodes={len(concept_source_nodes)}")
    for node in eligible_concept_nodes:
        found_nodes, found_edges = link_source_interpretation_concepts(node, source_location=node.path)
        interpretation_nodes.update(found_nodes)
        interpretation_edges.extend(found_edges)
    if interpretation_nodes or interpretation_edges:
        nodes.update(interpretation_nodes)
        _merge_new_edges(edges, interpretation_edges)
    concepts_ms = (time.perf_counter() - concepts_started) * 1000.0
    metadata.update(
        _source_concept_scan_metadata(
            candidate_count=len(concept_source_nodes),
            eligible_count=len(eligible_concept_nodes),
            interpretation_edges=interpretation_edges,
            concepts_ms=concepts_ms,
            scope_concepts_to_dirty=scope_concepts_to_dirty,
        )
    )
    _emit_progress(
        progress,
        "concepts",
        f"completed_ms={concepts_ms:.1f} links={len(interpretation_edges)}",
    )

    existing_edges = {(e.source, e.target, e.type) for e in edges}
    for src, tgt, etype, matching_edge in skipped_edges:
        if src not in nodes or tgt not in nodes:
            continue
        key = (src, tgt, etype)
        if key in existing_edges:
            continue
        existing_edges.add(key)
        seen.add((src, tgt))
        if matching_edge:
            edges.append(matching_edge)
        else:
            edges.append(Edge(source=src, target=tgt, type=etype))

    # Older snapshots could treat generated registry nodes as source symbols,
    # producing self-links such as Bellman -> Bellman. Remove those stale
    # instructions even when they arrive through incremental manifest restore.
    edges = [
        edge
        for edge in edges
        if not (
            edge.active
            and edge.type in SOURCE_CONCEPT_RELATIONS
            and edge.source in INTERPRETATION_CONCEPT_IDS
        )
    ]
    edges, rust_reference_receipt = filter_rust_reference_edges(
        root,
        active_rels,
        nodes,
        edges,
    )
    metadata["rust_reference_candidates"] = str(rust_reference_receipt.candidates)
    metadata["rust_reference_rejected_qualified_suffix"] = str(
        rust_reference_receipt.rejected_qualified_suffix
    )
    metadata["rust_reference_rejected_unreachable_crate"] = str(
        rust_reference_receipt.rejected_unreachable_crate
    )

    # Update manifest for the scanned (dirty) files
    if manifest:
        _persist_scan_manifest(
            manifest,
            file_map=file_map,
            dirty_files=dirty_files,
            active_rels=active_rels,
            nodes=nodes,
            edges=edges,
            depth=depth,
            frontend=frontend,
            docs=docs,
            root=root,
            python_fact_snapshots=python_fact_snapshots,
            type_index_data=type_index_data or {},
            manifest_path=manifest_path,
            manifest_sink=manifest_sink,
            progress=progress,
        )

    # Edge confidence is epistemic: it records how trustworthy the extraction
    # is. Centrality and symbol visibility are relevance signals, not evidence
    # that an edge exists, so applying them here made confidence change when an
    # unrelated file was added or removed. Keep those signals in retrieval-time
    # ranking and preserve the frontend/provenance calibration in the graph.
    metadata.update(
        _global_source_concept_metadata(nodes, edges, excluded_concept_kinds)
    )
    _emit_progress(progress, "complete", f"nodes={len(nodes)} edges={len(edges)}")
    return Graph(nodes=nodes, edges=edges, metadata=metadata)


def _symbol_aliases(node: Node) -> tuple[str, ...]:
    aliases: list[str] = []
    for raw in (node.label, Path(node.path).stem if node.path else ""):
        if not raw:
            continue
        for candidate in (raw, term_key(raw)):
            if candidate and candidate not in aliases:
                aliases.append(candidate)
    return tuple(aliases)


def _context_symbol_node(node: Node) -> bool:
    return node.kind not in {"file", "python", "package", "concept", "section", "unknown"} and bool(node.path)
