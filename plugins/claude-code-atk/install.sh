#!/bin/bash
set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required but not installed."
  echo "  macOS:  brew install python3"
  echo "  Linux:  use your package manager (apt, dnf, pacman, ...)"
  exit 1
fi

exec python3 "$PLUGIN_DIR/manage.py" install "$PLUGIN_DIR"
