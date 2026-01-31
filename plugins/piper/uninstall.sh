#!/bin/bash
# Piper TTS uninstallation script
# Removes Docker resources and vendor directory

set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Uninstalling Piper TTS..."

# Stop and remove containers
cd "$PLUGIN_DIR"
if [ -f docker-compose.yml ]; then
    docker compose down -v 2>/dev/null || true
fi

# Remove Docker images
docker rmi piper-tts 2>/dev/null || true

# Remove vendor directory
rm -rf "$PLUGIN_DIR/vendor"

echo "✓ Piper TTS uninstalled"

