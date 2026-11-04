#!/bin/bash
set -e

# Install is also update: it converges to the desired state.
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prereq: the claude CLI (Claude Code), which installs the mod.
if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: the claude CLI (Claude Code) is required but not found in PATH."
  echo "  Install Claude Code (https://code.claude.com/docs/en/setup), then run: atk add atk-debrief"
  exit 1
fi

# atk-debrief replaces claude-dashboard: side by side, both draw a band and rebuild each chat twice.
if [ -d "$PLUGIN_DIR/../claude-dashboard" ]; then
  echo "ERROR: claude-dashboard is installed, and atk-debrief replaces it."
  echo "  Remove it first: atk remove claude-dashboard"
  echo "  Each chat keeps its dashboard: atk-debrief reads the same files."
  echo "Then run: atk add atk-debrief"
  exit 1
fi
if claude plugin list --json 2>/dev/null | grep -q '"chat-dashboard@claude-dashboard"'; then
  echo "ERROR: the claude-dashboard mod is still installed, and atk-debrief replaces it."
  echo "  Remove it first: claude plugin uninstall chat-dashboard@claude-dashboard --scope user"
  echo "  and its marketplace: claude plugin marketplace remove claude-dashboard"
  echo "Then run: atk add atk-debrief"
  exit 1
fi

# The desktop app brings its own Claude Code and is where the mod is supported; a terminal session runs it, unsupported,
# from 2.1.308.
MIN_VERSION="2.1.308"
CLAUDE_VERSION=$(claude --version 2>/dev/null | awk '{print $1}')
if [ "$(printf '%s\n%s\n' "$MIN_VERSION" "$CLAUDE_VERSION" | sort -V | head -1)" != "$MIN_VERSION" ]; then
  TERMINAL_NOTE="claude ${CLAUDE_VERSION:-of an unknown version} is older than $MIN_VERSION, so a terminal session does not run the mod; the desktop app, where it is supported, does. For the terminal too: claude update"
fi

# Install the ATK Debrief mod for every session. Its marketplace is the mod's
# own folder, so Claude Code reads the mod in place from $PLUGIN_DIR/mod.
claude plugin marketplace add "$PLUGIN_DIR/mod" >/dev/null
claude plugin install atk-debrief@atk-debrief --scope user >/dev/null

echo "✓ atk-debrief installed"
echo "  mod: ATK Debrief (atk-debrief@atk-debrief), read from $PLUGIN_DIR/mod"
echo "  settings: /debrief-settings in any chat"
if [ -n "${TERMINAL_NOTE:-}" ]; then echo "  note: $TERMINAL_NOTE"; fi
