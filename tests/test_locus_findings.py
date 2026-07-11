from pathlib import Path

from graphgraph.core import Edge, Graph, Node
from graphgraph.doccode import summarize_doc_code_coverage
from graphgraph.planning.shape import GraphShape, adjusted_edge_density, recommend_node_budget
from graphgraph.scanner.ast import _call_pattern, _callsite_pattern, extract_symbols


def test_graph_directional_edge_caches_invalidate_when_edges_change() -> None:
    graph = Graph(
        nodes={
            "A": Node("A", "A"),
            "B": Node("B", "B"),
            "C": Node("C", "C"),
        },
        edges=[Edge("A", "B", "calls")],
    )

    assert [edge.target for edge in graph.outgoing()["A"]] == ["B"]
    assert [edge.source for edge in graph.incoming()["B"]] == ["A"]

    graph.edges.append(Edge("C", "B", "calls"))

    assert [edge.source for edge in graph.incoming()["B"]] == ["A", "C"]
    assert [edge.target for edge in graph.outgoing()["C"]] == ["B"]


def test_scanner_python_function_refactor_preserves_sync_async_and_methods() -> None:
    text = """
class Service:
    def method(self):
        helper()

async def worker():
    return 1

def helper():
    return worker()
"""
    nodes, edges, _truncated = extract_symbols(
        [(Path("pkg/service.py"), "pkg/service.py", "file_pkg/service.py", text)],
        max_total_symbols=100,
    )

    by_label = {node.label: node for node in nodes.values()}
    assert by_label["Service"].kind == "class"
    assert by_label["method"].kind == "method"
    assert by_label["worker"].kind == "function"
    assert by_label["helper"].kind == "function"
    assert any(edge.source == by_label["method"].id and edge.target == by_label["helper"].id for edge in edges)


def test_scanner_call_patterns_keep_reference_and_callsite_semantics() -> None:
    names = ["load", "load_all"]

    ref_pattern = _call_pattern(names)
    call_pattern = _callsite_pattern(names)

    assert ref_pattern is not None
    assert call_pattern is not None
    assert ref_pattern.search("load_all")
    assert not ref_pattern.search("preload")
    assert call_pattern.search("load_all(data)")
    assert not call_pattern.search("module.load_all(data)")


def test_doc_code_pairing_sort_order_is_stable_after_sort_key_refactor() -> None:
    graph = Graph(
        nodes={
            "doc_a": Node("doc_a", "Alpha", "section", "docs/alpha.md"),
            "code_a": Node("code_a", "Alpha", "function", "src/alpha.py"),
            "doc_b": Node("doc_b", "Beta", "section", "docs/beta.md"),
            "code_b": Node("code_b", "Beta", "function", "src/beta.py"),
            "code_b2": Node("code_b2", "Beta", "method", "src/beta.py"),
        },
    )

    coverage = summarize_doc_code_coverage(graph)

    assert [pair.key for pair in coverage.paired_examples[:2]] == ["beta", "alpha"]


def test_budget_density_denominator_is_positive_for_valid_shapes() -> None:
    shape = GraphShape(
        nodes=100,
        edges=0,
        source_files=10,
        symbol_nodes=80,
        doc_nodes=10,
        import_edges=0,
        calls_edges=0,
        explains_edges=0,
        edge_density=0.0,
        imports_per_source_file=0.0,
        calls_per_symbol=0.0,
        weak_edge_ratio=0.0,
        doc_node_ratio=0.1,
        top_node_kinds=(),
        top_relations=(),
    )

    from graphgraph.planning.token_cost import packet_token_surface

    _intercept, node_cost, edge_cost = packet_token_surface("gg_max")
    density = adjusted_edge_density(shape)
    tau = node_cost + edge_cost * density
    recommendation = recommend_node_budget("direct_lookup", "", shape)

    assert density >= 0.05
    assert tau > 0.0
    assert recommendation.recommended_budget is not None

    # Pin the actual numeric values the closed-form n* used, not just their sign/existence:
    # noise_factor=1.0+0.30*0(weak_edge_ratio)+0.20*0.1(doc_node_ratio)=1.02; raw_density=0.0
    # -> clamped to the 0.05 floor since raw_density*noise_factor==0.0.
    assert density == 0.05
    # tau = 11.9975 + 5.1632*0.05 = 12.25566 (path-aware gg_max LOPO refit)
    assert abs(tau - 12.25566) < 1e-9
    # lambda_ = 0.08 * 1.25 (nodes<=500) = 0.10
    # n* = (1/0.10) * ln(max(1.1, 0.10/(1e-4*12.25566))) = 44
    assert recommendation.recommended_budget == 44
    assert recommendation.mode == "candidate"
    assert recommendation.reason == (
        "Regularized budget: n*=44 (lambda=0.100, tau=12.256); small graph direct/reverse lookup"
    )
