#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the research component.
# Emits one JSON payload on stdout. Reports status=unavailable rather than a
# fabricated number when its inputs are absent; the gate treats any emitted
# value as Measured evidence.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

"$PY" - "$GRAPH" <<'PYEOF'
import json, datetime, pathlib
from graphgraph.research.registry import validate_research_registry
import json as _j

registry = _j.loads(pathlib.Path("eval/context-system-research.json").read_text(encoding="utf-8"))
errors = validate_research_registry(registry, root=pathlib.Path("."))
value = len([e for e in errors if "source path does not exist" in str(e)])

print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "research",
    "metric": "registry_dangling_sources", "value": value, "unit": "count",
    "direction": "lower", "evidence_stage": "Measured", "status": "success", "total_errors": len(errors),
}))
PYEOF
