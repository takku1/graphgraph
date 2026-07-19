from __future__ import annotations

import unittest

from graphgraph.acceptance.quality import (
    BASELINE_PATH,
    QUALITY_QUERIES,
    QualityMetrics,
    compare,
    load_baseline,
    measure,
    run_quality,
)


class QualityMachineryTest(unittest.TestCase):
    def test_metrics_are_well_formed(self) -> None:
        for query in QUALITY_QUERIES:
            with self.subTest(query=query.id):
                m = measure(query)
                self.assertGreater(m.tokens, 0)
                self.assertGreaterEqual(m.nodes, 1)
                self.assertTrue(0.0 <= m.recall <= 1.0)
                if m.precision is not None:
                    self.assertTrue(0.0 <= m.precision <= 1.0)

    def test_required_facts_are_recalled(self) -> None:
        # If any fixture query cannot recall its own facts, the metric is broken.
        for query in QUALITY_QUERIES:
            with self.subTest(query=query.id):
                self.assertEqual(measure(query).recall, 1.0)


class QualityRegressionGateTest(unittest.TestCase):
    """Deterministic gate: tokens must not rise and recall must not fall vs the
    committed baseline. A legitimate improvement (fewer tokens) passes; refresh the
    baseline with `python -m graphgraph.acceptance.quality baseline` when intended."""

    def test_no_token_or_recall_regression_against_baseline(self) -> None:
        self.assertTrue(BASELINE_PATH.exists(), "run: python -m graphgraph.acceptance.quality baseline")
        regressions = compare(run_quality(), load_baseline())
        self.assertEqual(regressions, [], [f"{r.query}: {r.reason} {r.baseline}->{r.current}" for r in regressions])

    def test_quality_gain_can_pay_for_more_tokens(self) -> None:
        metrics = QualityMetrics(
            query="q",
            tokens=120,
            precise_tokens=150,
            nodes=3,
            precision=1.0,
            required=2,
            present=2,
            recall=1.0,
            density=1.6667,
        )
        baseline = {
            "q": {
                "tokens": 100,
                "precision": 0.5,
                "recall": 0.5,
            }
        }
        self.assertEqual(compare({"q": metrics}, baseline), [])


if __name__ == "__main__":
    unittest.main()
