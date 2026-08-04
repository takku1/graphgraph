#!/usr/bin/env bash
# checks.sh -- correctness backpressure for the acceptance component.
# Exit 0 = PASS. Non-zero blocks the keep decision regardless of the metric.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

# Only run suites that exist: some targets are still in-flight and uncommitted,
# and a missing file must not be reported as a passing check.
TARGETS=()
for t in test_acceptance.py test_acceptance_exec.py test_acceptance_quality.py test_live_validation.py; do
  [ -f "tests/$t" ] && TARGETS+=("tests/$t")
done

if [ ${#TARGETS[@]} -eq 0 ]; then
  echo "[CHECKS] acceptance: no test targets present" >&2
  exit 1
fi

echo "[CHECKS] acceptance: ${#TARGETS[@]} suite(s)" >&2
"$PY" -m pytest "${TARGETS[@]}" -q
