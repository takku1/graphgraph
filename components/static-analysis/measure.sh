#!/usr/bin/env bash
# measure.sh -- corpus extraction cost over a fixed in-repo subtree.
# A bounded, repeatable scan: the whole-repo number is dominated by corpus size
# rather than by frontend cost, so it cannot gate a frontend change.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

"$PY" - <<'PYEOF'
import json, time, datetime
from pathlib import Path
from graphgraph.scanner import scan_directory

TARGET = Path("src/graphgraph/concepts")
if not TARGET.is_dir():
    print(json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "event_type": "measurement", "component": "static-analysis",
                      "metric": "scan_fixture_ms", "value": None, "status": "unavailable",
                      "reason": f"missing corpus {TARGET}"}))
    raise SystemExit(0)

scan_directory(TARGET, depth="symbols")           # warm caches
runs = []
for _ in range(3):
    t0 = time.perf_counter()
    graph = scan_directory(TARGET, depth="symbols")
    runs.append((time.perf_counter() - t0) * 1000.0)
runs.sort()
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "static-analysis",
    "metric": "scan_fixture_ms", "value": round(runs[len(runs)//2], 2), "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "corpus": str(TARGET), "nodes": len(graph.nodes), "samples": len(runs),
}))
PYEOF
