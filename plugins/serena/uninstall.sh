#!/bin/bash
# Do NOT use set -e — partial cleanup is better than no cleanup.

echo "Uninstalling serena..."

if command -v uv &>/dev/null; then
  if uv tool list 2>/dev/null | grep -qi '^serena-agent'; then
    echo "  Removing serena-agent via uv tool..."
    uv tool uninstall serena-agent || true
  else
    echo "  serena-agent not registered with uv; nothing to remove."
  fi
elif [ -x "$HOME/.local/bin/serena" ]; then
  # Fallback if uv was uninstalled before this plugin was removed
  echo "  Removing ~/.local/bin/serena directly..."
  rm -f "$HOME/.local/bin/serena"
else
  echo "  serena not found; nothing to remove."
fi

echo "  ✅ serena uninstalled"
echo ""
echo "Notes:"
echo "  - Global config (~/.serena/) is NOT removed. Delete manually if desired:"
echo "      rm -rf ~/.serena"
echo "  - Per-project .serena/ directories are NOT removed. They are inside"
echo "    your project trees; remove them yourself if you no longer want them."
