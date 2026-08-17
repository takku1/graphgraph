#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the agent-interfaces component.
# SYSTEM.md declares "resident exact-query p95 latency (OW-AC-01)" as the
# primary metric; until this receipt, nothing measured it and the script here
# gated cli_cold_start_ms (the *secondary* metric) instead. Emits one JSON
# payload on stdout, matching every other component's measure.sh contract --
# cli_cold_start_ms is still computed and logged to stderr for humans, since
# ADR-AI-001 says the two figures are never averaged together, but only one
# JSON payload can be the harness-parsed primary metric per invocation.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
GRAPH="${GRAPHGRAPH_GRAPH:-.graphgraph/graph.gg}"

if [ ! -f "$GRAPH" ]; then
  printf '{"ts":"%s","event_type":"measurement","component":"agent-interfaces","metric":"resident_exact_query_p95_ms","value":null,"unit":"ms","direction":"lower","status":"unavailable","reason":"no active graph at %s; run: graphgraph scan --depth symbols --docs"}
'     "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GRAPH"
  exit 0
fi

"$PY" - "$GRAPH" <<'PYEOF'
import json, sys, time, datetime, statistics, subprocess
from pathlib import Path

graph_path = Path(sys.argv[1])

# Secondary metric, logged to stderr only -- see the module docstring above
# for why this can't also be the stdout JSON payload.
cold_runs = []
for _ in range(5):
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, "-c", "import graphgraph.cli"],
                          capture_output=True, timeout=60)
    if proc.returncode != 0:
        break
    cold_runs.append((time.perf_counter() - t0) * 1000.0)
if cold_runs:
    cold_runs.sort()
    print(f"[secondary] cli_cold_start_ms median={cold_runs[len(cold_runs)//2]:.2f}", file=sys.stderr)

from graphgraph.benchmark.relation_latency import measure_relation_latency_strata
from graphgraph.benchmark.resident_query import (
    measure_kernel_exact_p95,
    measure_session_exact_p95,
)
from graphgraph.io.core import load_any

kernel = measure_kernel_exact_p95(load_any(graph_path))
session = measure_session_exact_p95(graph_path)
relation_latency = measure_relation_latency_strata(samples=20)
payload = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement",
    "component": "agent-interfaces",
    "metric": "resident_exact_query_p95_ms",
    "value": session.get("value"),
    "unit": "ms",
    "direction": "lower",
    "evidence_stage": "Measured",
    "status": session.get("status", "unavailable"),
    "target": session.get("target"),
    "samples": session.get("samples"),
    "min": session.get("min"),
    "max": session.get("max"),
    "median": session.get("median"),
    "query": session.get("query"),
    "kernel": kernel,
    "relation_latency": relation_latency,
}
if session.get("reason"):
    payload["reason"] = session["reason"]
print(json.dumps(payload))
if payload["status"] == "fail":
    raise SystemExit(1)
PYEOF
