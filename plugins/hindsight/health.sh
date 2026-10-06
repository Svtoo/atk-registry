#!/bin/bash
# Prints one line when the bank is healthy; an alarm and exit 1 when work fails or stalls.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli health "$@"
