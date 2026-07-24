"""Enforce the path-to-10 quality gates against the scanned self-graph.

Run in CI after ``graphgraph scan``. Exits non-zero if any gate regresses, so the
gates are load-bearing rather than merely measured:

  * self-eval    -- every real task meets node recall, and the RED control still
                    scores exactly zero (an eval that cannot fail is not a gate);
  * calibration  -- answer-confidence ECE stays under 0.10 on the labeled
                    pass/fail set (``eval/graphgraph-calibration.json``).

The extraction ``calls_per_symbol`` floor is already enforced inside the pytest
suite (test_benchmark), so it is not repeated here.
"""

from __future__ import annotations

import sys
from pathlib import Path

from graphgraph.analysis.calibration import calibration_report
from graphgraph.analysis.eval import calibration_pairs, evaluate_graph, load_eval_tasks

GRAPH = Path(".graphgraph/graph.gg")
ECE_CEILING = 0.10
RECALL_FLOOR = 0.99


def main() -> int:
    if not GRAPH.exists():
        print(f"no scanned graph at {GRAPH}; run `graphgraph scan --docs` first", file=sys.stderr)
        return 1

    failures: list[str] = []

    self_results = evaluate_graph(GRAPH, load_eval_tasks(Path("eval/graphgraph-self.json")))
    real = [r for r in self_results if "RED TEST" not in r.query and r.node_recall is not None]
    red = [r for r in self_results if "RED TEST" in r.query]
    if not all(r.node_recall >= RECALL_FLOOR for r in real):
        failures.append(
            "self-eval recall regressed: "
            + ", ".join(f"{r.query[:32]!r}={r.node_recall}" for r in real if r.node_recall < RECALL_FLOOR)
        )
    if not (red and all(r.node_recall == 0.0 for r in red)):
        failures.append("RED control no longer scores zero -- the eval can be fooled")

    calibration = calibration_report(
        calibration_pairs(
            evaluate_graph(GRAPH, load_eval_tasks(Path("eval/graphgraph-calibration.json"))),
            complete_recall=1.0,
        ),
        bins=10,
    )
    print(f"self-eval: {len(real)} real tasks, {len(red)} RED control")
    print(f"calibration ECE = {calibration.ece:.4f} (ceiling {ECE_CEILING})")
    if calibration.ece >= ECE_CEILING:
        failures.append(f"answer-confidence ECE {calibration.ece:.4f} >= {ECE_CEILING}")

    if failures:
        print("QUALITY GATES FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("all quality gates pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
