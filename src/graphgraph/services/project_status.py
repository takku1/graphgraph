"""Project graph status, extraction telemetry, and runtime readiness."""

from __future__ import annotations

import json
from pathlib import Path

from ..concepts import concept_link_health
from ..graph.core import Graph
from ..io import find_graph_path, load_any, project_root_for_graph, validate_graph_file
from .freshness import inspect_saved_graph_freshness
from .runtime_probes import _read_package_status, _run_package_probes, _runtime_notes


def graph_shape(graph: Graph) -> dict[str, int]:
    source_kinds = {
        "python",
        "typescript",
        "tsx",
        "javascript",
        "jsx",
        "go",
        "rust",
        "java",
        "csharp",
        "cpp",
        "c",
        "header",
        "ruby",
        "php",
        "swift",
        "kotlin",
        "scala",
        "haskell",
        "lean",
        "function",
        "class",
        "struct",
        "method",
        "interface",
    }
    doc_kinds = {
        "markdown",
        "rst",
        "html",
        "text",
        "concept",
        "section",
        "paragraph",
    }
    source_nodes = sum(1 for node in graph.nodes.values() if node.kind in source_kinds)
    doc_nodes = sum(1 for node in graph.nodes.values() if node.kind in doc_kinds)
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "source_nodes": source_nodes,
        "doc_nodes": doc_nodes,
        "other_nodes": len(graph.nodes) - source_nodes - doc_nodes,
    }


def _symbol_extraction_status(
    kind_counts: dict[str, int], metadata: dict[str, object]
) -> dict[str, object]:
    """Report symbol extraction from graph content, not a stale scan label."""
    symbol_kinds = {
        "function",
        "method",
        "class",
        "struct",
        "interface",
        "enum",
        "trait",
    }
    symbol_nodes = sum(
        count for kind, count in kind_counts.items() if kind in symbol_kinds
    )
    return {
        "present": symbol_nodes > 0,
        "symbol_nodes": symbol_nodes,
        "scan_depth": str(metadata.get("scan_depth", "unknown")),
        "frontend": str(metadata.get("frontend", "files")),
    }


def classify_active_build(validation_ok: bool, freshness: dict[str, object] | None) -> str:
    """Collapse validation + freshness into one discovery label."""

    if not validation_ok:
        return "invalid"
    if not freshness:
        return "unchecked"
    flag = freshness.get("fresh")
    if flag is True:
        return "validated"
    if flag is False:
        return "stale"
    return "unchecked"


def _absent_graph_status(
    directory: Path, status: str, message: str
) -> dict[str, object]:
    """Return an actionable status for cold or ambiguous repositories."""
    return {
        "status": status,
        "active_build": "absent",
        "directory": str(directory),
        "message": message,
        "next_action": "build_graph" if status == "no_graph" else "specify_graph_path",
    }


def _parse_receiver_classes(raw: str) -> dict[str, int]:
    """Decode the `name:count` histogram of why receivers went untyped."""
    classes: dict[str, int] = {}
    for item in raw.split(","):
        name, _, count = item.partition(":")
        if name and count.isdigit():
            classes[name] = int(count)
    return dict(sorted(classes.items(), key=lambda item: (-item[1], item[0])))


def _member_calls_by_language(raw: str) -> dict[str, dict[str, object]]:
    """Decode compact scanner telemetry into language-conditioned trust data."""
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    result: dict[str, dict[str, object]] = {}
    for language, raw_counts in sorted(decoded.items()):
        if not isinstance(raw_counts, dict):
            continue
        counts = {
            name: int(raw_counts.get(name, 0) or 0)
            for name in (
                "resolved",
                "ambiguous",
                "unknown_receiver",
                "external_resolved",
                "unmatched",
            )
        }
        receiver_sites = (
            counts["resolved"]
            + counts["ambiguous"]
            + counts["unknown_receiver"]
        )
        result[str(language)] = {
            **counts,
            "receiver_sites": receiver_sites,
            "receiver_resolution_ratio": round(
                counts["resolved"] / max(1, receiver_sites),
                4,
            ),
        }
    return result


def _member_call_trust(
    counts: dict[str, int],
    version: str,
    topology_total: int,
    typed_total: int,
) -> tuple[str, str, str]:
    if version != "2":
        trust = "legacy_unclassified" if topology_total else "not_applicable"
        coverage = "unknown" if topology_total else "not_applicable"
        warning = (
            "member-call telemetry predates receiver-evidence classification; "
            "run a full symbol scan"
            if topology_total
            else ""
        )
        return trust, coverage, warning
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
            f"{counts['unknown_receiver']} member-call sites lack receiver "
            "evidence and are excluded from topology"
        )
    if counts["ambiguous"]:
        warnings.append(
            f"{counts['ambiguous']} typed member-call sites have multiple "
            "internal targets"
        )
    return trust, coverage, "; ".join(warnings)


def _member_call_snapshot(metadata: dict[str, str], scope: str) -> dict[str, object]:
    prefix = f"member_calls_{scope}_"
    counts = {
        name: int(
            metadata.get(f"{prefix}{name}", metadata.get(f"member_calls_{name}", "0"))
        )
        for name in (
            "resolved",
            "ambiguous",
            "unknown_receiver",
            "unresolved",
            "external_resolved",
            "unmatched",
        )
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

    trust, coverage, warning = _member_call_trust(counts, version, topology_total, typed_total)

    split_total = counts["external_resolved"] + counts["unmatched"]
    split_available = split_total > 0 or counts["unresolved"] == 0
    if not split_available:
        warning = "; ".join(
            part
            for part in (
                warning,
                f"{counts['unresolved']} external_or_unmatched sites predate the "
                "external/unmatched split; rescan to classify them",
            )
            if part
        )

    return {
        **counts,
        "external_or_unmatched": counts["unresolved"],
        "external_unmatched_split": (
            "available" if split_available else "legacy_unsplit"
        ),
        "unmatched_ratio": (
            round(counts["unmatched"] / max(1, split_total), 4)
            if split_available
            else None
        ),
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
    if graph_path is not None:
        resolved_graph_path = graph_path
        if not resolved_graph_path.exists():
            return _absent_graph_status(
                directory,
                "no_graph",
                f"No graph at {resolved_graph_path}. Build one first: build_graph "
                "(MCP) or `graphgraph scan --output .graphgraph/graph.gg`.",
            )
    else:
        try:
            resolved_graph_path = find_graph_path(directory)
        except FileNotFoundError:
            return _absent_graph_status(
                directory,
                "no_graph",
                "No native GraphGraph file found. Build one first: build_graph "
                "(MCP) or `graphgraph scan --output .graphgraph/graph.gg`.",
            )
        except RuntimeError as exc:
            return _absent_graph_status(directory, "ambiguous_graph", str(exc))

    try:
        validation = validate_graph_file(resolved_graph_path)
        graph = load_any(resolved_graph_path)
    except (OSError, ValueError, KeyError) as exc:
        return {
            "status": "invalid_graph",
            "active_build": "invalid",
            "directory": str(directory),
            "message": f"Native graph at {resolved_graph_path} is not a validated build: {exc}",
            "next_action": "build_graph",
        }
    if not validation.ok:
        return {
            "status": "invalid_graph",
            "active_build": "invalid",
            "directory": str(directory),
            "message": (
                f"Native graph at {resolved_graph_path} failed validation: "
                + "; ".join(str(item) for item in validation.errors[:5])
            ),
            "next_action": "build_graph",
        }
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
        "top_kinds": dict(
            sorted(kind_counts.items(), key=lambda item: -item[1])[:10]
        ),
        "symbol_extraction": _symbol_extraction_status(kind_counts, graph.metadata),
    }
    if graph.metadata.get("files_truncated") == "true":
        graph_report["files_truncated"] = True
        graph_report["files_total_matched"] = graph.metadata.get("files_total_matched")
    if graph.metadata.get("symbols_truncated") == "true":
        graph_report["symbols_truncated"] = True
        graph_report["symbols_cap"] = graph.metadata.get("symbols_cap")

    global_calls = _member_call_snapshot(graph.metadata, "global")
    last_update_calls = _member_call_snapshot(graph.metadata, "last_update")
    snapshot_at = graph.metadata.get("member_calls_global_scanned_at", "")
    snapshot_files = graph.metadata.get("member_calls_global_scanned_files", "")
    last_scope = graph.metadata.get("member_calls_last_update_scope", "")
    snapshot_stale = bool(snapshot_at) and last_scope == "changed_files"
    graph_report["member_calls"] = {
        **global_calls,
        "scope": graph.metadata.get(
            "member_calls_global_scope",
            graph.metadata.get("member_call_telemetry_scope", "unavailable"),
        ),
        "measured_at": snapshot_at or "unknown",
        "measured_over_files": int(snapshot_files) if snapshot_files else None,
        "snapshot_may_be_stale": snapshot_stale,
        "staleness_note": (
            f"counts were measured by a full scan over {snapshot_files} file(s)"
            f"{' at ' + snapshot_at if snapshot_at else ''}; incremental scans "
            "carry them forward unchanged, so re-run with --no-incremental to "
            "measure a resolver change"
            if snapshot_stale
            else ""
        ),
        "unknown_receiver_classes": _parse_receiver_classes(
            graph.metadata.get("member_calls_global_unknown_receiver_classes", "")
            or graph.metadata.get("member_calls_unknown_receiver_classes", "")
        ),
        "by_language": _member_calls_by_language(
            graph.metadata.get("member_calls_global_by_language", "")
        ),
        "candidate_edges": sum(
            1
            for edge in graph.edges
            if edge.active and edge.type == "calls_candidate"
        ),
        "last_update": {
            **last_update_calls,
            "scope": graph.metadata.get(
                "member_calls_last_update_scope",
                graph.metadata.get("member_call_telemetry_scope", "unavailable"),
            ),
        },
    }

    concept_eligible = int(graph.metadata.get("source_concepts_eligible", "0"))
    concept_linked = int(graph.metadata.get("source_concepts_linked_nodes", "0"))
    try:
        graph_report["freshness"] = inspect_saved_graph_freshness(
            directory=project_root_for_graph(resolved_graph_path),
            output_path=resolved_graph_path,
        )
    except Exception:  # noqa: BLE001 - status must never fail on a Git hiccup.
        graph_report["freshness"] = {"fresh": None}
    graph_report["concept_linking"] = {
        **concept_link_health(concept_eligible, concept_linked),
        "mode": graph.metadata.get("source_concepts_mode", "unavailable"),
        "scope": graph.metadata.get("source_concepts_scope", "unavailable"),
        "eligible_nodes": concept_eligible,
        "linked_nodes": concept_linked,
        "links": int(graph.metadata.get("source_concepts_links", "0")),
        "typed_fact_links": int(
            graph.metadata.get("source_concepts_typed_fact_links", "0")
        ),
        "exact_alias_links": int(
            graph.metadata.get("source_concepts_exact_alias_links", "0")
        ),
        "linked_concepts": int(
            graph.metadata.get("source_concepts_linked_concepts", "0")
        ),
        "coverage_ratio": float(
            graph.metadata.get("source_concepts_coverage_ratio", "0")
        ),
        "rejections": {
            "excluded_kind": int(
                graph.metadata.get("source_concepts_rejected_excluded_kind", "0")
            ),
            "no_registry_alias": int(
                graph.metadata.get("source_concepts_rejected_no_registry_alias", "0")
            ),
            "no_evidence": int(
                graph.metadata.get("source_concepts_rejected_no_evidence", "0")
            ),
        },
        "last_update": {
            "scope": graph.metadata.get(
                "source_concepts_last_update_scope", "unavailable"
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
            "typed_fact_links": int(
                graph.metadata.get("source_concepts_last_update_typed_fact_links", "0")
            ),
            "exact_alias_links": int(
                graph.metadata.get("source_concepts_last_update_exact_alias_links", "0")
            ),
            "linked_concepts": int(
                graph.metadata.get("source_concepts_last_update_linked_concepts", "0")
            ),
        },
    }
    graph_report["frontend_fallbacks"] = {
        "total": int(graph.metadata.get("frontend_fallback_count", "0")),
        "unsupported": int(graph.metadata.get("frontend_unsupported_count", "0")),
        "grammar_errors": int(
            graph.metadata.get("frontend_grammar_error_count", "0")
        ),
        "timeouts": int(graph.metadata.get("frontend_timeout_count", "0")),
        "parse_errors": int(graph.metadata.get("frontend_parse_error_count", "0")),
    }
    freshness = graph_report.get("freshness")
    return {
        "graph": graph_report,
        "package": package,
        "runtime_probes": probes,
        "runtime_notes": runtime_notes,
        "active_build": classify_active_build(
            bool(validation.ok),
            freshness if isinstance(freshness, dict) else None,
        ),
    }


__all__ = ["build_project_status", "graph_shape"]
