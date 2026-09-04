#!/bin/bash
# Applies ATK's bank configuration to the configured bank. Thin wrapper so a
# direct run gets .env exactly the way lifecycle commands do.
#   atk run hindsight conform [--force]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/lib.sh"
exec uv run --project "$DIR/src" python "$DIR/src/conform.py" "$@"
