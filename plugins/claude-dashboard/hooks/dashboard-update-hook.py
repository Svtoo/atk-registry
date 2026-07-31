#!/usr/bin/env python3
"""Claude Code Stop hook -> dashboard server regen request.

Posts the session UUID to the running claude-dashboard server so it regenerates
that chat's dashboard. Stdlib only: no jq, no curl, no shell. If the server is
down or anything errors, the hook silently no-ops -- the dashboard isn't visible
in that state anyway, and the index has a rebuild button.

The port file's path arrives as argv[1] rather than as a `VAR=value cmd`
environment prefix: that prefix is POSIX-shell syntax, and Claude Code runs hook
commands through the platform shell, so on Windows it fails to parse.

Usage (baked into the hook command by manage.py):
    dashboard-update-hook.py <port_file>
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_PORT = "7878"


def resolve_port() -> str:
    """The server's port: the file it writes at bind time (path in argv[1], since
    the copied hook can't find the plugin dir on its own), else an ambient PORT,
    else the default."""
    if len(sys.argv) > 1 and sys.argv[1]:
        try:
            value = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return os.environ.get("PORT") or DEFAULT_PORT


def main() -> None:
    # Recursion guard: if we're firing INSIDE the headless dashboard subagent's
    # own Stop event, exit immediately. regen.py sets this marker before spawning
    # `claude -p`; `--setting-sources local` is the primary defense, this is
    # belt-and-suspenders.
    if os.environ.get("CLAUDE_DASHBOARD_SUBAGENT"):
        return

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    session = payload.get("session_id")
    if not session:
        return

    request = urllib.request.Request(
        "http://127.0.0.1:%s/api/regen" % resolve_port(),
        data=json.dumps({"session": session}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=2).read()
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
