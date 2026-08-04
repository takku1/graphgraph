#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the information-retrieval component.
# Emits one JSON payload on stdout. Never emits a fabricated number: when the
# active graph is absent the run reports status=unavailable, which the gate
# treats as a broken instrument and reverts rather than guessing.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"information-retrieval","metric":"retrieval_query_ms","value":null,"unit":"ms","direction":"lower","status":"unavailable","reason":"no active graph at %s; run: graphgraph scan --depth symbols --docs"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, time, datetime, statistics
from pathlib import Path
from graphgraph.io.core import load_any
from graphgraph.retrieval import retrieve_context

graph = load_any(Path(sys.argv[1]))

# One representative query repeated, so the spread reflects the system rather
# than a mix of unlike workloads. Load is excluded: this is the warm retrieval
# path the resident transport actually serves.
QUERY, QCLASS = "where is retrieve_context defined", "direct_lookup"
for _ in range(3):
    retrieve_context(graph, QUERY, QCLASS, hops=1)
runs = []
for _ in range(9):
    t0 = time.perf_counter()
    retrieve_context(graph, QUERY, QCLASS, hops=1)
    runs.append((time.perf_counter() - t0) * 1000.0)
runs.sort()
median = runs[len(runs)//2]
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "information-retrieval",
    "metric": "retrieval_query_warm_ms", "value": round(median, 3), "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "query": QUERY, "query_class": QCLASS,
    "samples": len(runs), "min": round(runs[0], 3), "max": round(runs[-1], 3),
    "stdev": round(statistics.pstdev(runs), 3),
}))
PYEOF
