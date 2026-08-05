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
import json, sys, time, datetime, statistics, subprocess, random
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

from graphgraph.io.core import load_any
from graphgraph.retrieval import query_relations

graph = load_any(graph_path)
candidates = [
    node_id for node_id, node in graph.nodes.items()
    if node.active and node.kind in ("function", "method") and node.label
]
if not candidates:
    print(json.dumps({
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "measurement", "component": "agent-interfaces",
        "metric": "resident_exact_query_p95_ms", "value": None, "unit": "ms",
        "direction": "lower", "status": "unavailable",
        "reason": "no function/method nodes in active graph",
    }))
    raise SystemExit(0)

random.seed(7)
sample = random.sample(candidates, min(300, len(candidates)))

# Warm the process the way a resident MCP server already is by the time it
# serves its first real query: import paths and lexical/token-index caches
# built once, reused across every call after.
for node_id in sample[:10]:
    query_relations(graph, node_id, direction="callers", limit=20)

runs = []
for node_id in sample:
    t0 = time.perf_counter()
    query_relations(graph, node_id, direction="callers", limit=20)
    runs.append((time.perf_counter() - t0) * 1000.0)
runs.sort()
p95 = runs[min(len(runs) - 1, int(len(runs) * 0.95))]
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "event_type": "measurement", "component": "agent-interfaces",
    "metric": "resident_exact_query_p95_ms", "value": round(p95, 4), "unit": "ms",
    "direction": "lower", "evidence_stage": "Measured", "status": "success",
    "samples": len(runs), "min": round(runs[0], 4), "max": round(runs[-1], 4),
    "median": round(runs[len(runs) // 2], 4),
    "stdev": round(statistics.pstdev(runs), 4),
    "query": "query_relations(direction=callers) on a known exact node id, sampled uniformly across active function/method nodes",
}))
PYEOF
