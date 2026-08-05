"""Graph analysis: shape/diff summaries and retrieval evaluation."""

from .calibration import (
    CalibrationReport,
    ReliabilityBin,
    apply_isotonic,
    calibration_report,
    pav_isotonic,
    reliability_table,
)
from .eval import (
    EvalResult,
    EvalTask,
    calibration_pairs,
    evaluate_graph,
    load_eval_tasks,
    ndcg_at_k,
    rank_nodes_by_subgraph_pagerank,
    reciprocal_rank,
    results_to_json,
    results_with_calibration_to_json,
)
from .metrics import GraphComparison, GraphSummary, compare_graphs, summarize_graph
from .navigation import NavigationEvalError, evaluate_navigation, evaluate_navigation_files

__all__ = [
    "EvalResult",
    "EvalTask",
    "CalibrationReport",
    "GraphComparison",
    "GraphSummary",
    "NavigationEvalError",
    "ReliabilityBin",
    "apply_isotonic",
    "calibration_pairs",
    "calibration_report",
    "compare_graphs",
    "evaluate_graph",
    "evaluate_navigation",
    "evaluate_navigation_files",
    "load_eval_tasks",
    "ndcg_at_k",
    "rank_nodes_by_subgraph_pagerank",
    "reciprocal_rank",
    "reliability_table",
    "pav_isotonic",
    "results_with_calibration_to_json",
    "results_to_json",
    "summarize_graph",
]
