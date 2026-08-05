from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from graphgraph.analysis.navigation import NavigationEvalError, evaluate_navigation
from graphgraph.cli.parser import build_parser


class NavigationEvalTest(unittest.TestCase):
    def _tasks(self) -> dict[str, object]:
        return {
            "tasks": [{
                "id": "cold-1",
                "stratum": "cold_orientation",
                "relevant_regions": [{"path": "src/pkg/api.py", "start_line": 1, "end_line": 10}],
                "facets": ["languages", "entry_points"],
                "budget": {"source_lines": 100, "tokens": 1000, "actions": 10, "milliseconds": 1000},
            }]
        }

    def _runs(self) -> dict[str, object]:
        return {
            "runs": [
                {
                    "task_id": "cold-1",
                    "strategy": "rg+get-content",
                    "regions": [
                        {"path": "src/noise.py", "start_line": 1, "end_line": 20},
                        {"path": "src/pkg/api.py", "start_line": 1, "end_line": 5},
                    ],
                    "facets": ["languages"],
                    "source_lines": 100,
                    "tokens": 800,
                    "actions": 8,
                    "milliseconds": 800,
                    "complete_claimed": True,
                },
                {
                    "task_id": "cold-1",
                    "strategy": "graphgraph-atlas",
                    "regions": [{"path": "src/pkg/api.py", "start_line": 1, "end_line": 10}],
                    "facets": ["languages", "entry_points"],
                    "source_lines": 20,
                    "tokens": 200,
                    "actions": 2,
                    "milliseconds": 200,
                    "complete_claimed": True,
                },
            ]
        }

    def test_equal_budget_report_exposes_quality_cost_and_stopping_failures(self) -> None:
        report = evaluate_navigation(self._tasks(), self._runs())
        rows = {row["strategy"]: row for row in report["results"]}

        self.assertEqual(report["schema"], "navigation_eval_v1")
        self.assertEqual(rows["rg+get-content"]["line_coverage"], 0.5)
        self.assertEqual(rows["rg+get-content"]["facet_completeness"], 0.5)
        self.assertTrue(rows["rg+get-content"]["false_complete"])
        self.assertEqual(rows["graphgraph-atlas"]["line_coverage"], 1.0)
        self.assertFalse(rows["graphgraph-atlas"]["false_complete"])
        self.assertLess(
            rows["graphgraph-atlas"]["navigation_loss"],
            rows["rg+get-content"]["navigation_loss"],
        )
        self.assertEqual(report["strategies"]["graphgraph-atlas"]["within_line_budget_rate"], 1.0)

    def test_unknown_task_and_unknown_weight_fail_closed(self) -> None:
        with self.assertRaisesRegex(NavigationEvalError, "unknown task_id"):
            evaluate_navigation(self._tasks(), {"runs": [{"task_id": "missing", "strategy": "x"}]})
        with self.assertRaisesRegex(NavigationEvalError, "unknown navigation-loss weight"):
            evaluate_navigation(self._tasks(), self._runs(), profile_payload={"magic": 1})

    def test_cli_scores_trace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            runs = root / "runs.json"
            tasks.write_text(json.dumps(self._tasks()), encoding="utf-8")
            runs.write_text(json.dumps(self._runs()), encoding="utf-8")
            args = build_parser().parse_args([
                "navigation-eval", "--tasks", str(tasks), "--runs", str(runs)
            ])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                args.func(args)
            payload = json.loads(stdout.getvalue())

        self.assertIn("graphgraph-atlas", payload["strategies"])
        self.assertIn("rg+get-content", payload["strategies"])


if __name__ == "__main__":
    unittest.main()
