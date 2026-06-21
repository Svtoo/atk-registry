#!/bin/bash
# No `set -e` — uninstall should be best-effort cleanup.
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Stop the server if it's running.
"$PLUGIN_DIR/stop.sh" 2>/dev/null || true

# Unwire the Stop hook + remove hook scripts from ~/.claude/hooks/.
python3 "$PLUGIN_DIR/manage.py" uninstall "$PLUGIN_DIR" 2>/dev/null || true

# Remove runtime artifacts (PID file, log).
rm -rf "$PLUGIN_DIR/runtime"

echo "✓ claude-dashboard uninstalled"
echo "  Note: per-chat dashboards in ~/.claude/projects/*/*/dashboard.html are user data and have NOT been touched."
