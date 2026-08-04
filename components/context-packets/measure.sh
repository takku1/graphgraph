#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the context-packets component.
# Emits one JSON payload on stdout. Never emits a fabricated number: when the
# active graph is absent the run reports status=unavailable, which the gate
# treats as a broken instrument and reverts rather than guessing.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"context-packets","metric":"packet_token_units","value":null,"unit":"tokens","direction":"lower","status":"unavailable","reason":"no active graph at %s; run: graphgraph scan --depth symbols --docs"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, datetime
from pathlib import Path
from graphgraph.io.core import load_any
from graphgraph.retrieval import retrieve_context
from graphgraph.packets.metrics import token_units

graph = load_any(Path(sys.argv[1]))
total = 0.0
queries = [
    ("where is retrieve_context defined", "direct_lookup"),
    ("how does packet validation work", "subsystem_summary"),
]
for q, cls in queries:
    result = retrieve_context(graph, q, cls, hops=1)
    packet = str(result.metadata.get("packet", "")) or " ".join(sorted(result.nodes))
    total += token_units(packet)
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "context-packets",
    "metric": "packet_token_units", "value": round(total, 2), "unit": "tokens",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "queries": len(queries),
}))
PYEOF
