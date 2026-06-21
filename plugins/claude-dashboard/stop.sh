#!/bin/bash
# No `set -e` per ATK convention — partial cleanup is better than no cleanup.
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PLUGIN_DIR/runtime/server.pid"

# Resolve the port the same way start.sh does, so the stray-process reap targets
# the actual port even when PORT was overridden in .env.
if [ -f "$PLUGIN_DIR/.env" ]; then
  set -a; . "$PLUGIN_DIR/.env"; set +a
fi
PORT="${PORT:-7878}"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE" 2>/dev/null)
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null
    for i in $(seq 1 15); do
      if ! kill -0 "$PID" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "✓ claude-dashboard stopped (pid $PID)"
        exit 0
      fi
      sleep 0.2
    done
    echo "  graceful stop timed out, sending SIGKILL"
    kill -9 "$PID" 2>/dev/null
  fi
  rm -f "$PID_FILE"
fi

# Belt-and-suspenders: kill anything still squatting on the port.
if command -v lsof >/dev/null 2>&1; then
  STRAY=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [ -n "$STRAY" ]; then
    echo "  reaping stray process on port $PORT: $STRAY"
    kill "$STRAY" 2>/dev/null || true
  fi
fi

echo "✓ claude-dashboard stopped"
