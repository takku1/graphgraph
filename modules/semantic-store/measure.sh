#!/usr/bin/env bash
set -euo pipefail

MODULE_NAME="${1:-semantic-store}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PYTHON_PATHSEP="$(python -c 'import os; print(os.pathsep)')"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+$PYTHON_PATHSEP$PYTHONPATH}"

python modules/semantic-store/probe.py --module "$MODULE_NAME"
