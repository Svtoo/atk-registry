#!/bin/bash
# OpenMemory full uninstall — removes containers, images, volumes, and vendor clone
# No set -e: processes may already be stopped

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== OpenMemory Uninstall ==="

# --- Stop and remove containers + locally built images ---
echo "  Stopping containers..."
cd "$PLUGIN_DIR"
docker compose down --rmi local 2>/dev/null || true

# --- Remove named volume ---
echo "  Removing data volume..."
docker volume rm openmemory_data 2>/dev/null || true

# --- Remove vendor clone ---
echo "  Removing vendor source..."
rm -rf "$PLUGIN_DIR/vendor"

echo "  ✅ OpenMemory uninstalled"

