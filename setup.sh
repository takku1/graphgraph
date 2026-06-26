#!/usr/bin/env bash
set -e

# GraphGraph Setup Bootstrap for Unix
echo "Starting GraphGraph Setup..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed. Please install Python 3.10+." >&2
    exit 1
fi

python3 setup_graphgraph.py "$@"
