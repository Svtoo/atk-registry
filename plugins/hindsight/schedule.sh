#!/bin/bash
# Manages the launchd job that keeps daily backups fresh. Thin wrapper so a direct run gets .env
# exactly the way lifecycle commands do.
#   atk run hindsight schedule [off|status]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli schedule "$@"
