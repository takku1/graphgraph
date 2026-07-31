"""Canonical construction for GraphGraph compiler runtimes."""

from __future__ import annotations

from pathlib import Path

from ..graph.core import Graph
from ..io import load_any, project_root_for_graph
from .compiler import GraphRuntime
from .contracts import EvidenceProvider, StructuralEvidenceProvider
from .source_planner import QuerySourcePlanner

DEFAULT_SOURCE_MODE = "auto"
DEFAULT_MEMORY_SCOPES = ("project", "session")


def create_graph_runtime(
    graph_path: Path | None,
    *,
    graph: Graph | None = None,
    providers: tuple[EvidenceProvider, ...] | None = None,
    enable_evidence: bool = True,
    evidence_store_path: Path | None = None,
    changed_paths: tuple[str, ...] = (),
    refresh_evidence: bool = False,
    source_planning: bool = True,
    source_mode: str = DEFAULT_SOURCE_MODE,
    memory_scopes: tuple[str, ...] = DEFAULT_MEMORY_SCOPES,
) -> GraphRuntime:
    """Build a runtime with consistent providers, stores, and source planning.

    Callers retain transport parsing and request bounds. This factory owns only
    compilation dependencies and their project-relative defaults.
    """
    resolved = Path(graph_path) if graph_path is not None else None
    if graph is None:
        if resolved is None:
            raise ValueError("graph or graph_path is required")
        graph = load_any(resolved)

    active_providers = providers
    if active_providers is None:
        if enable_evidence:
            from .cpg import CpgEvidenceProvider

        active_providers = (
            (StructuralEvidenceProvider(), CpgEvidenceProvider())
            if enable_evidence
            else ()
        )
    evidence_store = None
    if enable_evidence and resolved is not None:
        from .evidence_store import EvidenceStore

        evidence_store = EvidenceStore(evidence_store_path or resolved.parent / "evidence.db")
    source_planner = None
    if source_planning and resolved is not None:
        source_planner = QuerySourcePlanner(
            project_root_for_graph(resolved),
            graph_path=resolved,
        )

    return GraphRuntime(
        graph,
        active_providers,
        evidence_store=evidence_store,
        changed_paths=changed_paths,
        refresh_evidence=refresh_evidence,
        source_planner=source_planner,
        source_mode=source_mode,
        memory_scopes=memory_scopes,
    )
