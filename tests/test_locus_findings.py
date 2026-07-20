from pathlib import Path

from graphgraph.concepts.doccode import summarize_doc_code_coverage
from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.planning.shape import GraphShape, adjusted_edge_density, recommend_node_budget
from graphgraph.retrieval import retrieve_context
from graphgraph.scanner.ast import _call_pattern, _callsite_pattern, extract_symbols


def test_affected_tests_query_excludes_homonym_symbol_with_no_structural_path() -> None:
    # GG-ITER-03 regression (docs/bugs/2026-07-17-locus-iterative-corpus-dogfood.md):
    # an "if X changes, which tests are affected?" query must not let the intent
    # word "affected" become a lexical anchor onto an unrelated symbol merely
    # named `affected_packages`, nor drag that symbol's tests into the validation
    # plan. structural_anchor_query strips planner vocabulary before anchoring;
    # without it, `affected_packages` and its test are pulled in purely by the
    # word "affected", producing a bogus extra test command.
    graph = Graph(
        nodes={
            # queried subsystem
            "scb": Node("scb", "SourceCaseBaseline", "class", "pipeline/baseline.py"),
            "scb_eval": Node("scb_eval", "evaluate", "method", "pipeline/baseline.py", parent="scb"),
            "scb_test": Node("scb_test", "representative_corpus_meets_expectations", "function", "tests/yield.py"),
            # unrelated subsystem whose method name collides with the intent word "affected"
            "tp": Node("tp", "TransformPlanner", "class", "frontends/planner.py"),
            "tp_affected": Node("tp_affected", "affected_packages", "method", "frontends/planner.py", parent="tp"),
            "tp_test": Node("tp_test", "planner_affected_packages_test", "function", "tests/planner.py"),
        },
        edges=[
            Edge("scb", "scb_eval", "contains"),
            Edge("scb_test", "scb_eval", "tests"),
            Edge("tp", "tp_affected", "contains"),
            Edge("tp_test", "tp_affected", "tests"),
            # deliberately NO edge connecting the two subsystems
        ],
    )

    from graphgraph.retrieval.context import structural_anchor_query
    from graphgraph.retrieval.search import search_nodes

    raw = "if SourceCaseBaseline evaluate changes, which tests are affected?"

    # Teeth: the leak this guards against is real. Without sanitizing planner
    # vocabulary, the homonym `affected_packages` is a genuine candidate -- the
    # word "affected" scores it ABOVE the correct test -- so the exclusion below
    # is a live property, not a vacuous pass.
    raw_ids = {m.node.id for m in search_nodes(graph, raw, limit=10)}
    assert "tp_affected" in raw_ids

    # Layer 1: structural_anchor_query strips planner vocabulary, so the homonym
    # is no longer a search candidate at all.
    sanitized_ids = {m.node.id for m in search_nodes(graph, structural_anchor_query(raw, "affected_tests"), limit=10)}
    assert "tp_affected" not in sanitized_ids, "sanitizer failed to strip the intent word that anchors the homonym"

    # Layer 2 (end-to-end contract): the full pipeline anchors the queried method
    # and its direct test, and excludes the homonym and its test.
    result = retrieve_context(graph, raw, "affected_tests", hops=2)
    assert "scb_eval" in result.nodes
    assert "scb_test" in result.nodes
    assert "tp_affected" not in result.nodes, "homonym symbol leaked into affected-tests packet"
    assert "tp_test" not in result.nodes, "unrelated test dragged in via the word 'affected'"


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


def test_doc_summary_flags_missing_document_extraction() -> None:
    # Slice-round finding #5: a doc_summary query against a graph built WITHOUT
    # document extraction silently returned file pointers, with no signal that
    # the graph simply lacks grounded doc bodies. Retrieval now flags the
    # missing extraction with an actionable rebuild hint (docs=true). When docs
    # ARE extracted, section/paragraph nodes exist and no hint is emitted.
    no_docs = Graph(nodes={
        "MD": Node("MD", "architecture.md", "markdown", "docs/architecture.md"),
        "F": Node("F", "refract", "function", "code.py"),
    })
    result = retrieve_context(no_docs, "how does the architecture handle refraction", "doc_summary", hops=2)
    extraction = result.metadata.get("document_extraction", {})
    assert extraction.get("grounded") is False
    assert "docs=true" in extraction.get("hint", "")

    with_docs = Graph(nodes={
        "MD": Node("MD", "architecture.md", "markdown", "docs/architecture.md"),
        "S": Node("S", "Refraction", "section", "docs/architecture.md"),
        "P": Node("P", "The refraction pass rewrites expressions", "paragraph", "docs/architecture.md"),
    })
    grounded = retrieve_context(with_docs, "how does refraction rewrite expressions", "doc_summary", hops=2)
    assert "document_extraction" not in grounded.metadata  # grounded: no hint


def test_facet_credited_by_domain_equivalent_evidence_already_in_packet() -> None:
    # GG-ITER-04 regression (docs/bugs/2026-07-17-locus-iterative-corpus-dogfood.md):
    # a facet must not be reported unfulfilled when its supporting evidence is
    # already in the packet under a domain-equivalent name. The evidence labels
    # below share NO literal token with the facet words ("yield" vs
    # "promotable_candidates", "unsafe path" vs "rejects_parent_traversal",
    # "running loaded cases" vs "load_and_run"), so only the domain-equivalence
    # mapping in _facet_evidence_queries can credit them -- these assertions fail
    # if that mapping regresses, they are not vacuous.
    from graphgraph.retrieval.context import facet_coverage, query_facets

    scenarios = [
        ("what tests catch yield loss", "min_promotable_candidates", "minimum promotable candidates threshold"),
        ("is there unsafe path rejection", "disk_backed_source_corpus_rejects_parent_traversal", "test rejects parent traversal"),
        ("does it support running loaded cases", "load_and_run_corpus_case", "loads a case from disk and runs it"),
    ]
    for query, label, summary in scenarios:
        graph = Graph(nodes={"E": Node("E", label, "function", "pipeline/x.py", summary=summary)})
        coverage = facet_coverage(graph, {"E"}, query_facets(query))
        assert not coverage["unfulfilled"], (
            f"facet wrongly unfulfilled for {query!r} despite evidence node {label!r} in packet"
        )


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

    _intercept, node_cost, edge_cost = packet_token_surface("gg")
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
    # tau = 11.9975 + 5.1632*0.05 = 12.25566 (path-aware gg LOPO refit)
    assert abs(tau - 12.25566) < 1e-9
    # lambda_ = 0.08 * 1.25 (nodes<=500) = 0.10
    # n* = (1/0.10) * ln(max(1.1, 0.10/(1e-4*12.25566))) = 44
    assert recommendation.recommended_budget == 44
    assert recommendation.mode == "candidate"
    assert recommendation.reason == (
        "Regularized budget: n*=44 (lambda=0.100, tau=12.256); small graph direct/reverse lookup"
    )
