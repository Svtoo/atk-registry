#!/usr/bin/env bash
# Claude Code Stop hook -> dashboard server regen request.
#
# Posts the session UUID to the running claude-dashboard server so it
# regenerates that chat's dashboard. Depends ONLY on python3 (already required
# by the plugin): no jq, no curl. If the server is down or anything errors, the
# hook silently no-ops -- the dashboard isn't visible in that state anyway, and
# the index has a rebuild button.

# Recursion guard: if we're firing INSIDE the headless dashboard subagent's own
# Stop event, exit immediately. regen.py sets this marker before spawning
# `claude -p`; `--setting-sources local` is the primary defense, this is
# belt-and-suspenders.
if [ -n "${CLAUDE_DASHBOARD_SUBAGENT:-}" ]; then
  exit 0
fi

# Resolve the server port. Prefer the port file the server writes at bind time
# (its path is baked into the hook command as DASHBOARD_PORT_FILE by the
# installer, since the copied hook can't find the plugin dir on its own); else
# an ambient PORT; else the default 7878.
PORT_FROM_ENV="${PORT:-}"
PORT=""
if [ -n "${DASHBOARD_PORT_FILE:-}" ] && [ -r "${DASHBOARD_PORT_FILE}" ]; then
  PORT="$(cat "${DASHBOARD_PORT_FILE}" 2>/dev/null)"
fi
PORT="${PORT:-${PORT_FROM_ENV:-7878}}"

# Parse session_id from the hook's JSON on stdin and POST the regen request,
# both in a single python3 process. Best-effort and quiet.
INPUT="$(cat)"
printf '%s' "$INPUT" | DASH_PORT="$PORT" python3 -c '
import sys, json, os, urllib.request
try:
    sid = (json.load(sys.stdin) or {}).get("session_id")
except Exception:
    sys.exit(0)
if not sid:
    sys.exit(0)
port = os.environ.get("DASH_PORT", "7878")
req = urllib.request.Request(
    "http://127.0.0.1:%s/api/regen" % port,
    data=json.dumps({"session": sid}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=2).read()
except Exception:
    pass
' 2>/dev/null || true

exit 0
