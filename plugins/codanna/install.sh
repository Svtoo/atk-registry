#!/bin/bash
set -e

# ATK_NONINTERACTIVE: agents set this to 1 during testing — exit immediately
if [ "${ATK_NONINTERACTIVE:-0}" = "1" ]; then
  echo "ATK_NONINTERACTIVE=1: skipping interactive install"
  exit 0
fi

echo "Installing codanna..."

OS="$(uname -s)"

if [ "$OS" = "Darwin" ]; then
  if command -v brew &>/dev/null; then
    echo "  Using Homebrew..."
    brew upgrade codanna || brew install codanna
  else
    echo "  Homebrew not found, using install script..."
    curl -fsSL --proto '=https' --tlsv1.2 https://install.codanna.sh | sh
  fi
elif [ "$OS" = "Linux" ]; then
  echo "  Using install script..."
  curl -fsSL --proto '=https' --tlsv1.2 https://install.codanna.sh | sh
else
  echo "ERROR: Unsupported OS: $OS"
  echo "  Please install codanna manually: https://docs.codanna.sh/installation"
  exit 1
fi

# Verify the binary is reachable
if ! command -v codanna &>/dev/null; then
  # Linux install script places binary in ~/.local/bin — check if it is there
  if [ -x "$HOME/.local/bin/codanna" ]; then
    echo ""
    echo "  codanna installed to ~/.local/bin/codanna"
    echo "  Make sure ~/.local/bin is in your PATH:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "  Add that line to your shell rc file (~/.bashrc, ~/.zshrc, etc.)"
  else
    echo "ERROR: codanna was not found in PATH after install."
    echo "  On macOS (Homebrew): /opt/homebrew/bin/codanna"
    echo "  On Linux (install script): ~/.local/bin/codanna"
    echo "  Ensure the relevant directory is in your PATH."
    exit 1
  fi
fi

echo "  ✅ codanna installed successfully"
echo ""
echo "Per-project setup (run inside each project directory):"
echo "  codanna init        # creates .codanna/settings.toml"
echo "  codanna index src   # indexes source (downloads ~150 MB model on first run)"

