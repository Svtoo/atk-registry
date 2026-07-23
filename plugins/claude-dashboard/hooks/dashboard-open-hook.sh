#!/usr/bin/env bash
# Claude Code UserPromptSubmit hook for claude-dashboard. Finds a Python and runs
# preview/session_open.py, which injects the once-per-session Browser-pane open
# instruction. DASHBOARD_PLUGIN_DIR is set by the installer (manage.py).

# Short-circuit inside our own headless subagent (it also runs with
# --setting-sources local, which skips user hooks).
if [ -n "${CLAUDE_DASHBOARD_SUBAGENT:-}" ]; then
  exit 0
fi

PLUGIN_DIR="${DASHBOARD_PLUGIN_DIR:-}"
if [ -z "$PLUGIN_DIR" ]; then
  exit 0
fi

for py in python3 python python3.13 python3.12 python3.11 python3.10; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" "$PLUGIN_DIR/preview/session_open.py"
  fi
done

# No Python found; exit 0.
exit 0
