#!/bin/bash
# Healthy when the ATK Debrief mod is installed and enabled for every session.

if ! command -v claude >/dev/null 2>&1; then
  echo "✗ the claude CLI (Claude Code) is not in PATH"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 is needed to read claude plugin list"
  exit 1
fi

if claude plugin list --json 2>/dev/null | python3 -c '
import json, sys
plugins = json.load(sys.stdin)
sys.exit(0 if any(p.get("id") == "atk-debrief@atk-debrief" and p.get("enabled") for p in plugins) else 1)
' 2>/dev/null; then
  echo "✓ ATK Debrief mod installed and enabled"
  exit 0
fi

echo "✗ ATK Debrief mod is not installed or not enabled: run atk add atk-debrief"
exit 1
