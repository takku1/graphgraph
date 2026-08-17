from graphgraph.benchmark.relation_latency import (
    STRATA,
    measure_relation_latency_strata,
    synthetic_call_graph,
)


def test_synthetic_call_graph_has_requested_size() -> None:
    graph = synthetic_call_graph(25)
    assert len(graph.nodes) == 25
    assert len(graph.edges) == 24


def test_relation_latency_emits_three_strata_with_p50_p95() -> None:
    report = measure_relation_latency_strata(samples=8)
    assert set(report["strata"]) == {name for name, _size in STRATA}
    for name, size in STRATA:
        row = report["strata"][name]
        assert row["nodes"] == size
        assert row["p50_ms"] >= 0
        assert row["p95_ms"] >= row["p50_ms"]
    assert report["metric"] == "packed_exact_relation_p95_ms"
    assert report["value"] == report["strata"]["medium"]["p95_ms"]
