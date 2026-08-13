"""Public context-retrieval Interface over private in-process phases."""

from __future__ import annotations

from pathlib import Path

from ..graph.core import Graph
from .anchor_search import _execute_anchor_search
from .models import RetrievalResult
from .request_feasibility import _request_feasibility
from .result_assembly import _assemble_retrieval_result


def retrieve_context(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    seed_ids: tuple[str, ...] = (),
    anchor_paths: tuple[str, ...] = (),
    activation_state_path: Path | None = None,
) -> RetrievalResult:
    feasibility = _request_feasibility(
        graph, query, query_class, hops, anchor_limit, max_nodes, scopes, scope_mode, anchor_paths
    )
    if isinstance(feasibility, RetrievalResult):
        return feasibility
    selection = _execute_anchor_search(graph, feasibility, max_nodes=max_nodes, seed_ids=seed_ids)
    if isinstance(selection, RetrievalResult):
        return selection
    return _assemble_retrieval_result(graph, selection, activation_state_path=activation_state_path)
