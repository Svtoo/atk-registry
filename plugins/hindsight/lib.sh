#!/bin/bash
# Loads .env for the wrapper scripts; all command logic lives in the
# hindsight-cli package under src/.

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ATK injects these when it runs a script; sourcing .env keeps direct invocation
# behaving identically.
# shellcheck disable=SC1091
if [ -f "$PLUGIN_DIR/.env" ]; then
    set -a
    . "$PLUGIN_DIR/.env"
    set +a
fi
