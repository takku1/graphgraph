"""Graph analysis: shape/diff summaries and retrieval evaluation."""

from .eval import (
    EvalResult,
    EvalTask,
    evaluate_graph,
    load_eval_tasks,
    ndcg_at_k,
    rank_nodes_by_subgraph_pagerank,
    reciprocal_rank,
    results_to_json,
)
from .metrics import GraphComparison, GraphSummary, compare_graphs, summarize_graph

__all__ = [
    "EvalResult",
    "EvalTask",
    "GraphComparison",
    "GraphSummary",
    "compare_graphs",
    "evaluate_graph",
    "load_eval_tasks",
    "ndcg_at_k",
    "rank_nodes_by_subgraph_pagerank",
    "reciprocal_rank",
    "results_to_json",
    "summarize_graph",
]
