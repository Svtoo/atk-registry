#!/bin/bash
# OpenMemory backup script
# Copies the Docker volume named OPENMEMORY_VOLUME_NAME to OPENMEMORY_BACKUP_DIR.
# If OPENMEMORY_BACKUP_DIR is not set, this script is a no-op.
#
# Usage (via ATK — env vars injected automatically):
#   atk run openmemory backup
#
# OPENMEMORY_BACKUP_DIR must be set (via atk setup openmemory or .env).
# The script stops OpenMemory services before backing up (for a consistent
# snapshot), then restarts them when done.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOLUME_NAME="${OPENMEMORY_VOLUME_NAME:-openmemory_data}"

# ─── 1. Check backup directory is configured ─────────────────────────────────
if [[ -z "${OPENMEMORY_BACKUP_DIR:-}" ]]; then
    echo "  ℹ️  OPENMEMORY_BACKUP_DIR is not set — backup skipped."
    echo "  Run 'atk setup openmemory' to configure OPENMEMORY_BACKUP_DIR."
    exit 0
fi

echo "=== OpenMemory Backup ==="
echo "  Backup directory: $OPENMEMORY_BACKUP_DIR"

# ─── 2. Validate backup directory ─────────────────────────────────────────────
if [[ ! -d "$OPENMEMORY_BACKUP_DIR" ]]; then
    echo "  ❌ Backup directory does not exist: $OPENMEMORY_BACKUP_DIR"
    echo "  Create it first: mkdir -p \"$OPENMEMORY_BACKUP_DIR\""
    exit 1
fi

# ─── 3. Check Docker volume exists ────────────────────────────────────────────
if ! docker volume inspect "$VOLUME_NAME" > /dev/null 2>&1; then
    echo "  ❌ Docker volume '$VOLUME_NAME' not found."
    echo "  Is OpenMemory installed? Run: atk install openmemory"
    exit 1
fi

# ─── 4. Check for existing backup ────────────────────────────────────────────
BACKUP_FILENAME="openmemory_backup.tar.gz"
BACKUP_FILE="$OPENMEMORY_BACKUP_DIR/$BACKUP_FILENAME"

if [[ -f "$BACKUP_FILE" ]]; then
    printf "  Backup already exists: %s\n" "$BACKUP_FILE"
    printf "  Overwrite? [Y/n] "
    if [[ -t 0 ]]; then
        read -r response
    else
        response="y"
        echo "y  (non-interactive — overwriting)"
    fi
    case "$response" in
        n|N|no|NO|No)
            echo "  Backup skipped — existing backup preserved."
            exit 0
            ;;
    esac
fi

# ─── 5. Stop services for a consistent snapshot ───────────────────────────────
echo "  Stopping services for safe backup..."
cd "$PLUGIN_DIR"
docker compose down

# ─── 6. Create backup ────────────────────────────────────────────────────────
echo "  Creating backup: $BACKUP_FILE"
docker run --rm \
    -v "${VOLUME_NAME}:/source:ro" \
    -v "${OPENMEMORY_BACKUP_DIR}:/backup" \
    alpine \
    tar czf "/backup/${BACKUP_FILENAME}" -C /source .

BACKUP_SIZE=$(du -sh "$BACKUP_FILE" 2>/dev/null | cut -f1 || echo "unknown size")
echo "  ✅ Backup created: $BACKUP_FILE ($BACKUP_SIZE)"

# ─── 7. Restart services ──────────────────────────────────────────────────────
echo "  Restarting services..."
docker compose up -d

echo "  Waiting for services to become healthy..."
API_OK=false
for i in $(seq 1 15); do
    if curl -sf "${OPENMEMORY_URL}/health" > /dev/null 2>&1; then
        API_OK=true
        break
    fi
    sleep 2
done

if $API_OK; then
    echo "  ✅ Services restarted — API: $OPENMEMORY_URL"
else
    echo "  ⚠️  Services may still be starting — check: docker compose logs"
fi

echo "  ✅ Backup complete"

