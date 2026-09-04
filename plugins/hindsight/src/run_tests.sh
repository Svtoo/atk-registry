#!/usr/bin/env bash
# Run all hindsight plugin unit tests in the uv-managed environment.
# No docker and no live API; uv may sync the environment on first run.
# Usage: ./run_tests.sh
set -u
export PYTHONDONTWRITEBYTECODE=1
# typer-slim 0.21 re-exports click stream helpers that click 8.5 deprecates.
export PYTHONWARNINGS="ignore::DeprecationWarning:typer"
cd "$(dirname "$0")" || exit 2

fail=0
for t in test_*.py; do
    echo "== $t"
    uv run --project . python "$t" || fail=1
done
exit $fail
