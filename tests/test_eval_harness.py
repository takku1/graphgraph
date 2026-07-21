from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph import Edge, Graph, Node
from graphgraph.analysis.eval import evaluate_graph, load_eval_tasks
from graphgraph.io import save_graph


def _graph_path(tmp: Path) -> Path:
    graph = Graph(
        nodes={
            "wsgi": Node("wsgi", "wsgi_app", "function", "src/app.py", "L10"),
            "full": Node("full", "full_dispatch_request", "function", "src/app.py", "L20"),
            "teardown": Node("teardown", "do_teardown_request", "function", "src/ctx.py", "L30"),
        },
        edges=[Edge("wsgi", "full", "calls"), Edge("full", "teardown", "calls")],
    )
    path = tmp / "graph.json"
    save_graph(graph, path)
    return path


def _tasks(tmp: Path, payload: list[dict]) -> Path:
    path = tmp / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class EvalHarnessTest(unittest.TestCase):
    """The harness must be able to fail. A green number it cannot lose is a lie."""

    def test_nonexistent_expected_symbols_score_zero(self) -> None:
        # The red test. This reported node_recall 1.0 for symbols that do not
        # exist anywhere in the graph, because `expected` was read under a
        # different key and an empty expectation set scored as vacuously
        # perfect. In CI that is a green light over a suite measuring nothing.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = _graph_path(root)
            tasks = load_eval_tasks(_tasks(root, [{
                "query": "database connection pooling retry backoff",
                "expected": ["zzz_nonexistent_alpha", "zzz_nonexistent_beta"],
            }]))
            result = evaluate_graph(graph_path, tasks)[0]

        self.assertEqual(result.node_recall, 0.0)
        self.assertTrue(result.scored)

    def test_real_expected_symbols_score_above_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = _graph_path(root)
            tasks = load_eval_tasks(_tasks(root, [{
                "query": "what calls full_dispatch_request",
                "expected": ["wsgi_app"],
            }]))
            result = evaluate_graph(graph_path, tasks)[0]

        self.assertGreater(result.node_recall or 0.0, 0.0)

    def test_missing_expectations_are_reported_unscored_not_perfect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = _graph_path(root)
            tasks = load_eval_tasks(_tasks(root, [{"query": "anything at all"}]))
            result = evaluate_graph(graph_path, tasks)[0]

        self.assertIsNone(result.node_recall)
        self.assertFalse(result.scored)
        self.assertIn("expected", result.note)

    def test_expected_nodes_key_still_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = load_eval_tasks(_tasks(root, [{
                "query": "q", "expected_nodes": ["wsgi_app"],
            }]))
        self.assertEqual(tasks[0].expected_nodes, ("wsgi_app",))

    def test_query_class_is_routed_not_a_fixed_default(self) -> None:
        # Every task previously classified `blast_radius`, so a suite could not
        # tell whether routing worked at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = _graph_path(root)
            tasks = load_eval_tasks(_tasks(root, [
                {"query": "what calls full_dispatch_request", "expected": ["wsgi_app"]},
                {"query": "how does request teardown work overall", "expected": ["do_teardown_request"]},
            ]))
            classes = {r.query_class for r in evaluate_graph(graph_path, tasks)}

        self.assertGreater(len(classes), 1, f"routing did not discriminate: {classes}")
        self.assertNotIn("auto", classes)


if __name__ == "__main__":
    unittest.main()
