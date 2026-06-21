#!/bin/bash
set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PLUGIN_DIR/runtime/server.pid"
LOG_FILE="$PLUGIN_DIR/runtime/server.log"

# When launched directly (not via `atk start`), load the plugin's .env so the
# same CCD_* config applies. `atk start` already injects these.
if [ -f "$PLUGIN_DIR/.env" ]; then
  set -a; . "$PLUGIN_DIR/.env"; set +a
fi
PORT="${PORT:-7878}"

mkdir -p "$PLUGIN_DIR/runtime"

# Reap stale PID file if the process is gone.
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "ERROR: claude-dashboard server already running (pid $OLD_PID)"
    echo "  stop it first: atk stop claude-dashboard"
    exit 1
  fi
  rm -f "$PID_FILE"
fi

# Port conflict check — fail fast with a clear message.
if command -v lsof >/dev/null 2>&1; then
  if lsof -ti tcp:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    BLOCKER=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN | head -1)
    echo "ERROR: port $PORT already in use (pid $BLOCKER)"
    echo "  free it or set PORT in $PLUGIN_DIR/.env"
    exit 1
  fi
fi

# Launch the server detached. CCD_* config + CLAUDE_PROJECTS_DIR flow through
# env. The server's RotatingFileHandler owns server.log; discard the detached
# process's stdout/stderr (nothing useful goes there once logging is up, and a
# pre-logging crash is rare and visible by running serve.py directly).
PYTHONDONTWRITEBYTECODE=1 nohup python3 "$PLUGIN_DIR/server/serve.py" >/dev/null 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
disown "$PID" 2>/dev/null || true

# Health check — retry-poll the API endpoint.
for i in $(seq 1 20); do
  if curl -sf "http://127.0.0.1:$PORT/api/projects.json" >/dev/null 2>&1; then
    echo "✓ claude-dashboard started"
    echo "  pid: $PID · port: $PORT · log: $LOG_FILE"
    echo "  open: http://localhost:$PORT/"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "ERROR: server process exited during startup"
    echo "  last log lines:"
    tail -20 "$LOG_FILE" 2>/dev/null | sed 's/^/    /'
    echo "  (run 'python3 $PLUGIN_DIR/server/serve.py' directly to see startup errors)"
    rm -f "$PID_FILE"
    exit 1
  fi
  sleep 0.25
done

echo "ERROR: server did not become healthy within 5s"
echo "  last log lines:"
tail -20 "$LOG_FILE" 2>/dev/null | sed 's/^/    /'
kill "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
exit 1
