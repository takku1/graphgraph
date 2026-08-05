#!/usr/bin/env bash
# measure.sh -- cold-start process latency for the CLI transport.
# This is the figure the architecture insists on reporting separately from
# resident retrieval: it is interpreter start plus import, not graph work.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

"$PY" - <<'PYEOF'
import json, time, datetime, subprocess, sys, statistics
runs = []
for _ in range(5):
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, "-c", "import graphgraph.cli"],
                          capture_output=True, timeout=60)
    dt = (time.perf_counter() - t0) * 1000.0
    if proc.returncode != 0:
        print(json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "event_type": "measurement", "component": "agent-interfaces",
                          "metric": "cli_cold_start_ms", "value": None, "status": "unavailable",
                          "reason": proc.stderr.decode("utf-8", "replace")[:200]}))
            
        raise SystemExit(0)
    runs.append(dt)
runs.sort()
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "agent-interfaces",
    "metric": "cli_cold_start_ms", "value": round(runs[len(runs)//2], 2), "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "samples": len(runs), "min": round(runs[0], 2), "max": round(runs[-1], 2),
    "stdev": round(statistics.pstdev(runs), 2),
}))
PYEOF
