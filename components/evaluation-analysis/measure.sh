#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the evaluation-analysis component.
#
# Metric: expected calibration error (ECE) between the confidence this system
# reports and whether it was actually right, over the hand-labeled task set.
# direction=lower. The shipped gate is ECE < 0.10.
#
# This subsystem measures other subsystems, so its own regressions are silent:
# nothing downstream fails, the numbers just quietly stop meaning what they say.
# That is why the metric is calibration error and not a pass-rate.
#
# Emits one JSON payload on stdout. When the self-graph is absent it reports
# status=unavailable rather than a fabricated number; the gate treats a broken
# instrument as a revert, not as a passing measurement.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"
TASKS="${GRAPHGRAPH_CALIBRATION_TASKS:-eval/graphgraph-calibration.json}"

"$PY" - "$GRAPH" "$TASKS" <<'PYEOF'
import datetime
import json
import sys
from pathlib import Path

graph_path = Path(sys.argv[1])
tasks_path = Path(sys.argv[2])


def emit(**fields):
    payload = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "measurement",
        "component": "evaluation-analysis",
        "metric": "answer_confidence_ece",
        "unit": "ece",
        "direction": "lower",
    }
    payload.update(fields)
    print(json.dumps(payload))
    raise SystemExit(0)


for missing, hint in ((graph_path, "graphgraph scan --depth symbols --docs"), (tasks_path, None)):
    if not missing.exists():
        reason = f"required input absent: {missing}"
        if hint:
            reason += f"; run: {hint}"
        emit(value=None, status="unavailable", reason=reason)

from graphgraph.analysis.calibration import calibration_report
from graphgraph.analysis.eval import calibration_pairs, evaluate_graph, load_eval_tasks

results = evaluate_graph(graph_path, load_eval_tasks(tasks_path))
pairs = calibration_pairs(results, complete_recall=1.0)

if not pairs:
    emit(value=None, status="unavailable", reason="task set produced zero scored predictions")

# 10 bins matches the shipped gate in tests/test_calibration.py. Reporting a
# different binning here would produce a number that silently disagrees with
# the assertion it is meant to track.
report = calibration_report(pairs, bins=10)

emit(
    value=report.ece,
    status="success",
    evidence_stage="Measured",
    gate="ece < 0.10",
    gate_pass=bool(report.ece < 0.10),
    count=report.count,
    bins=10,
    base_rate=report.base_rate,
    brier=report.brier,
    mce=report.mce,
    reliability=report.reliability,
    resolution=report.resolution,
    decomposition_residual=round(report.decomposition_residual, 9),
    tasks=str(tasks_path),
)
PYEOF
