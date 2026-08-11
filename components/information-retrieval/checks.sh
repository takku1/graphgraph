#!/usr/bin/env bash
# checks.sh -- correctness backpressure for the information-retrieval component.
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
TARGETS=(test_retrieval.py test_retrieval_field_log.py test_retrieval_predicates.py test_retrieval_section_relevance.py test_retrieval_subsystems.py test_relations.py test_tree_knapsack.py test_adversarial_ambiguity.py)
MISSING=()
for t in "${TARGETS[@]}"; do
  [ -f "tests/$t" ] || MISSING+=("$t")
done

if [ ${#MISSING[@]} -ne 0 ]; then
  echo "[CHECKS] information-retrieval: declared suite(s) missing: ${MISSING[*]}" >&2
  echo "[CHECKS] information-retrieval: if they moved deliberately, update components/information-retrieval/checks.sh" >&2
  exit 1
fi

echo "[CHECKS] information-retrieval: ${#TARGETS[@]} suite(s)" >&2
"$PY" -m pytest "${TARGETS[@]/#/tests/}" -q
