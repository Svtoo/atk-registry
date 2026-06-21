#!/bin/bash
set -e

# install IS update — converge to desired state, no conditional logic.
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prereq: python3
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required but not found in PATH."
  echo "  macOS:  ships with Xcode CLI tools, or 'brew install python3'"
  echo "  Linux:  apt/dnf/pacman install python3"
  exit 1
fi

PY_OK=$(python3 -c 'import sys; print("yes" if sys.version_info >= (3, 7) else "no")')
if [ "$PY_OK" != "yes" ]; then
  echo "ERROR: python3 >= 3.7 required (need ThreadingHTTPServer)."
  echo "  current: $(python3 --version)"
  exit 1
fi

# Prereq: ~/.claude/projects/ exists (otherwise the plugin has nothing to serve).
PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
if [ ! -d "$PROJECTS_DIR" ]; then
  echo "WARN: $PROJECTS_DIR does not exist yet."
  echo "  The server will start anyway and the landing page will be empty until"
  echo "  Claude Code creates its first chat history file in this directory."
fi

# Ensure runtime dir exists. We deliberately do NOT wipe it: it holds the
# live server's pid + log files, and re-running install while the server
# is up should be safe (the whole point is to sync hook scripts without
# tearing down the running process).
mkdir -p "$PLUGIN_DIR/runtime"

# Wire the Stop hook + copy hook scripts to ~/.claude/hooks/.
python3 "$PLUGIN_DIR/manage.py" install "$PLUGIN_DIR"

echo "✓ claude-dashboard installed"
echo "  python3: $(python3 --version)"
echo "  projects: $PROJECTS_DIR"
echo "  start with: atk start claude-dashboard"
