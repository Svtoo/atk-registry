#!/bin/bash
# Do NOT use set -e — partial cleanup is better than no cleanup

echo "Uninstalling codanna..."

OS="$(uname -s)"

if [ "$OS" = "Darwin" ]; then
  if command -v brew &>/dev/null && brew list codanna &>/dev/null 2>&1; then
    echo "  Removing via Homebrew..."
    brew uninstall codanna || true
  elif [ -x "$HOME/.local/bin/codanna" ]; then
    echo "  Removing ~/.local/bin/codanna..."
    rm -f "$HOME/.local/bin/codanna"
  else
    echo "  codanna not found via Homebrew or ~/.local/bin; nothing to remove."
  fi
elif [ "$OS" = "Linux" ]; then
  if [ -x "$HOME/.local/bin/codanna" ]; then
    echo "  Removing ~/.local/bin/codanna..."
    rm -f "$HOME/.local/bin/codanna"
  elif command -v codanna &>/dev/null; then
    CODANNA_BIN="$(command -v codanna)"
    echo "  Removing $CODANNA_BIN..."
    rm -f "$CODANNA_BIN"
  else
    echo "  codanna not found; nothing to remove."
  fi
else
  echo "  Unsupported OS: $OS — remove codanna manually."
fi

echo "  ✅ codanna uninstalled"
echo ""
echo "Note: Per-project .codanna/ directories are NOT removed."
echo "  Delete them manually if desired: rm -rf /path/to/project/.codanna"

