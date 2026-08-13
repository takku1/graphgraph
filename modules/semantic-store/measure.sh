#!/usr/bin/env bash
set -euo pipefail

MODULE_NAME="${1:-semantic-store}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python modules/semantic-store/probe.py --module "$MODULE_NAME"
