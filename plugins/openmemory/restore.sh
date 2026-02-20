#!/bin/bash
# OpenMemory restore script
# Restores the Docker volume named OPENMEMORY_VOLUME_NAME from OPENMEMORY_BACKUP_DIR.
# ⚠️  DESTRUCTIVE: replaces all current memory data.
#
# Usage (via ATK — env vars injected automatically):
#   atk run openmemory restore
#
# OPENMEMORY_BACKUP_DIR must be set (via atk setup openmemory or .env).
# The script stops OpenMemory services before restoring (for safety),
# clears the volume, extracts the backup, then restarts.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOLUME_NAME="${OPENMEMORY_VOLUME_NAME:-openmemory_data}"
BACKUP_FILENAME="openmemory_backup.tar.gz"
BACKUP_FILE="$OPENMEMORY_BACKUP_DIR/$BACKUP_FILENAME"

# ─── 1. Check backup directory is configured ─────────────────────────────────
if [[ -z "${OPENMEMORY_BACKUP_DIR:-}" ]]; then
    echo "  ℹ️  OPENMEMORY_BACKUP_DIR is not set — restore skipped."
    echo "  Run 'atk setup openmemory' to configure OPENMEMORY_BACKUP_DIR."
    exit 0
fi

echo "=== OpenMemory Restore ==="
echo "  Backup file: $BACKUP_FILE"

# ─── 2. Check backup file exists ──────────────────────────────────────────────
if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "  ❌ Backup file not found: $BACKUP_FILE"
    echo "  Run 'atk run openmemory backup' to create a backup first."
    exit 1
fi

# ─── 3. Check Docker volume exists ────────────────────────────────────────────
if ! docker volume inspect "$VOLUME_NAME" > /dev/null 2>&1; then
    echo "  ❌ Docker volume '$VOLUME_NAME' not found."
    echo "  Is OpenMemory installed? Run: atk install openmemory"
    exit 1
fi

# ─── 4. Destructive operation warning + confirmation ─────────────────────────
echo ""
echo "  ⚠️  WARNING: This will REPLACE all current memory data with the backup."
echo "  Volume:  $VOLUME_NAME"
echo "  Backup:  $BACKUP_FILE"
echo ""
printf "  Proceed? [y/N] "
if [[ -t 0 ]]; then
    read -r response
else
    response="n"
    echo "n  (non-interactive — restore declined for safety)"
fi
case "$response" in
    y|Y|yes|YES|Yes)
        ;;
    *)
        echo "  Restore cancelled — existing data preserved."
        exit 0
        ;;
esac

# ─── 5. Stop services ─────────────────────────────────────────────────────────
echo "  Stopping services..."
cd "$PLUGIN_DIR"
docker compose down

# ─── 6. Clear volume and restore ─────────────────────────────────────────────
echo "  Restoring volume '$VOLUME_NAME' from backup..."
docker run --rm \
    -v "${VOLUME_NAME}:/target" \
    -v "${OPENMEMORY_BACKUP_DIR}:/backup:ro" \
    alpine \
    sh -c "cd /target && find . -mindepth 1 -delete 2>/dev/null || true; tar xzf /backup/${BACKUP_FILENAME}"

echo "  ✅ Volume restored"

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

echo "  ✅ Restore complete"

