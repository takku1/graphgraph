#!/usr/bin/env bash
set -euo pipefail

MODULE_NAME="${1:-semantic-store}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PYTHON_PATHSEP="$(python -c 'import os; print(os.pathsep)')"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+$PYTHON_PATHSEP$PYTHONPATH}"

echo "[CHECKS] ${MODULE_NAME}: semantic-store contract and repository gates"
python -m pytest \
  tests/test_semantic_store.py \
  tests/test_planning.py \
  tests/test_cli_mcp.py \
  tests/test_cycle5_regressions.py \
  tests/test_retrieval_phase_characterization.py \
  tests/test_module_boundaries.py \
  -q
python -m pytest -q
python -m ruff check .
python components/maintainability/measure.py
git diff --check
echo "[CHECKS] ${MODULE_NAME}: PASS"
