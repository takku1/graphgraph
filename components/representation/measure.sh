#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the representation component.
# Emits one JSON payload on stdout. Reports status=unavailable rather than a
# fabricated number when its inputs are absent; the gate treats any emitted
# value as Measured evidence.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"representation","metric":"hybrid_vs_flat_token_ratio","value":null,"status":"unavailable","reason":"no active graph at %s"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, datetime
from pathlib import Path
from graphgraph.io.core import load_any
from graphgraph.services.context import render_query_context
from graphgraph.packets.metrics import token_units

# A real two-arm comparison: render the same query flat and hybrid, and report
# the ratio. This is the promotion gate's own number -- below 1.0 means the
# candidate is cheaper. No arm is assumed.
graph = load_any(Path(sys.argv[1]))
Q = "how does packet validation work"
flat = token_units(render_query_context(query=Q, graph=graph, representation="flat"))
hybrid = token_units(render_query_context(query=Q, graph=graph, representation="hybrid"))
if flat <= 0:
    print(json.dumps({
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "measurement", "component": "representation",
        "metric": "hybrid_vs_flat_token_ratio", "value": None,
        "status": "unavailable", "reason": "flat arm produced no packet",
    }))
else:
    print(json.dumps({
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "measurement", "component": "representation",
        "metric": "hybrid_vs_flat_token_ratio", "value": round(hybrid / flat, 4),
        "unit": "ratio", "direction": "lower",
        "evidence_stage": "Measured", "status": "success",
        "flat_token_units": round(flat, 2), "hybrid_token_units": round(hybrid, 2), "query": Q,
    }))
PYEOF
