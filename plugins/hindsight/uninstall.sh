#!/bin/bash
# Removes the container and image; offers to delete stored memories. Thin wrapper so a direct run gets .env
# exactly the way lifecycle commands do.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" hindsight-cli uninstall "$@"
