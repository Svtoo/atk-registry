#!/bin/bash
# No `set -e`: uninstall is best-effort cleanup.

# Uninstall the ATK Debrief mod and its marketplace; the mod's folder stays.
if command -v claude >/dev/null 2>&1; then
  claude plugin uninstall atk-debrief@atk-debrief --scope user >/dev/null 2>&1 || true
  claude plugin marketplace remove atk-debrief >/dev/null 2>&1 || true
fi

echo "✓ atk-debrief uninstalled"
echo "  Note: each chat's state.json and tail files in ~/.claude/projects/*/*/ are user data and have NOT been touched,"
echo "  nor the mod's settings (model and time limit) in Claude Code's plugin store."
