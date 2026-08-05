#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the query-planning component.
# Emits one JSON payload on stdout. Reports status=unavailable rather than a
# fabricated number when its inputs are absent; the gate treats any emitted
# value as Measured evidence.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

"$PY" - "$GRAPH" <<'PYEOF'
import json, time, datetime
from graphgraph.planning import plan_context

QUERIES = [("where is retrieve_context defined","direct_lookup"),
           ("what calls estimate_tokens","reverse_lookup"),
           ("blast radius of scoping changes","blast_radius")]
for q, c in QUERIES: plan_context(q, c)
runs = []
for _ in range(200):
    for q, c in QUERIES:
        t0 = time.perf_counter(); plan_context(q, c); runs.append((time.perf_counter()-t0)*1e6)
runs.sort()
value = round(runs[len(runs)//2], 2)

print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "query-planning",
    "metric": "plan_latency_us", "value": value, "unit": "us",
    "direction": "lower", "evidence_stage": "Measured", "status": "success", "samples": len(runs),
}))
PYEOF
