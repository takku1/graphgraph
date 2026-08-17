"""Held-out receiver oracles beyond the synthetic same-file 7-language fixture."""

from __future__ import annotations

from pathlib import Path

from graphgraph import scan_directory


HELDOUT = Path(__file__).resolve().parent / "corpus" / "heldout-receivers"


def _member_calls(graph):
    return [
        edge
        for edge in graph.edges
        if edge.type == "calls"
        and graph.nodes[edge.source].kind in {"function", "method"}
        and graph.nodes[edge.target].kind == "method"
        and "tree_sitter_type_resolved" in (edge.provenance or "")
    ]


def _owner_label(graph, node_id: str) -> str:
    node = graph.nodes[node_id]
    if node.parent and node.parent in graph.nodes:
        return graph.nodes[node.parent].label
    return ""


def test_heldout_typescript_inherited_save_is_exact() -> None:
    graph = scan_directory(HELDOUT / "ts", depth="symbols", frontend="tree_sitter")
    calls = {
        (graph.nodes[edge.source].label, graph.nodes[edge.target].label)
        for edge in _member_calls(graph)
    }
    assert ("persist", "save") in calls
    owners = {
        _owner_label(graph, edge.target)
        for edge in _member_calls(graph)
        if graph.nodes[edge.source].label == "persist"
    }
    assert owners == {"Store"}


def test_heldout_csharp_inherited_save_is_exact() -> None:
    graph = scan_directory(HELDOUT / "cs", depth="symbols", frontend="tree_sitter")
    calls = {
        (graph.nodes[edge.source].label, graph.nodes[edge.target].label)
        for edge in _member_calls(graph)
    }
    assert ("Persist", "Save") in calls
    owners = {
        _owner_label(graph, edge.target)
        for edge in _member_calls(graph)
        if graph.nodes[edge.source].label == "Persist"
    }
    assert owners == {"Store"}


def test_heldout_python_inherited_save_is_exact() -> None:
    graph = scan_directory(HELDOUT / "py", depth="symbols", frontend="tree_sitter")
    calls = {
        (graph.nodes[edge.source].label, graph.nodes[edge.target].label)
        for edge in _member_calls(graph)
    }
    assert ("persist", "save") in calls
    owners = {
        _owner_label(graph, edge.target)
        for edge in _member_calls(graph)
        if graph.nodes[edge.source].label == "persist"
    }
    assert owners == {"Store"}


def test_heldout_go_inherited_save_is_exact() -> None:
    graph = scan_directory(HELDOUT / "go", depth="symbols", frontend="tree_sitter")
    calls = {
        (graph.nodes[edge.source].label, graph.nodes[edge.target].label)
        for edge in _member_calls(graph)
    }
    assert ("Persist", "Save") in calls
    owners = {
        _owner_label(graph, edge.target)
        for edge in _member_calls(graph)
        if graph.nodes[edge.source].label == "Persist"
    }
    assert owners == {"Store"}


def test_heldout_resolved_member_calls_have_unit_precision() -> None:
    """Every type-resolved edge on this panel names a method on the receiver lineage."""

    expected = {
        "ts": {("persist", "save", "Store")},
        "cs": {("Persist", "Save", "Store")},
        "py": {("persist", "save", "Store")},
        "go": {("Persist", "Save", "Store")},
    }
    for language, wanted in expected.items():
        graph = scan_directory(HELDOUT / language, depth="symbols", frontend="tree_sitter")
        observed = {
            (
                graph.nodes[edge.source].label,
                graph.nodes[edge.target].label,
                _owner_label(graph, edge.target),
            )
            for edge in _member_calls(graph)
        }
        assert wanted <= observed
        # Precision: no type-resolved edge points at a same-named method on
        # an unrelated owner. This panel only declares one lineage.
        assert all(item[2] == "Store" for item in observed)
