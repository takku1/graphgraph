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
from graphgraph.retrieval.search import search_nodes
from graphgraph.services.context import render_final_packet
from graphgraph.packets.metrics import token_units

# A real two-arm comparison: render the same query flat and hybrid, and report
# the ratio. This is the promotion gate's own number -- below 1.0 means the
# candidate is cheaper. No arm is assumed.
#
# Was render_query_context(), removed by e466afd (OW-Q09 context-compiler
# convergence). render_final_packet is the surviving renderer that still takes
# `representation`, so both arms stay comparable; it wants explicit starts, so
# anchors are resolved once and shared by both arms -- the arms must differ
# only in representation, never in their seed set.
graph_path = Path(sys.argv[1])
Q = "how does packet validation work"
graph = load_any(graph_path)
starts = [match.node.id for match in search_nodes(graph, Q, limit=3)]
if not starts:
    print(json.dumps({
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "measurement", "component": "representation",
        "metric": "hybrid_vs_flat_token_ratio", "value": None,
        "status": "unavailable", "reason": f"no anchors matched probe query: {Q!r}",
    }))
    raise SystemExit(0)


# Pinned rather than left to render_final_packet's internal `or 4096` default,
# so the number is reproducible across runs and a change in that default shows
# up as a code change here instead of silently moving the metric.
HYBRID_TOKEN_BUDGET = 4096


def arm(representation: str) -> float:
    return token_units(render_final_packet(
        starts=list(starts),
        query_class="direct_lookup",
        query_text=Q,
        graph_path=graph_path,
        representation=representation,
        representation_budget=HYBRID_TOKEN_BUDGET if representation == "hybrid" else None,
        cache_namespace=f"measure_representation_{representation}",
    ))


flat = arm("flat")
hybrid = arm("hybrid")
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
        # The arms are not budget-symmetric: flat is selection-driven (a node
        # count yields whatever tokens it yields) while hybrid packs toward a
        # fixed token budget. The absolute ratio therefore reflects that budget
        # as well as representation efficiency, and is a same-vs-same
        # regression tripwire over time, NOT a standalone verdict that flat
        # beats hybrid by this factor.
        "hybrid_token_budget": HYBRID_TOKEN_BUDGET,
        "comparison": "budget_asymmetric",
        "anchors": list(starts),
    }))
PYEOF
