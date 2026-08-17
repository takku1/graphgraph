"""OW-D-01: runtime coverage ingestion on an Express-shaped fixture.

Fixtures prove provenance preservation. A live Express mocha/nyc run is not
required to show that V8 and Istanbul coverage become observed_calls with
runtime_trace provenance distinct from static calls.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.platform.tracing import ingest_runtime_trace


def _express_graph() -> Graph:
    return Graph(
        nodes={
            "CREATE": Node("CREATE", "createApplication", "function", "lib/express.js"),
            "HANDLE": Node("HANDLE", "handle", "function", "lib/application.js"),
            "ROUTE_HANDLE": Node("ROUTE_HANDLE", "handle", "function", "lib/router/index.js"),
            "TEST": Node("TEST", "it", "function", "test/app.router.js"),
        },
        edges=[
            Edge("TEST", "HANDLE", "calls", provenance="static"),
        ],
    )


def _istanbul_fixture() -> dict[str, object]:
    return {
        "/repo/express/lib/application.js": {
            "path": "/repo/express/lib/application.js",
            "fnMap": {
                "0": {
                    "name": "handle",
                    "decl": {"start": {"line": 152, "column": 0}, "end": {"line": 178, "column": 1}},
                    "loc": {"start": {"line": 152, "column": 0}, "end": {"line": 178, "column": 1}},
                },
                "1": {
                    "name": "(anonymous_1)",
                    "loc": {"start": {"line": 200, "column": 0}, "end": {"line": 201, "column": 1}},
                },
            },
            "f": {"0": 4, "1": 2},
        },
        "/repo/express/lib/express.js": {
            "path": "/repo/express/lib/express.js",
            "fnMap": {
                "0": {
                    "name": "createApplication",
                    "loc": {"start": {"line": 36, "column": 0}, "end": {"line": 40, "column": 1}},
                },
                "1": {
                    "name": "unusedHelper",
                    "loc": {"start": {"line": 80, "column": 0}, "end": {"line": 82, "column": 1}},
                },
            },
            "f": {"0": 1, "1": 0},
        },
    }


def _v8_fixture() -> dict[str, object]:
    return {
        "result": [
            {
                "scriptId": "12",
                "url": "file:///repo/express/lib/application.js",
                "functions": [
                    {
                        "functionName": "app.handle",
                        "isBlockCoverage": True,
                        "ranges": [{"startOffset": 10, "endOffset": 80, "count": 3}],
                    },
                    {
                        "functionName": "",
                        "isBlockCoverage": True,
                        "ranges": [{"startOffset": 80, "endOffset": 90, "count": 1}],
                    },
                ],
            },
            {
                "scriptId": "13",
                "url": "file:///repo/express/lib/express.js",
                "functions": [
                    {
                        "functionName": "createApplication",
                        "isBlockCoverage": True,
                        "ranges": [{"startOffset": 0, "endOffset": 40, "count": 1}],
                    }
                ],
            },
        ]
    }


def test_istanbul_express_coverage_emits_observed_calls_with_runtime_provenance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "coverage-final.json"
        path.write_text(json.dumps(_istanbul_fixture()), encoding="utf-8")
        graph, receipt = ingest_runtime_trace(_express_graph(), path)

    observed = [edge for edge in graph.edges if edge.type == "observed_calls"]
    static = [edge for edge in graph.edges if edge.type == "calls"]
    targets = {graph.nodes[edge.target].label for edge in observed}
    assert receipt["format"] == "istanbul_coverage"
    assert receipt["edges_emitted"] == 2
    assert targets == {"handle", "createApplication"}
    assert all(edge.provenance == "runtime_trace" for edge in observed)
    assert all(edge.evidence == "istanbul_coverage" for edge in observed)
    assert static[0].provenance == "static"
    handle_edge = next(edge for edge in observed if graph.nodes[edge.target].id == "HANDLE")
    assert handle_edge.source_location.endswith("lib/application.js:152")
    assert "unusedHelper" not in targets


def test_v8_express_coverage_disambiguates_same_named_handle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "coverage.json"
        path.write_text(json.dumps(_v8_fixture()), encoding="utf-8")
        graph, receipt = ingest_runtime_trace(_express_graph(), path)

    observed = [edge for edge in graph.edges if edge.type == "observed_calls"]
    handle_targets = {edge.target for edge in observed if graph.nodes[edge.target].label == "handle"}
    assert receipt["format"] == "v8_coverage"
    assert handle_targets == {"HANDLE"}
    assert any(graph.nodes[edge.target].label == "createApplication" for edge in observed)
    assert all(edge.provenance == "runtime_trace" for edge in observed)


def test_empty_coverage_file_emits_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "coverage-final.json"
        path.write_text("", encoding="utf-8")
        graph, receipt = ingest_runtime_trace(_express_graph(), path)
    assert receipt["format"] == "empty"
    assert receipt["edges_emitted"] == 0
    assert receipt["events"] == 0
    assert not any(edge.type == "observed_calls" for edge in graph.edges)


def test_source_planner_discovers_istanbul_coverage_final() -> None:
    from graphgraph.io import save_graph
    from graphgraph.platform.source_planner import QuerySourcePlanner

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        graph_path = root / "graph.json"
        save_graph(_express_graph(), graph_path)
        (root / "coverage").mkdir()
        (root / "coverage" / "coverage-final.json").write_text(
            json.dumps(_istanbul_fixture()),
            encoding="utf-8",
        )
        plan = QuerySourcePlanner(root, graph_path=graph_path).plan(
            _express_graph(),
            "runtime coverage of handle",
            mode="all",
        )
    assert "runtime_trace" in plan.receipt.sources
    assert plan.receipt.trace_edges >= 1
    assert any(edge.type == "observed_calls" for edge in plan.graph.edges)


def test_native_jsonl_trace_still_resolves_caller_callee() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "runtime-trace.jsonl"
        path.write_text(
            json.dumps({"caller": "it", "callee": "handle", "count": 2, "location": "lib/application.js"})
            + "\n",
            encoding="utf-8",
        )
        graph, receipt = ingest_runtime_trace(_express_graph(), path)
    observed = next(edge for edge in graph.edges if edge.type == "observed_calls")
    assert receipt["format"] == "jsonl"
    assert observed.source == "TEST"
    assert observed.target == "HANDLE"
    assert observed.weight == 2
    assert observed.provenance == "runtime_trace"
