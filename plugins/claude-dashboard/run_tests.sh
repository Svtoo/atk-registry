#!/usr/bin/env bash
# Run all claude-dashboard unit tests. No network, no `claude -p`.
# Each test file is a self-contained stdlib script (python3 <file>); this just
# runs them all and reports an aggregate pass/fail.
#
# Usage: ./run_tests.sh
set -u

# Don't litter the plugin dir with __pycache__/*.pyc.
export PYTHONDONTWRITEBYTECODE=1

cd "$(dirname "$0")/server" || exit 2

TESTS=(test_regen test_store test_serve_security)
fail=0

for t in "${TESTS[@]}"; do
  echo "=== ${t} ==="
  if ! python3 "${t}.py"; then
    fail=1
  fi
  echo
done

if [ "${fail}" -eq 0 ]; then
  echo "ALL TESTS PASSED"
else
  echo "SOME TESTS FAILED" >&2
fi
exit "${fail}"
