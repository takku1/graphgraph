"""Experimental research contracts that are not production retrieval defaults."""

from .attention_field import (
    FIELD_COUPLINGS,
    CoverPlan,
    Hierarchy,
    compile_greedy_cover,
    compile_greedy_formula_cover,
    compile_optimal_cover,
    compile_optimal_formula_cover,
    effective_influence_receipt,
    evaluate_cover,
    evaluate_top_k,
    exact_influence_field,
    field_support_receipt,
    influence_field,
)
from .registry import load_research_registry, validate_research_registry
from .static_cover import (
    PathHierarchy,
    build_path_hierarchy,
    evaluate_expected_resolution,
    render_cover_plan,
    render_exact_nodes,
    select_flat_nodes_at_token_budget,
)

__all__ = [
    "FIELD_COUPLINGS",
    "CoverPlan",
    "Hierarchy",
    "PathHierarchy",
    "build_path_hierarchy",
    "compile_greedy_cover",
    "compile_greedy_formula_cover",
    "compile_optimal_cover",
    "compile_optimal_formula_cover",
    "effective_influence_receipt",
    "evaluate_cover",
    "evaluate_expected_resolution",
    "evaluate_top_k",
    "exact_influence_field",
    "field_support_receipt",
    "influence_field",
    "load_research_registry",
    "render_cover_plan",
    "render_exact_nodes",
    "select_flat_nodes_at_token_budget",
    "validate_research_registry",
]
