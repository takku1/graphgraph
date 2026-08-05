#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the intermediate-representation component.
# Emits one JSON payload on stdout. Reports status=unavailable rather than a
# fabricated number when its inputs are absent; the gate treats any emitted
# value as Measured evidence.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"intermediate-representation","metric":"traversal_2hop_ms","value":null,"status":"unavailable","reason":"no active graph at %s"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, time, datetime
from pathlib import Path
from graphgraph.io.core import load_any
from graphgraph.retrieval.expansion import expand_context
from graphgraph.planning import plan_context

graph = load_any(Path(sys.argv[1]))
plan = plan_context("blast radius of scoping changes", "blast_radius")
starts = tuple(sorted(graph.nodes)[:25])
for _ in range(2):
    expand_context(graph, starts, plan)
runs = []
for _ in range(7):
    t0 = time.perf_counter()
    expand_context(graph, starts, plan)
    runs.append((time.perf_counter() - t0) * 1000.0)
runs.sort()
value = round(runs[len(runs)//2], 3)
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "intermediate-representation",
    "metric": "expand_context_ms", "value": value, "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "samples": len(runs), "starts": len(starts),
}))
PYEOF
