#!/bin/bash
# Piper TTS installation script
# Clones the MCP server repository into vendor/

set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$PLUGIN_DIR/vendor"
MCP_REPO_URL="https://github.com/CryptoDappDev/piper-tts-mcp.git"
MCP_REPO_REF="main"

echo "Installing Piper TTS MCP server..."

# Create vendor directory
mkdir -p "$VENDOR_DIR"

# Clone or update MCP server repo
if [ -d "$VENDOR_DIR/piper-tts-mcp" ]; then
    echo "Updating existing MCP server repository..."
    cd "$VENDOR_DIR/piper-tts-mcp"
    git fetch origin
    git checkout "$MCP_REPO_REF"
    git pull origin "$MCP_REPO_REF"
else
    echo "Cloning MCP server repository..."
    git clone --branch "$MCP_REPO_REF" "$MCP_REPO_URL" "$VENDOR_DIR/piper-tts-mcp"
fi

echo "✓ Piper TTS MCP server installed"

