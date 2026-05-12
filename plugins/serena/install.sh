#!/bin/bash
set -e

# ATK_NONINTERACTIVE: agents set this to 1 during testing — exit immediately.
# Skipped here too so test harnesses don't fetch the (large) serena distribution.
if [ "${ATK_NONINTERACTIVE:-0}" = "1" ]; then
  echo "ATK_NONINTERACTIVE=1: skipping install"
  exit 0
fi

echo "Installing serena (serena-agent via uv)..."

if ! command -v uv &>/dev/null; then
  echo "ERROR: 'uv' is required but not installed."
  echo "  macOS:  brew install uv"
  echo "  Other:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  Docs:   https://docs.astral.sh/uv/getting-started/installation/"
  echo "Then run: atk install serena"
  exit 1
fi

# Install IS update (per ATK plugin contract). Bare `uv tool install pkg@latest`
# silently skips when pkg is already installed — it does NOT re-resolve to a newer
# version. --reinstall forces uv to uninstall + reinstall at the latest matching
# version every time. --prerelease=allow is the canonical upstream invocation
# (Serena publishes prereleases between stable cuts).
uv tool install -p 3.13 serena-agent@latest --prerelease=allow --reinstall

# Find the serena binary. uv tool installs to ~/.local/bin by default;
# the user's MCP client must have that directory on PATH.
if ! command -v serena &>/dev/null; then
  if [ -x "$HOME/.local/bin/serena" ]; then
    echo ""
    echo "  serena installed to ~/.local/bin/serena"
    echo "  Make sure ~/.local/bin is on PATH for whichever shell your MCP client uses:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "  Add that line to your shell rc file (~/.bashrc, ~/.zshrc, etc.)"
  else
    echo "ERROR: 'serena' was not found in PATH after install."
    echo "  Expected at: ~/.local/bin/serena"
    echo "  Check uv's tool bin directory: uv tool dir --bin"
    exit 1
  fi
fi

# Lay down the global ~/.serena/ config. `serena init` is idempotent —
# it prints a success message and exits.
echo ""
echo "Initialising serena..."
serena init >/dev/null

echo ""
echo "  ✅ serena installed successfully"
echo ""
echo "Per-project usage:"
echo "  Serena auto-activates the current directory as the project when its MCP"
echo "  server starts (--project-from-cwd). Open your editor / agent inside the"
echo "  project root and it just works."
echo ""
echo "  Project-local config lives at <project>/.serena/. Add it to .gitignore"
echo "  or commit it — your choice."
