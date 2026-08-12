#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the application-services component.
# Emits one JSON payload on stdout. Reports status=unavailable rather than a
# fabricated number when its inputs are absent; the gate treats any emitted
# value as Measured evidence.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"application-services","metric":"context_compile_warm_ms","value":null,"status":"unavailable","reason":"no active graph at %s"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, time, datetime
from pathlib import Path
from graphgraph.services.compiler_driver import CompilerDriver, DriverRequest

# Was render_query_context(), removed by e466afd (OW-Q09 context-compiler
# convergence). CompilerDriver is that path's successor and is itself the
# application-services entry point, so this measures the component directly
# rather than a helper that used to sit in front of it.
graph_path = Path(sys.argv[1])
Q = "how does packet validation work"


def compile_once() -> None:
    CompilerDriver().compile(DriverRequest(
        query=Q,
        graph_path=graph_path,
        query_class="direct_lookup",
        rebuild=False,
    ))


for _ in range(2):
    compile_once()
runs = []
for _ in range(5):
    t0 = time.perf_counter()
    compile_once()
    runs.append((time.perf_counter() - t0) * 1000.0)
runs.sort()
value = round(runs[len(runs)//2], 3)
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "application-services",
    "metric": "context_compile_warm_ms", "value": value, "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "samples": len(runs), "query": Q,
}))
PYEOF
