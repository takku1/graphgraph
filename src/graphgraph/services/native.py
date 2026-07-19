from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Callable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

from ..graph.core import Graph
from ..io import find_graph_path, load_any, save_validated_graph, validate_graph_file
from ..manifest import Manifest, compute_file_hash
from ..packets.validation import ValidationResult, validate_any
from ..retrieval.git_utils import get_git_ignored_paths, get_git_worktree_paths
from ..scanner import DEFAULT_SCAN_MAX_NODES, remove_paths, scan_directory, update_paths
from ..scanner.core import _normalize_rels
from ..scanner.files import SKIP_DIRS, SKIP_FILE_NAMES, SKIP_SUFFIXES, path_ignored_by_rules
from .context import render_query_context


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
    progress: Callable[[str, str], None] | None = None,
) -> GraphBuildStatus:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    use_incremental = incremental
    previous_graph_path = output_path if use_incremental else None
    # A clean scan must also replace the manifest. Leaving it untouched made
    # the next targeted update resurrect edges from an older extraction
    # policy even though the graph itself had just been rebuilt.
    manifest_path = manifest_path_for_graph(output_path)

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
        exclude_paths=[output_path, manifest_path],
        progress=progress,
    )
    try:
        if progress is not None:
            progress("validate", f"path={output_path}")
        validation = save_validated_graph(graph, output_path)
        if progress is not None:
            progress("saved", f"path={output_path} bytes={output_path.stat().st_size}")
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        if not incremental:
            raise
        if progress is not None:
            progress("repair", "incremental result invalid; retrying clean scan")

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
        exclude_paths=[output_path, manifest_path_for_graph(output_path)],
        progress=progress,
    )
    if progress is not None:
        progress("validate", f"path={output_path} clean_rebuild=true")
    validation = save_validated_graph(graph, output_path)
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
) -> GraphBuildStatus:
    """Repair path shared by update/remove: promote to a clean full rebuild.

    Mirrors ``scan_validated_graph``'s own incremental-then-repair fallback --
    if the targeted operation produced an invalid graph (e.g. the manifest
    was stale relative to disk), a full non-incremental scan is the safety
    net, same as it is for the ordinary incremental scan path.
    """
    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=None,
        manifest_path=manifest_path_for_graph(output_path),
        exclude_paths=[output_path, manifest_path_for_graph(output_path)],
    )
    validation = save_validated_graph(graph, output_path)
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
) -> GraphBuildStatus:
    """Re-extract *paths* and remove *deleted_paths* in one graph splice.

    Requires a prior ``scan_validated_graph``/``graphgraph scan`` run (needs
    an existing graph + manifest at *output_path*). Falls back to a full
    rebuild if that's missing or the result fails validation.
    """
    manifest_path = manifest_path_for_graph(output_path)
    owned_artifacts = _normalize_rels(
        directory.resolve(),
        [output_path, manifest_path],
    )
    update_candidates = [
        path for path in paths
        if _normalize_rels(directory.resolve(), [path]).isdisjoint(owned_artifacts)
    ]
    authoritative_deletions = list(dict.fromkeys([*(deleted_paths or ()), *owned_artifacts]))
    try:
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
        )
        validation = save_validated_graph(graph, output_path)
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


def inspect_saved_graph_freshness(*, directory: Path, output_path: Path) -> dict[str, object]:
    """Read-only manifest check for stale Git candidates in O(changed files)."""
    directory = directory.resolve()
    changed, deleted = get_git_worktree_paths(directory)
    manifest = Manifest.load(manifest_path_for_graph(output_path))
    ignored = set(get_git_ignored_paths(changed, directory))
    ignored.update(path for path in changed if path_ignored_by_rules(directory, path))
    stale_changed: list[str] = []
    for rel_path in changed:
        if rel_path in ignored or not _worktree_sync_candidate(rel_path):
            continue
        source_path = directory / rel_path
        info = manifest.get_file_info(rel_path)
        old_hash = str(info.get("hash") or "") if info else ""
        if source_path.is_file() and compute_file_hash(source_path) != old_hash:
            stale_changed.append(rel_path)
    stale_deleted = [rel_path for rel_path in deleted if manifest.get_file_info(rel_path) is not None]
    return {
        "fresh": not stale_changed and not stale_deleted,
        "changed_count": len(stale_changed),
        "deleted_count": len(stale_deleted),
        "changed_paths": stale_changed[:20],
        "deleted_paths": stale_deleted[:20],
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
        "remaining_stale_paths": sorted(stale),
        "remaining_stale_changed_paths": sorted(stale_changed),
        "remaining_stale_deleted_paths": sorted(stale_deleted),
        "unrelated_changed_paths": sorted(path for path in stale_changed if path not in requested),
        "unrelated_deleted_paths": sorted(path for path in stale_deleted if path not in requested),
    })
    return enriched


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
) -> GraphBuildStatus:
    """Drop *paths* (deleted/renamed-away files) from the existing graph.

    Requires a prior ``scan_validated_graph``/``graphgraph scan`` run. Falls
    back to a full rebuild if that's missing or the result fails validation.
    """
    manifest_path = manifest_path_for_graph(output_path)
    try:
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
        )
        validation = save_validated_graph(graph, output_path)
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        return _full_rescan_fallback(
            directory=directory, output_path=output_path, max_nodes=max_nodes,
            depth=depth, frontend=frontend, docs=docs, history=history,
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


def graph_shape(graph: Graph) -> dict[str, int]:
    source_kinds = {
        "python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
        "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
        "kotlin", "scala", "haskell", "lean", "function", "class",
        "struct", "method", "interface",
    }
    doc_kinds = {"markdown", "rst", "html", "text", "concept", "section", "paragraph"}
    source_nodes = sum(1 for node in graph.nodes.values() if node.kind in source_kinds)
    doc_nodes = sum(1 for node in graph.nodes.values() if node.kind in doc_kinds)
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "source_nodes": source_nodes,
        "doc_nodes": doc_nodes,
        "other_nodes": len(graph.nodes) - source_nodes - doc_nodes,
    }


def _symbol_extraction_status(kind_counts: dict[str, int], metadata: dict[str, object]) -> dict[str, object]:
    """Whether symbol-level extraction is present, from graph content not label.

    ``scan_depth``/``frontend`` are the requested/last-run labels (which an
    incremental preserve-symbols scan can leave stale); ``present`` and
    ``symbol_nodes`` are counted from the graph itself and are authoritative.
    """
    symbol_kinds = {"function", "method", "class", "struct", "interface", "enum", "trait"}
    symbol_nodes = sum(count for kind, count in kind_counts.items() if kind in symbol_kinds)
    return {
        "present": symbol_nodes > 0,
        "symbol_nodes": symbol_nodes,
        "scan_depth": str(metadata.get("scan_depth", "unknown")),
        "frontend": str(metadata.get("frontend", "files")),
    }


def _absent_graph_status(directory: Path, status: str, message: str) -> dict[str, object]:
    """Graceful, actionable status for cold/ambiguous-graph repos.

    Distinct ``status`` discriminator so callers can branch, plus the concrete
    next step. ``next_action`` mirrors the MCP tool name so an agent can chain
    straight into it.
    """
    return {
        "status": status,
        "directory": str(directory),
        "message": message,
        "next_action": "build_graph" if status == "no_graph" else "specify_graph_path",
    }


def _member_call_snapshot(metadata: dict[str, str], scope: str) -> dict[str, object]:
    prefix = f"member_calls_{scope}_"
    counts = {
        name: int(metadata.get(f"{prefix}{name}", metadata.get(f"member_calls_{name}", "0")))
        for name in ("resolved", "ambiguous", "unknown_receiver", "unresolved")
    }
    version = metadata.get(
        f"member_calls_{scope}_version",
        metadata.get("member_call_telemetry_version", "1"),
    )
    typed_total = counts["resolved"] + counts["ambiguous"]
    topology_total = typed_total + counts["unknown_receiver"]
    resolved_ratio = counts["resolved"] / max(1, topology_total)
    trusted_resolution_ratio = counts["resolved"] / max(1, typed_total)
    receiver_evidence_ratio = typed_total / max(1, topology_total)

    if version != "2":
        trust = "legacy_unclassified" if topology_total else "not_applicable"
        coverage = "unknown" if topology_total else "not_applicable"
        warning = (
            "member-call telemetry predates receiver-evidence classification; run a full symbol scan"
            if topology_total
            else ""
        )
    else:
        if typed_total == 0:
            trust = "not_applicable"
        elif counts["ambiguous"] == 0:
            trust = "high"
        elif counts["resolved"] == 0:
            trust = "low"
        else:
            trust = "mixed"

        if topology_total == 0:
            coverage = "not_applicable"
        elif counts["unknown_receiver"] == 0:
            coverage = "complete"
        elif typed_total:
            coverage = "partial"
        else:
            coverage = "unresolved"
        warnings: list[str] = []
        if counts["unknown_receiver"]:
            warnings.append(
                f"{counts['unknown_receiver']} member-call sites lack receiver evidence and are excluded from topology"
            )
        if counts["ambiguous"]:
            warnings.append(
                f"{counts['ambiguous']} typed member-call sites have multiple internal targets"
            )
        warning = "; ".join(warnings)

    return {
        **counts,
        "external_or_unmatched": counts["unresolved"],
        "telemetry_version": version,
        "resolved_ratio": round(resolved_ratio, 4),
        "trusted_resolution_ratio": round(trusted_resolution_ratio, 4),
        "receiver_evidence_ratio": round(receiver_evidence_ratio, 4),
        "trust": trust,
        "coverage": coverage,
        "warning": warning,
    }


def build_project_status(
    *,
    directory: Path = Path("."),
    graph_path: Path | None = None,
    run_probes: bool = False,
) -> dict[str, object]:
    directory = directory.resolve()
    # A status probe is the natural first call on a cold repo, so "there is no
    # graph yet" is an expected state, not an exception. Return an actionable,
    # inspectable status (consistent with the tool's honest-self-reporting
    # principle) instead of letting the MCP transport surface a -32000 crash.
    if graph_path is not None:
        resolved_graph_path = graph_path
        if not resolved_graph_path.exists():
            return _absent_graph_status(
                directory,
                "no_graph",
                f"No graph at {resolved_graph_path}. Build one first: build_graph (MCP) "
                "or `graphgraph scan --output .graphgraph/graph.gg`.",
            )
    else:
        try:
            resolved_graph_path = find_graph_path(directory)
        except FileNotFoundError:
            return _absent_graph_status(
                directory,
                "no_graph",
                "No native GraphGraph file found. Build one first: build_graph (MCP) "
                "or `graphgraph scan --output .graphgraph/graph.gg`.",
            )
        except RuntimeError as exc:
            # Deliberate refuse-ambiguous-auto-detection stance is preserved --
            # we still do not guess a graph, we just report it as a status the
            # agent can act on rather than crashing the tool call.
            return _absent_graph_status(directory, "ambiguous_graph", str(exc))
    validation = validate_graph_file(resolved_graph_path)
    graph = load_any(resolved_graph_path)
    shape = graph_shape(graph)
    kind_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1

    package = _read_package_status(directory)
    probes = _run_package_probes(directory, package) if run_probes else []
    runtime_notes = _runtime_notes(probes) if run_probes else []
    graph_report: dict[str, object] = {
        "path": str(resolved_graph_path),
        "validation": {
            "ok": validation.ok,
            "format": validation.format,
            "nodes": validation.node_count,
            "edges": validation.edge_count,
            "errors": list(validation.errors[:10]),
        },
        "shape": shape,
        "top_kinds": dict(sorted(kind_counts.items(), key=lambda item: -item[1])[:10]),
        # Derived from actual graph content, not the scan's `frontend`/`scan_depth`
        # metadata label -- an incremental scan that preserves prior symbols can
        # reset that label to "files" even though symbol nodes are still present.
        # This answers "did symbol extraction actually happen?" from ground truth.
        "symbol_extraction": _symbol_extraction_status(kind_counts, graph.metadata),
    }
    # Same diagnostic gap already closed in `graphgraph scan`'s own output and
    # `doctor`: this is the "is something wrong with my graph" surface, so it
    # should say so when the last scan silently hit a truncation cap instead
    # of only showing counts that look complete.
    if graph.metadata.get("files_truncated") == "true":
        graph_report["files_truncated"] = True
        graph_report["files_total_matched"] = graph.metadata.get("files_total_matched")
    if graph.metadata.get("symbols_truncated") == "true":
        graph_report["symbols_truncated"] = True
        graph_report["symbols_cap"] = graph.metadata.get("symbols_cap")
    global_calls = _member_call_snapshot(graph.metadata, "global")
    last_update_calls = _member_call_snapshot(graph.metadata, "last_update")
    graph_report["member_calls"] = {
        **global_calls,
        "scope": graph.metadata.get("member_calls_global_scope", graph.metadata.get("member_call_telemetry_scope", "unavailable")),
        "candidate_edges": sum(1 for edge in graph.edges if edge.active and edge.type == "calls_candidate"),
        "last_update": {
            **last_update_calls,
            "scope": graph.metadata.get("member_calls_last_update_scope", graph.metadata.get("member_call_telemetry_scope", "unavailable")),
        },
    }
    graph_report["concept_linking"] = {
        "mode": graph.metadata.get("source_concepts_mode", "unavailable"),
        "scope": graph.metadata.get("source_concepts_scope", "unavailable"),
        "eligible_nodes": int(graph.metadata.get("source_concepts_eligible", "0")),
        "linked_nodes": int(graph.metadata.get("source_concepts_linked_nodes", "0")),
        "links": int(graph.metadata.get("source_concepts_links", "0")),
        "coverage_ratio": float(graph.metadata.get("source_concepts_coverage_ratio", "0")),
        "rejections": {
            "excluded_kind": int(graph.metadata.get("source_concepts_rejected_excluded_kind", "0")),
            "no_registry_alias": int(graph.metadata.get("source_concepts_rejected_no_registry_alias", "0")),
        },
        "last_update": {
            "scope": graph.metadata.get(
                "source_concepts_last_update_scope",
                "unavailable",
            ),
            "eligible_nodes": int(
                graph.metadata.get("source_concepts_last_update_eligible", "0")
            ),
            "linked_nodes": int(
                graph.metadata.get("source_concepts_last_update_linked_nodes", "0")
            ),
            "coverage_ratio": float(
                graph.metadata.get("source_concepts_last_update_coverage_ratio", "0")
            ),
        },
    }
    graph_report["frontend_fallbacks"] = {
        "total": int(graph.metadata.get("frontend_fallback_count", "0")),
        "unsupported": int(graph.metadata.get("frontend_unsupported_count", "0")),
        "grammar_errors": int(graph.metadata.get("frontend_grammar_error_count", "0")),
        "timeouts": int(graph.metadata.get("frontend_timeout_count", "0")),
        "parse_errors": int(graph.metadata.get("frontend_parse_error_count", "0")),
    }
    return {
        "graph": graph_report,
        "package": package,
        "runtime_probes": probes,
        "runtime_notes": runtime_notes,
    }


def _resolve_cargo_workspace_members(
    directory: Path,
    workspace: dict[str, object],
) -> list[str]:
    """Expand Cargo workspace member globs and apply excludes deterministically."""
    patterns = [
        str(pattern).replace("\\", "/").strip("/")
        for pattern in workspace.get("members", ())
        if str(pattern).strip()
    ]
    excludes = [
        str(pattern).replace("\\", "/").strip("/")
        for pattern in workspace.get("exclude", ())
        if str(pattern).strip()
    ]
    root = directory.resolve()
    members: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        try:
            candidates = (
                tuple(sorted(directory.glob(pattern), key=lambda path: path.as_posix()))
                if any(marker in pattern for marker in "*?[")
                else (directory / pattern,)
            )
        except (OSError, ValueError):
            continue
        for candidate in candidates:
            member_dir = candidate.parent if candidate.name == "Cargo.toml" else candidate
            if not (member_dir / "Cargo.toml").is_file():
                continue
            try:
                relative = member_dir.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if any(
                relative == excluded
                or fnmatchcase(relative, excluded)
                for excluded in excludes
            ):
                continue
            normalized = relative or "."
            if normalized not in seen:
                members.append(normalized)
                seen.add(normalized)
    return members


def _read_package_status(directory: Path) -> dict[str, object]:
    pyproject = directory / "pyproject.toml"
    cargo_manifest = directory / "Cargo.toml"
    src_layout = (directory / "src").is_dir()
    package: dict[str, object] = {
        "ecosystem": "python" if pyproject.exists() else "",
        "ecosystems": ["python"] if pyproject.exists() else [],
        "pyproject": str(pyproject) if pyproject.exists() else "",
        "cargo_manifest": str(cargo_manifest) if cargo_manifest.exists() else "",
        "name": "",
        "version": "",
        "module": "",
        "scripts": {},
        "src_layout": src_layout,
        "import_hint": "Set PYTHONPATH=src or install the package editable before direct python -m probes."
        if src_layout else "",
    }
    if cargo_manifest.exists():
        try:
            cargo = tomllib.loads(cargo_manifest.read_text(encoding="utf-8"))
            cargo_package = cargo.get("package") or {}
            workspace = cargo.get("workspace") or {}
            member_patterns = [
                str(member)
                for member in workspace.get("members", ())
            ]
            rust = {
                "kind": "workspace" if workspace else "package",
                "name": str(cargo_package.get("name") or directory.name),
                "version": str(cargo_package.get("version") or ""),
                "members": _resolve_cargo_workspace_members(directory, workspace),
                "member_patterns": member_patterns,
                "exclude_patterns": [
                    str(member)
                    for member in workspace.get("exclude", ())
                ],
            }
            package["rust"] = rust
            ecosystems = list(package["ecosystems"])
            ecosystems.append("rust")
            package["ecosystems"] = ecosystems
            package["ecosystem"] = "mixed" if pyproject.exists() else "rust"
            if not pyproject.exists():
                package["name"] = rust["name"]
                package["version"] = rust["version"]
        except Exception as exc:
            package["cargo_error"] = f"failed to parse Cargo.toml: {exc}"
    if not pyproject.exists():
        return package
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception as exc:
        package["error"] = f"failed to parse pyproject.toml: {exc}"
        return package

    project = data.get("project") or {}
    if isinstance(project, dict):
        name = str(project.get("name") or "")
        package["name"] = name
        package["version"] = str(project.get("version") or "")
        package["module"] = name.replace("-", "_") if name else ""
        scripts = project.get("scripts") or {}
        if isinstance(scripts, dict):
            package["scripts"] = {str(k): str(v) for k, v in scripts.items()}
    return package


def _run_package_probes(directory: Path, package: dict[str, object]) -> list[dict[str, object]]:
    module = str(package.get("module") or "")
    if not module:
        return []

    probes: list[dict[str, object]] = []
    commands = (
        ("module_help", [sys.executable, "-m", module, "--help"]),
        ("import", [sys.executable, "-c", f"import {module}; print({module}.__file__)"]),
    )
    raw_env = os.environ.copy()
    raw_env.pop("PYTHONPATH", None)
    for name, args in commands:
        probes.append(_run_probe(name=f"raw_{name}", args=args, directory=directory, env=raw_env, env_label="raw"))

    if package.get("src_layout"):
        src_env = os.environ.copy()
        src_path = str(directory / "src")
        existing = src_env.get("PYTHONPATH")
        src_env["PYTHONPATH"] = src_path if not existing else src_path + os.pathsep + existing
        for name, args in commands:
            probes.append(_run_probe(name=f"src_{name}", args=args, directory=directory, env=src_env, env_label="PYTHONPATH=src"))

    scripts = package.get("scripts") or {}
    if isinstance(scripts, dict):
        env = os.environ.copy()
        if package.get("src_layout"):
            env["PYTHONPATH"] = str(directory / "src")
        for script_name, target in sorted(scripts.items()):
            module_name = str(target).split(":", 1)[0].strip()
            if not module_name:
                continue
            probes.append(
                _run_probe(
                    name=f"script_target_import:{script_name}",
                    args=[sys.executable, "-c", f"import {module_name}; print({module_name}.__file__)"],
                    directory=directory,
                    env=env,
                    env_label="PYTHONPATH=src" if package.get("src_layout") else "raw",
                )
            )
    return probes


def _run_probe(
    *,
    name: str,
    args: list[str],
    directory: Path,
    env: dict[str, str],
    env_label: str,
) -> dict[str, object]:
    try:
        proc = subprocess.run(
            args,
            cwd=directory,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
        output = (proc.stdout or "").strip().splitlines()
        return {
            "name": name,
            "env": env_label,
            "command": " ".join(args),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": output[:5],
        }
    except Exception as exc:
        return {"name": name, "env": env_label, "command": " ".join(args), "ok": False, "error": str(exc)}


def _runtime_notes(probes: list[dict[str, object]]) -> list[str]:
    by_name = {str(probe.get("name")): probe for probe in probes}
    notes: list[str] = []
    raw_import = by_name.get("raw_import")
    src_import = by_name.get("src_import")
    if raw_import and src_import and not raw_import.get("ok") and src_import.get("ok"):
        notes.append("Package imports only when PYTHONPATH includes src; install editable or export PYTHONPATH=src.")
    raw_module = by_name.get("raw_module_help")
    src_module = by_name.get("src_module_help")
    if raw_module and src_module and not raw_module.get("ok") and src_module.get("ok"):
        notes.append("python -m module works only with src on PYTHONPATH.")
    for probe in probes:
        name = str(probe.get("name") or "")
        if name.startswith("script_target_import:") and not probe.get("ok"):
            notes.append(f"Console script target import failed: {name.split(':', 1)[1]}.")
    return notes


def render_native_context(
    *,
    query: str,
    query_class: str = "auto",
    directory: Path = Path("."),
    graph_path: Path | None = None,
    rebuild: bool = False,
    max_nodes: int | None = None,
    scan_max_nodes: int = DEFAULT_SCAN_MAX_NODES,
    packet: str | None = None,
    anchor_limit: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
    generic_mentions: bool = False,
    incremental: bool = True,
    show_anchors: bool = False,
    changed_paths: tuple[str, ...] = (),
    deleted_paths: tuple[str, ...] = (),
    sync_git: bool = False,
    json_output: bool = False,
    json_details: bool = True,
    source_mode: str = "auto",
    memory_scopes: tuple[str, ...] = ("project", "session"),
) -> tuple[str, GraphBuildStatus]:
    import time
    started = time.monotonic()
    output_path = graph_path or Path(".graphgraph/graph.gg")
    status = ensure_native_graph(
        directory=directory,
        output_path=output_path,
        rebuild=rebuild,
        max_nodes=scan_max_nodes,
        skip_dirs=skip_dirs,
        include_dirs=include_dirs,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        generic_mentions=generic_mentions,
        incremental=incremental,
        discover_existing=graph_path is None,
    )
    refresh_started = time.monotonic()
    if changed_paths or deleted_paths or sync_git:
        status = refresh_saved_graph(
            directory=directory,
            output_path=status.path,
            changed_paths=list(changed_paths),
            deleted_paths=list(deleted_paths),
            sync_git=sync_git,
            max_nodes=scan_max_nodes,
            depth=depth,
            frontend=frontend,
            docs=docs,
            history=history,
        )
    refresh_ms = round((time.monotonic() - refresh_started) * 1000, 3)
    query_started = time.monotonic()
    requested_anchor_paths = tuple(dict.fromkeys((*changed_paths, *status.changed_paths)))
    repository_freshness = (
        {"fresh": True, "changed_count": 0, "deleted_count": 0, "changed_paths": [], "deleted_paths": []}
        if sync_git
        else inspect_saved_graph_freshness(directory=directory, output_path=status.path)
    )
    workflow_metadata = {
        "workflow": {
            "refresh": refresh_receipt(
                status,
                mode="git" if sync_git else ("explicit" if changed_paths or deleted_paths else "none"),
                requested_changed_paths=changed_paths,
                requested_deleted_paths=deleted_paths,
                attempted=bool(changed_paths or deleted_paths or sync_git),
                milliseconds=refresh_ms,
            ),
            "graph_validation": {
                "ok": bool(status.validation.ok) if status.validation else True,
                "format": status.validation.format if status.validation else "existing_valid_graph",
            },
            "freshness": scope_freshness(
                repository_freshness,
                tuple(dict.fromkeys((*changed_paths, *deleted_paths))),
            ),
        }
    }
    packet_text = render_query_context(
        query=query,
        query_class=query_class,
        graph_path=status.path,
        packet=packet,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        scopes=scopes,
        scope_mode=scope_mode,
        show_anchors=show_anchors or json_output,
        json_anchors=json_output,
        cache_namespace="cli_context",
        graph=status.graph if status.built else None,
        response_metadata=workflow_metadata,
        source_mode=source_mode,
        memory_scopes=memory_scopes,
        anchor_paths=requested_anchor_paths,
    )
    if json_output:
        payload = json.loads(packet_text)
        payload["workflow"]["query_milliseconds"] = round((time.monotonic() - query_started) * 1000, 3)
        payload["workflow"]["total_milliseconds"] = round((time.monotonic() - started) * 1000, 3)
        rendered_packet = str(payload.get("packet", ""))
        if rendered_packet:
            packet_validation = validate_any(rendered_packet)
            semantic_validation = payload.get("retrieval", {}).get(
                "semantic_validation",
                {"ok": True, "errors": []},
            )
            semantic_ok = bool(semantic_validation.get("ok", True))
            combined_ok = packet_validation.ok and semantic_ok
            payload["workflow"]["packet_validation"] = {
                "ok": combined_ok,
                "status": (
                    "semantic_fail"
                    if packet_validation.ok and not semantic_ok
                    else "packet_and_receipt_pass"
                    if combined_ok
                    else "structural_fail"
                ),
                "scope": "packet_and_receipt",
                "format": packet_validation.format,
                "nodes": packet_validation.node_count,
                "edges": packet_validation.edge_count,
                "errors": [
                    *packet_validation.errors,
                    *semantic_validation.get("errors", ()),
                ],
            }
        else:
            payload["workflow"]["packet_validation"] = {
                "ok": None,
                "status": "not_applicable",
                "scope": "packet_structure_only",
                "format": "none",
                "nodes": 0,
                "edges": 0,
                "errors": [],
            }
        if not json_details:
            payload = {
                "actionable": payload.get("actionable", {}),
                "control": payload.get("control", ""),
                "metrics": payload.get("metrics", {}),
                "query_class": payload.get("query_class", query_class),
                "routing": payload.get("routing", {}),
                "workflow": payload.get("workflow", {}),
                "details": {
                    "included": False,
                    "hint": "rerun with --json --details for packet, anchors, and full provenance",
                },
            }
        packet_text = json.dumps(payload, indent=2, ensure_ascii=False)
    return packet_text, status
