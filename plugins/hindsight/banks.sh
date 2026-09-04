#!/bin/bash
# Lists or deletes memory banks. Thin wrapper so a direct run gets .env
# exactly the way lifecycle commands do.
#   atk run hindsight banks [list|delete <bank>...]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli banks "$@"
