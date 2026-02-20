#!/bin/bash
# OpenMemory uninstall — removes containers, images, and vendor clone.
# The persistent data volume is KEPT by default; you are prompted to delete it.
# No set -e: processes may already be stopped

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOLUME_NAME="${OPENMEMORY_VOLUME_NAME:-openmemory_data}"

echo "=== OpenMemory Uninstall ==="

# --- Stop and remove containers + locally built images ---
echo "  Stopping containers..."
cd "$PLUGIN_DIR"
docker compose down --rmi local 2>/dev/null || true

# --- Prompt before removing the data volume ---
echo ""
echo "  ⚠️  The data volume '$VOLUME_NAME' contains all stored memories."
echo "  Deleting it is permanent and cannot be undone."
echo ""
printf "  Remove persistent memory data? [y/N] "

# Default to no when stdin is not a terminal (piped input, CI, atk uninstall, etc.)
if [[ -t 0 ]]; then
    read -r response
else
    response="n"
    echo "n  (non-interactive — preserving data)"
fi

case "$response" in
    y|Y|yes|YES|Yes)
        echo "  Removing data volume..."
        docker volume rm "$VOLUME_NAME" 2>/dev/null || true
        echo "  ✅ Data volume removed"
        ;;
    *)
        echo "  ✅ Data volume preserved — memories intact"
        ;;
esac

# --- Remove vendor clone ---
echo "  Removing vendor source..."
rm -rf "$PLUGIN_DIR/vendor"

echo "  ✅ OpenMemory uninstalled"

