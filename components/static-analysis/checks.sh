#!/usr/bin/env bash
# checks.sh -- correctness backpressure for the static-analysis component.
# Exit 0 = PASS. Non-zero blocks the keep decision regardless of the metric.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

# Every declared suite must exist. The previous template skipped absent targets
# so that in-flight uncommitted work would not fail the gate; that tolerance let
# a gate keep reporting green while running fewer suites than it declares.
# A declared-but-missing suite is drift, and drift is the thing this gate exists
# to catch.
TARGETS=(test_scanner.py test_scanner_frontends.py test_scanner_imports.py test_scanner_incremental.py test_scanner_docs.py test_scanner_history.py test_scope_graph.py test_receiver_type_resolution.py test_persistent_type_facts.py test_grammar_profiles.py)
MISSING=()
for t in "${TARGETS[@]}"; do
  [ -f "tests/$t" ] || MISSING+=("$t")
done

if [ ${#MISSING[@]} -ne 0 ]; then
  echo "[CHECKS] static-analysis: declared suite(s) missing: ${MISSING[*]}" >&2
  echo "[CHECKS] static-analysis: if they moved deliberately, update components/static-analysis/checks.sh" >&2
  exit 1
fi

echo "[CHECKS] static-analysis: ${#TARGETS[@]} suite(s)" >&2
"$PY" -m pytest "${TARGETS[@]/#/tests/}" -q
