#!/bin/bash
# Replaces the database from a backup dump. Destructive. Thin wrapper so a direct run gets .env
# exactly the way lifecycle commands do.
#   atk run hindsight restore [dump-file]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli restore "$@"
