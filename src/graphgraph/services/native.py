"""Compatibility facade for the decomposed native service domains."""

from . import freshness as _freshness
from . import project_status as _project_status
from . import runtime_probes as _runtime_probes
from .lifecycle import (
    GraphBuildStatus,
    ensure_native_graph,
    manifest_path_for_graph,
    refresh_saved_graph,
    remove_paths_validated_graph,
    scan_validated_graph,
    update_paths_validated_graph,
)
from .native_context import render_native_context

inspect_saved_graph_freshness = _freshness.inspect_saved_graph_freshness
refresh_receipt = _freshness.refresh_receipt
scope_freshness = _freshness.scope_freshness
_read_package_status = _runtime_probes._read_package_status
_resolve_cargo_workspace_members = _runtime_probes._resolve_cargo_workspace_members
_run_package_probes = _runtime_probes._run_package_probes
_run_probe = _runtime_probes._run_probe
_runtime_notes = _runtime_probes._runtime_notes
_absent_graph_status = _project_status._absent_graph_status
_member_call_snapshot = _project_status._member_call_snapshot
_parse_receiver_classes = _project_status._parse_receiver_classes
_symbol_extraction_status = _project_status._symbol_extraction_status
build_project_status = _project_status.build_project_status
graph_shape = _project_status.graph_shape

__all__ = [
    "GraphBuildStatus",
    "build_project_status",
    "ensure_native_graph",
    "graph_shape",
    "inspect_saved_graph_freshness",
    "manifest_path_for_graph",
    "refresh_receipt",
    "refresh_saved_graph",
    "remove_paths_validated_graph",
    "render_native_context",
    "scan_validated_graph",
    "scope_freshness",
    "update_paths_validated_graph",
]
