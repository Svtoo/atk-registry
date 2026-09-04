#!/bin/bash
# Mental models over the full API, including the schedule and mode the MCP
# surface does not expose.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli mental-models "$@"
