#!/bin/bash
# Dumps the database to HINDSIGHT_BACKUP_DIR. Thin wrapper so a direct run gets .env
# exactly the way lifecycle commands do.
#   atk run hindsight backup [--if-stale]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli backup "$@"
