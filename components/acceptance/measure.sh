#!/usr/bin/env bash
# measure.sh -- Back-Channel B primary metric for the acceptance component.
#
# Metric: acceptance gate pass-rate over the canonical case set, run against a
# real external repository. direction=higher.
#
# The corpus is external by design: this is the qualification layer, and a
# harness that only ever runs against its own repository qualifies nothing.
# When the corpus is absent the run reports status=unavailable rather than a
# number, per the component spec -- the gate treats a broken instrument as a
# revert, not as a pass.
#
# Secondary figures (pending cases, release blockers, environment blockers)
# ride along in the payload. They are deliberately NOT folded into the primary
# value: a pass-rate that silently absorbs "2 cases are pending" is how a
# partial run gets read as a complete one.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"
REPO="${GRAPHGRAPH_ACCEPTANCE_REPO:-../locus}"

emit_unavailable() {
  printf '{"ts":"%s","event_type":"measurement","component":"acceptance","metric":"acceptance_pass_rate","value":null,"unit":"ratio","direction":"higher","status":"unavailable","reason":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
  exit 0
}

[ -d "$REPO" ] || emit_unavailable "external corpus absent at $REPO; set GRAPHGRAPH_ACCEPTANCE_REPO"
[ -f "$REPO/.graphgraph/graph.gg" ] || emit_unavailable "no graph at $REPO/.graphgraph/graph.gg; run: graphgraph scan --depth symbols --docs"

REPORT="$(mktemp)"
trap 'rm -f "$REPORT"' EXIT

# The runner exits non-zero when cases fail. That is a legitimate measurement,
# not a harness error, so the exit code is captured rather than propagated.
set +e
"$PY" -m graphgraph.acceptance run --repo "$REPO" --json >"$REPORT" 2>/dev/null
RC=$?
set -e

"$PY" - "$REPORT" "$REPO" "$RC" <<'PYEOF'
import datetime
import json
import sys
from pathlib import Path

report_path, repo, rc = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])


def emit(**fields):
    payload = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "measurement",
        "component": "acceptance",
        "metric": "acceptance_pass_rate",
        "unit": "ratio",
        "direction": "higher",
    }
    payload.update(fields)
    print(json.dumps(payload))
    raise SystemExit(0)


try:
    report = json.loads(report_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    emit(value=None, status="unavailable", reason=f"acceptance run produced no parseable report (rc={rc}): {exc}")

summary = report.get("summary") or {}
if "pass_rate" not in summary:
    emit(value=None, status="unavailable", reason=f"report carried no pass_rate (rc={rc})")

environment = report.get("environment") or {}
freshness = environment.get("freshness") or {}

emit(
    value=summary["pass_rate"],
    status="success",
    evidence_stage="Measured",
    runner_exit=rc,
    total=summary.get("total"),
    active=summary.get("active"),
    passed=summary.get("passed"),
    failed=summary.get("failed"),
    # Reported alongside the rate, never inside it: pass_rate is computed over
    # active cases, so pending cases are invisible to the primary number.
    pending=summary.get("pending"),
    blocking_failures=summary.get("blocking_failures"),
    blocking_pending=summary.get("blocking_pending"),
    environment_blockers=summary.get("environment_blockers"),
    release_ready=summary.get("release_ready"),
    corpus=repo,
    graph_hash=environment.get("graph_hash"),
    graph_files=environment.get("graph_files"),
    graph_fresh=freshness.get("fresh"),
)
PYEOF
