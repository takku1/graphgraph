#!/usr/bin/env bash
# measure.sh -- held-out member-call resolution precision.
# The header previously described "corpus extraction cost over a fixed in-repo
# subtree", which this script has never measured; it emits the resolution
# precision ratio below. Extraction throughput is a separate concern and is
# reported by tests/test_benchmark.py under GRAPHGRAPH_TIMING_GATES=1, because
# wall-clock belongs in a deliberate measurement run rather than in a
# correctness suite that must be deterministic.
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
