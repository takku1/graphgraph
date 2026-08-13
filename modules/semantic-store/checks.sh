#!/usr/bin/env bash
set -euo pipefail

MODULE_NAME="${1:-semantic-store}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "[CHECKS] ${MODULE_NAME}: semantic-store contract and repository gates"
python -m pytest \
  tests/test_semantic_store.py \
  tests/test_planning.py \
  tests/test_cli_mcp.py \
  tests/test_cycle5_regressions.py \
  -q
python -m pytest -q
python -m ruff check .
git diff --check
echo "[CHECKS] ${MODULE_NAME}: PASS"
