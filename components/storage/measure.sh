#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the storage component.
# Emits one JSON payload on stdout. Never emits a fabricated number: when the
# active graph is absent the run reports status=unavailable, which the gate
# treats as a broken instrument and reverts rather than guessing.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"storage","metric":"graph_load_ms","value":null,"unit":"ms","direction":"lower","status":"unavailable","reason":"no active graph at %s; run: graphgraph scan --depth symbols --docs"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, time, datetime
from pathlib import Path
from graphgraph.io.core import load_any

path = Path(sys.argv[1])

# The first in-process load is cold; every later one hits the process cache.
# Reporting a median across both measures neither. Separate them: the gate
# tracks steady-state load, and the cold figure rides along as context.
t0 = time.perf_counter()
load_any(path)
cold_ms = (time.perf_counter() - t0) * 1000.0

warm = []
for _ in range(9):
    t0 = time.perf_counter()
    load_any(path)
    warm.append((time.perf_counter() - t0) * 1000.0)
warm.sort()
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "storage",
    "metric": "graph_load_warm_ms", "value": round(warm[len(warm)//2], 4), "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "samples": len(warm), "min": round(warm[0], 4), "max": round(warm[-1], 4),
    "cold_load_ms": round(cold_ms, 3),
}))
PYEOF
