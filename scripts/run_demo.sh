#!/usr/bin/env bash
# Convenience wrapper around the portable full-demo runner.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python scripts/run_demo.py "$@"
fi
exec python3 scripts/run_demo.py "$@"

