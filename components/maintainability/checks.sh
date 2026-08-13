#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

PY="${GRAPHGRAPH_PYTHON:-.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

"$PY" -m pytest \
  tests/test_maintainability.py \
  tests/test_module_boundaries.py \
  tests/test_surface_constants.py \
  tests/test_docs_contract.py \
  -q
"$PY" -m ruff check src/graphgraph tests/test_maintainability.py
