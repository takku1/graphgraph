"""GraphGraph public API, lazily loaded.

Importing this package is cheap: each public name pulls in only its own submodule
on first access (PEP 562), so ``import graphgraph`` no longer eagerly loads the
scanner (tree-sitter), concept, planning, and retrieval stacks all at once. A CLI
command, MCP call, or library user touches only the subsystems it actually uses,
which removes a large share of cold-start import overhead.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# Public name -> submodule that defines it. Order/grouping mirrors the former
# eager imports; the values are the modules that were previously imported here.
_LAZY_EXPORTS = {
    "detect_interpretation_concepts": "concepts",
    "interpretation_concept_id": "concepts",
    "canonical_concept_label": "concepts.terms",
    "concept_id": "concepts.terms",
    "normalize_label": "concepts.terms",
    "term_key": "concepts.terms",
    "Edge": "graph.core",
    "Graph": "graph.core",
    "Node": "graph.core",
    "Policy": "graph.core",
    "Query": "graph.core",
    "GraphOperation": "graph.operations",
    "add_decision_trace": "graph.operations",
    "add_edge": "graph.operations",
    "add_node": "graph.operations",
    "add_policy_node": "graph.operations",
    "append_operation": "graph.operations",
    "expire_edge": "graph.operations",
    "expire_node": "graph.operations",
    "merge_node": "graph.operations",
    "operation_from_json": "graph.operations",
    "operation_to_json": "graph.operations",
    "policy_to_node": "graph.operations",
    "read_operations": "graph.operations",
    "render_hybrid": "packets",
    "render_lowlevel": "packets",
    "render_sql": "packets",
    "ValidationResult": "packets.validation",
    "validate_packet": "packets.validation",
    "ContextPlan": "planning",
    "PacketChoice": "planning",
    "choose_packet": "planning",
    "plan_context": "planning",
    "select_policies": "planning.policies",
    "Match": "retrieval",
    "RetrievalResult": "retrieval",
    "retrieve_context": "retrieval",
    "search_nodes": "retrieval",
    "query": "services.query",
    "extract_symbols": "scanner",
    "remove_paths": "scanner",
    "scan_directory": "scanner",
    "update_paths": "scanner",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is not None:
        module = importlib.import_module(f".{module_path}", __name__)
        value = getattr(module, name)
        globals()[name] = value  # cache: __getattr__ fires once per name
        return value
    # Fall back to real submodule access (e.g. `graphgraph.scanner`) so
    # `import graphgraph; graphgraph.scanner.x` keeps working without an
    # explicit submodule import.
    try:
        submodule = importlib.import_module(f".{name}", __name__)
    except ImportError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    globals()[name] = submodule
    return submodule


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:
    # Give type checkers and IDEs the real symbols without paying import cost.
    from .concepts import detect_interpretation_concepts, interpretation_concept_id
    from .concepts.terms import canonical_concept_label, concept_id, normalize_label, term_key
    from .graph.core import Edge, Graph, Node, Policy, Query
    from .graph.operations import (
        GraphOperation,
        add_decision_trace,
        add_edge,
        add_node,
        add_policy_node,
        append_operation,
        expire_edge,
        expire_node,
        merge_node,
        operation_from_json,
        operation_to_json,
        policy_to_node,
        read_operations,
    )
    from .packets import render_hybrid, render_lowlevel, render_sql
    from .packets.validation import ValidationResult, validate_packet
    from .planning import ContextPlan, PacketChoice, choose_packet, plan_context
    from .planning.policies import select_policies
    from .retrieval import Match, RetrievalResult, retrieve_context, search_nodes
    from .scanner import extract_symbols, remove_paths, scan_directory, update_paths
    from .services.query import query

__all__ = [
    "Edge",
    "Graph",
    "GraphOperation",
    "ContextPlan",
    "Node",
    "PacketChoice",
    "Policy",
    "Query",
    "RetrievalResult",
    "ValidationResult",
    "add_decision_trace",
    "add_edge",
    "add_node",
    "add_policy_node",
    "append_operation",
    "choose_packet",
    "plan_context",
    "canonical_concept_label",
    "concept_id",
    "detect_interpretation_concepts",
    "extract_symbols",
    "expire_edge",
    "expire_node",
    "interpretation_concept_id",
    "Match",
    "merge_node",
    "normalize_label",
    "operation_from_json",
    "operation_to_json",
    "policy_to_node",
    "read_operations",
    "render_hybrid",
    "render_lowlevel",
    "render_sql",
    "retrieve_context",
    "scan_directory",
    "update_paths",
    "remove_paths",
    "search_nodes",
    "query",
    "select_policies",
    "term_key",
    "validate_packet",
]
