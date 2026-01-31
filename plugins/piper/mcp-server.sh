#!/bin/bash
# Piper TTS MCP server wrapper
# Runs the MCP server with uv, pointing to local Docker service

set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$PLUGIN_DIR/vendor/piper-tts-mcp"

# Ensure vendor repo exists
if [ ! -d "$VENDOR_DIR" ]; then
    echo "Error: MCP server not installed. Run 'atk install piper' first." >&2
    exit 1
fi

# Set default URL if not provided
export PIPER_TTS_URL="${PIPER_TTS_URL:-http://localhost:5847}"

cd "$VENDOR_DIR"
exec uv run server.py

