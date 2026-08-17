#!/usr/bin/env bash
# measure.sh -- corpus extraction cost over a fixed in-repo subtree.
# A bounded, repeatable scan: the whole-repo number is dominated by corpus size
# rather than by frontend cost, so it cannot gate a frontend change.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

"$PY" - <<'PYEOF'
import datetime, json
from graphgraph.scanner.resolution_report import heldout_precision_table

report = heldout_precision_table()
status = "success" if report["value"] >= report["target"] else "fail"
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement",
    "component": "static-analysis",
    "metric": report["metric"],
    "value": report["value"],
    "unit": "ratio",
    "direction": report["direction"],
    "evidence_stage": "Measured",
    "status": status,
    "target": report["target"],
    "recall": report["recall"],
    "by_language": report["by_language"],
    "hits": report["hits"],
    "expected": report["expected"],
    "false_owners": report["false_owners"],
}))
if status != "success":
    raise SystemExit(1)
PYEOF
