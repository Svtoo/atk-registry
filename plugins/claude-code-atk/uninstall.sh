#!/bin/bash
# No `set -e` — partial cleanup is better than no cleanup.

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$PLUGIN_DIR/manage.py" uninstall "$PLUGIN_DIR" \
  || echo "WARNING: manage.py uninstall failed; manual cleanup may be required"
