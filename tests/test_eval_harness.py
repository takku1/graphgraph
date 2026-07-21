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


class SelfEvalSuiteTest(unittest.TestCase):
    """The committed suite must keep proving the instrument can fail.

    Gate 0 of the gray-box evaluation asked for a task suite with
    hand-verified ground truth *and* a red case, because a harness that
    always reports success is worse than no harness -- it produces confident
    green numbers over a system that has silently regressed.
    """

    SUITE = Path("eval/graphgraph-self.json")

    def test_suite_is_parsed_and_every_task_is_scorable(self) -> None:
        tasks = load_eval_tasks(self.SUITE)
        self.assertGreaterEqual(len(tasks), 5)
        for task in tasks:
            self.assertTrue(
                task.expected_nodes,
                f"task {task.query!r} has no expectations and would score nothing",
            )

    def test_suite_contains_a_red_task_that_cannot_pass(self) -> None:
        tasks = load_eval_tasks(self.SUITE)
        red = [t for t in tasks if any("zzz_nonexistent" in item for item in t.expected_nodes)]
        self.assertTrue(red, "the suite must retain a task that is designed to fail")

    def test_red_task_scores_zero_against_the_real_graph(self) -> None:
        # Skips rather than fails when the graph has not been built, so the
        # suite never blocks a fresh checkout -- but runs for real in any
        # environment that has scanned this repository.
        graph_path = Path(".graphgraph/graph.gg")
        if not graph_path.exists():
            self.skipTest("no graph built for this repository")

        results = evaluate_graph(graph_path, load_eval_tasks(self.SUITE))
        red = [r for r in results if "RED TEST" in r.query]
        self.assertEqual(len(red), 1)
        self.assertEqual(red[0].node_recall, 0.0)

        scored = [r for r in results if "RED TEST" not in r.query]
        self.assertTrue(
            all((r.node_recall or 0.0) > 0.0 for r in scored),
            f"hand-verified expectations regressed: "
            f"{[(r.query, r.node_recall) for r in scored if not r.node_recall]}",
        )
